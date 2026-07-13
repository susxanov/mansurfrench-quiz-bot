import json
import logging
import time
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from config import settings
from quality import validate_question
from schemas import CandidateQuestion, ReviewResult
from text_utils import clean_quiz_prompt

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
- объяснение должно быть полностью завершённым, состоять из 1–2 коротких предложений,
  занимать 70–170 символов и заканчиваться точкой; не обрывай слова, цитаты или правило;
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

approved=false ставь только при БЛОКИРУЮЩЕЙ ошибке: неверный ответ,
второй допустимый ответ, неестественная/ошибочная французская фраза,
неверное русское объяснение или явное несоответствие уровню/типу.
Не отклоняй вопрос из-за необязательной стилистической рекомендации или потому,
что он ближе к одному уровню внутри указанного диапазона.
Если approved=true, issues должен быть пустым массивом.
verified_correct_option_id укажи всегда.
Верни только JSON, строго соответствующий переданной схеме.
""".strip()


def _generation_prompt(
    level: str,
    session: str,
    question_type: str,
    topic: str,
    forbidden_prompts: list[str],
    correction_feedback: str | None = None,
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
        "translation": (
            "Перевод одной живой фразы с русского на французский. "
            "Prompt должен быть полностью на русском и НЕ содержать пропусков. "
            "Все 4 options должны быть полными французскими предложениями. "
            "Сохрани точный временной смысл исходной русской фразы. "
            "Если используется «бы», добавь явный контекст настоящего или прошлого, "
            "чтобы условная конструкция была однозначной."
        ),
        "conjugation": (
            "Выбор правильной формы частотного французского глагола в контексте. "
            "Prompt обязан содержать ровно один пропуск ___; options должны содержать "
            "только формы, которые можно буквально подставить в этот пропуск. "
            "Если местоимение te/t’, lui, en, y уже стоит перед пропуском, не повторяй его в options."
        ),
        "lexicon": f"Лексический вопрос по теме: {topic}.",
        "grammar_pronouns": f"Грамматический вопрос по теме: {topic}.",
    }[question_type]
    recent_items = [str(prompt)[:180] for prompt in forbidden_prompts[-25:]]
    recent = "\n".join(f"- {prompt}" for prompt in recent_items) or "- нет"

    correction = (
        "\nИсправь конкретные ошибки предыдущей попытки. Не повторяй отклонённую конструкцию:\n"
        + correction_feedback[:1800]
        if correction_feedback
        else ""
    )

    return f"""
Сессия: {session}
Уровень: {level}
Тип: {question_type}
{level_rules}
{type_rules}
{correction}

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
    reasoning_effort: str,
) -> T:
    # GPT-5 models may spend part of max_completion_tokens on internal
    # reasoning. A tiny JSON answer can therefore finish with reason=length.
    # Retry only that technical truncation with a larger budget.
    # The maximum is a ceiling, not prepaid usage: billing is based on tokens
    # actually consumed. Start with enough room for GPT-5 mini reasoning, then
    # double only when the API explicitly reports finish_reason=length.
    budgets = [
        min(max_completion_tokens, 128000),
        min(max_completion_tokens * 2, 128000),
        min(max_completion_tokens * 4, 128000),
    ]
    effort_ladder = {
        "high": ["high", "medium", "low"],
        "medium": ["medium", "low", "minimal"],
        "low": ["low", "minimal", "minimal"],
        "minimal": ["minimal", "minimal", "minimal"],
    }[reasoning_effort]
    last_error: RuntimeError | None = None

    for attempt, (budget, effort) in enumerate(
        zip(budgets, effort_ladder), start=1
    ):
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": instructions},
                {"role": "user", "content": user_input},
            ],
            response_format=_json_schema_for(schema, schema_name),
            reasoning_effort=effort,
            max_completion_tokens=budget,
        )

        if not completion.choices:
            last_error = RuntimeError("OpenAI returned no choices")
            continue

        choice = completion.choices[0]
        message = choice.message

        usage = getattr(completion, "usage", None)
        if usage is not None:
            details = getattr(usage, "completion_tokens_details", None)
            reasoning_tokens = (
                getattr(details, "reasoning_tokens", None) if details else None
            )
            log.info(
                "OpenAI usage | schema=%s | model=%s | attempt=%s | "
                "effort=%s | budget=%s | prompt=%s | completion=%s | "
                "reasoning=%s | finish=%s",
                schema_name,
                model,
                attempt,
                effort,
                budget,
                getattr(usage, "prompt_tokens", None),
                getattr(usage, "completion_tokens", None),
                reasoning_tokens,
                choice.finish_reason,
            )

        refusal = getattr(message, "refusal", None)
        if refusal:
            raise RuntimeError(f"OpenAI refused the request: {refusal}")

        raw = message.content
        if choice.finish_reason == "length":
            last_error = RuntimeError(
                "OpenAI response was truncated by the token limit "
                f"(attempt={attempt}, budget={budget}, effort={effort})"
            )
            log.warning(
                "Structured response truncated; retrying | schema=%s | "
                "attempt=%s | budget=%s | effort=%s",
                schema_name,
                attempt,
                budget,
                effort,
            )
            continue

        if not isinstance(raw, str) or not raw.strip():
            last_error = RuntimeError(
                "OpenAI returned an empty structured response "
                f"(finish_reason={choice.finish_reason}, attempt={attempt}, "
                f"budget={budget})"
            )
            if attempt < len(budgets):
                continue
            break

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
                f"OpenAI JSON does not match schema: {exc.errors()[:3]} | "
                f"raw={raw[:500]}"
            ) from exc

    raise last_error or RuntimeError("OpenAI failed to return structured JSON")


def _review(question: CandidateQuestion) -> ReviewResult:
    return _request_json(
        model=cfg.openai_reviewer_model,
        instructions=REVIEWER_RULES,
        user_input=question.model_dump_json(ensure_ascii=False),
        schema=ReviewResult,
        schema_name="french_quiz_review",
        max_completion_tokens=cfg.reviewer_max_completion_tokens,
        reasoning_effort=cfg.reviewer_reasoning_effort,
    )


def generate_question(
    level: str,
    session: str,
    question_type: str,
    topic: str,
    forbidden_prompts: list[str],
) -> CandidateQuestion:
    last_error: Exception | None = None
    correction_feedback: str | None = None

    for attempt in range(1, 6):
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
                    correction_feedback,
                ),
                schema=CandidateQuestion,
                schema_name="french_quiz_question",
                max_completion_tokens=cfg.generator_max_completion_tokens,
                reasoning_effort=cfg.generator_reasoning_effort,
            )

            raw_prompt = item.prompt
            item.prompt = clean_quiz_prompt(item.prompt)

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
            correction_feedback = str(exc)
            log.warning(
                "Question attempt failed | session=%s | type=%s | "
                "attempt=%s | error=%s",
                session,
                question_type,
                attempt,
                str(exc)[:700],
                exc_info=True,
            )
            if attempt < 5:
                time.sleep(min(2 ** attempt, 12))

    raise RuntimeError(f"Не удалось создать проверенный вопрос: {last_error}")
