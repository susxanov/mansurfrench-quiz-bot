import logging
import time

from openai import OpenAI

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

GENERATOR_RULES = """
Ты — профессиональный методист FLE для русскоязычных взрослых.
Создай ОДИН современный и естественный вопрос.

ЖЁСТКИЕ ПРАВИЛА:
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
Ты — независимый старший редактор FLE.
Проверь вопрос без доверия к автору.

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


def _review(question: CandidateQuestion) -> ReviewResult:
    response = client.responses.parse(
        model=cfg.openai_reviewer_model,
        instructions=REVIEWER_RULES,
        input=question.model_dump_json(),
        text_format=ReviewResult,
        max_output_tokens=900,
    )
    if response.output_parsed is None:
        raise RuntimeError("Reviewer returned no parsed result")
    return response.output_parsed


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
            response = client.responses.parse(
                model=cfg.openai_model,
                instructions=GENERATOR_RULES,
                input=_generation_prompt(
                    level,
                    session,
                    question_type,
                    topic,
                    forbidden_prompts,
                ),
                text_format=CandidateQuestion,
                max_output_tokens=1600,
            )
            item = response.output_parsed
            if item is None:
                raise RuntimeError("Generator returned no parsed question")

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
