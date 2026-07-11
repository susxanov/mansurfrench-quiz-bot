import json
import logging
import re
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
- верни ТОЛЬКО один JSON-объект без Markdown и без ```;
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

JSON должен содержать ровно эти поля:
{
  "topic": "строка",
  "skill": "строка",
  "level": "A1-A2 или B1-B2",
  "question_type": "translation, conjugation, lexicon или grammar_pronouns",
  "prompt": "строка",
  "options": ["вариант 1", "вариант 2", "вариант 3", "вариант 4"],
  "correct_option_id": 0,
  "explanation": "краткое объяснение по-русски"
}
correct_option_id — индекс от 0 до 3.
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

Верни ТОЛЬКО один JSON-объект без Markdown и без ```:
{
  "approved": true,
  "verified_correct_option_id": 0,
  "issues": [],
  "explanation_check": "краткий вывод"
}
approved=true разрешено только при полной корректности.
verified_correct_option_id укажи всегда.
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


def _extract_output_text(response) -> str:
    """Extract text from Responses API without relying on output_parsed."""
    direct = getattr(response, "output_text", None)
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    chunks: list[str] = []
    for output_item in getattr(response, "output", None) or []:
        for content_item in getattr(output_item, "content", None) or []:
            text = getattr(content_item, "text", None)
            if isinstance(text, str) and text.strip():
                chunks.append(text)
            elif text is not None:
                value = getattr(text, "value", None)
                if isinstance(value, str) and value.strip():
                    chunks.append(value)

    if chunks:
        return "\n".join(chunks).strip()
    raise RuntimeError("OpenAI returned no text output")


def _clean_json_text(raw: str) -> str:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)

    # If the model added a short prefix/suffix, isolate the outer JSON object.
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    return text.strip()


def _request_json(*, model: str, instructions: str, user_input: str, schema: type[T], max_output_tokens: int) -> T:
    response = client.responses.create(
        model=model,
        instructions=instructions,
        input=user_input,
        max_output_tokens=max_output_tokens,
    )
    raw = _extract_output_text(response)
    cleaned = _clean_json_text(raw)

    try:
        payload = json.loads(cleaned)
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
        max_output_tokens=900,
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
                max_output_tokens=1600,
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
