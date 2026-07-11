import json
import logging
import time
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from config import settings
from quality import validate_question
from schemas import CandidateQuestion, ReviewResult
from text_utils import clean_quiz_prompt, clip_explanation

log = logging.getLogger(__name__)
cfg = settings()

client = OpenAI(
    api_key=cfg.openai_api_key,
    timeout=cfg.openai_timeout_seconds,
    max_retries=2,
)

T = TypeVar("T", bound=BaseModel)

GENERATOR_RULES = """
Ты — профессиональный методист FLE для русскоязычных взрослых.
Создай ОДИН современный и естественный вопрос.

ЖЁСТКИЕ ПРАВИЛА:
- верни только JSON, строго соответствующий переданной схеме;
- выводи только сам вопрос, без Exercice, Exercise, Question, номера, даты,
  служебного кода, заголовка, уровня и внутренних комментариев;
- ровно 4 разных и сопоставимых варианта;
- ровно один правильный ответ;
- неправильные варианты должны быть правдоподобными ошибками ученика;
- объяснение обязательно на русском языке: почему ответ правильный;
- французский должен быть современным и реально употребимым во Франции;
- никаких искусственных, двусмысленных или нелепых фраз;
- не повторяй и не перефразируй близко вопросы из списка запретов;
- вопрос должен строго соответствовать заявленному уровню и типу.
""".strip()

REVIEWER_RULES = """
Ты — независимый старший редактор FLE. Проверь вопрос без доверия к автору.

Проверь:
1. французскую грамматику и орфографию;
2. естественность современной речи;
3. что существует ровно один правильный вариант;
4. точный индекс правильного ответа от 0 до 3;
5. соответствие уровню A1–A2 или B1–B2;
6. соответствие типу задания;
7. корректность русского объяснения;
8. отсутствие двусмысленности и нелепых дистракторов.

approved=true разрешено только при полной корректности.
verified_correct_option_id укажи всегда.
Верни только JSON, строго соответствующий переданной схеме.
""".strip()


def _generation_prompt(
    level: str,
    session: str,
    question_type: str,
    topic: str,
    forbidden_prompts: list[str],
) -> str:
    level_rules = (
        "A1–A2: présent, passé composé, futur proche или futur simple; "
        "простая живая повседневная речь."
        if level == "A1-A2"
        else
        "B1–B2: частотные времена и наклонения, включая conditionnel и "
        "subjonctif; сложные местоимения и естественная живая речь."
    )
    type_rules = {
        "translation": "Перевод одной живой фразы с русского на французский.",
        "conjugation": "Выбор правильной формы частотного французского глагола в контексте.",
        "lexicon": f"Лексический вопрос по теме: {topic}.",
        "grammar_pronouns": f"Грамматический вопрос по теме: {topic}.",
    }[question_type]
    recent = "\n".join(f"- {prompt}" for prompt in forbidden_prompts[-60:]) or "- нет"

    return f"""
Сессия: {session}
Уровень: {level}
Тип: {question_type}
{level_rules}
{type_rules}

Запрещено повторять или близко перефразировать:
{recent}
""".strip()


def _strict_json_schema(schema: type[T]) -> dict:
    """Build an OpenAI-compatible strict JSON schema.

    OpenAI strict structured outputs require every property to be listed in
    ``required`` and every object to reject unspecified properties. Pydantic
    omits fields with defaults from ``required``, so we normalize recursively
    before the request reaches the API.
    """
    raw = schema.model_json_schema()

    def normalize(node):
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                node["required"] = list(properties.keys())
                node["additionalProperties"] = False
            for value in node.values():
                normalize(value)
        elif isinstance(node, list):
            for value in node:
                normalize(value)

    normalize(raw)
    return raw


def _json_schema_for(schema: type[T], name: str) -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "strict": True,
            "schema": _strict_json_schema(schema),
        },
    }


def _request_json(
    *,
    model: str,
    instructions: str,
    user_input: str,
    schema: type[T],
    schema_name: str,
    max_completion_tokens: int,
) -> T:
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": instructions},
            {"role": "user", "content": user_input},
        ],
        response_format=_json_schema_for(schema, schema_name),
        reasoning_effort="low",
        max_completion_tokens=max_completion_tokens,
    )

    if not completion.choices:
        raise RuntimeError("OpenAI returned no choices")

    choice = completion.choices[0]
    message = choice.message

    refusal = getattr(message, "refusal", None)
    if refusal:
        raise RuntimeError(f"OpenAI refused the request: {refusal}")

    if choice.finish_reason == "length":
        raise RuntimeError("OpenAI response was truncated by the token limit")

    raw = message.content
    if not isinstance(raw, str) or not raw.strip():
        raise RuntimeError(
            "OpenAI returned an empty structured response "
            f"(finish_reason={choice.finish_reason})"
        )

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"OpenAI returned invalid JSON: {exc.msg} | raw={raw[:500]}"
        ) from exc

    try:
        return schema.model_validate(payload)
    except ValidationError as exc:
        raise RuntimeError(
            f"OpenAI JSON does not match schema: {exc.errors()[:3]} | raw={raw[:500]}"
        ) from exc


def _review(question: CandidateQuestion) -> ReviewResult:
    return _request_json(
        model=cfg.openai_reviewer_model,
        instructions=REVIEWER_RULES,
        user_input=question.model_dump_json(ensure_ascii=False),
        schema=ReviewResult,
        schema_name="french_quiz_review",
        max_completion_tokens=1800,
    )


def generate_question(
    level: str,
    session: str,
    question_type: str,
    topic: str,
    forbidden_prompts: list[str],
) -> CandidateQuestion:
    last_error: Exception | None = None

    for attempt in range(1, 5):
        started = time.monotonic()
        try:
            item = _request_json(
                model=cfg.openai_model,
                instructions=GENERATOR_RULES,
                user_input=_generation_prompt(
                    level,
                    session,
                    question_type,
                    topic,
                    forbidden_prompts,
                ),
                schema=CandidateQuestion,
                schema_name="french_quiz_question",
                max_completion_tokens=2600,
            )

            raw_prompt = item.prompt
            item.prompt = clean_quiz_prompt(item.prompt)
            item.explanation = clip_explanation(item.explanation)

            errors = validate_question(
                item,
                expected_level=level,
                expected_type=question_type,
                raw_prompt=raw_prompt,
            )
            if errors:
                raise RuntimeError("Validation failed: " + ", ".join(errors))

            review = _review(item)
            if not review.approved:
                raise RuntimeError(
                    "Reviewer rejected: " + ", ".join(review.issues or ["unspecified"])
                )
            if review.verified_correct_option_id != item.correct_option_id:
                raise RuntimeError(
                    "Generator/reviewer correct-answer mismatch: "
                    f"{item.correct_option_id} != {review.verified_correct_option_id}"
                )

            log.info(
                "Question approved | session=%s | level=%s | type=%s | "
                "attempt=%s | elapsed=%.1fs",
                session,
                level,
                question_type,
                attempt,
                time.monotonic() - started,
            )
            return item

        except Exception as exc:
            last_error = exc
            log.warning(
                "Question attempt failed | session=%s | type=%s | "
                "attempt=%s | error=%s",
                session,
                question_type,
                attempt,
                str(exc)[:700],
                exc_info=True,
            )
            if attempt < 4:
                time.sleep(2 ** attempt)

    raise RuntimeError(f"Не удалось создать проверенный вопрос: {last_error}")
