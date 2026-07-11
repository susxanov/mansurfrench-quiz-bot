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
- только сам вопрос, без Exercice, номера, дня, служебного кода, заголовка и лишних символов;
- ровно 4 разных, правдоподобных и сопоставимых варианта;
- ровно один правильный ответ;
- объяснение по-русски: почему ответ правильный и почему ключевая ошибка неверна;
- французский современный, естественный и реально употребимый во Франции;
- никаких искусственных или нелепых фраз;
- не повторять примеры, переданные в списке запретов;
- вопрос должен точно соответствовать заявленному уровню.
""".strip()

REVIEWER_RULES = """
Ты — независимый старший редактор FLE.
Проверь вопрос максимально строго:
1) грамматика и орфография французского;
2) естественность современной речи;
3) единственность правильного ответа;
4) соответствие уровню;
5) корректность русского объяснения;
6) отсутствие двусмысленности и нелепых дистракторов.
Одобряй только полностью корректный вопрос.
""".strip()


def _generation_prompt(level: str, session: str, question_type: str, topic: str, forbidden_prompts: list[str]) -> str:
    level_rules = (
        "A1-A2: présent, passé composé, futur proche/futur simple, базовая повседневная речь."
        if level == "A1-A2"
        else
        "B1-B2: все частотные времена и наклонения, включая conditionnel и subjonctif, сложные местоимения и живую речь."
    )
    type_rules = {
        "translation": "Вопрос: перевод одной живой русской фразы на французский.",
        "conjugation": "Вопрос: выбор правильной формы одного частотного французского глагола в контексте.",
        "lexicon": f"Вопрос по лексической теме: {topic}.",
        "grammar_pronouns": f"Вопрос по грамматике/местоимениям: {topic}.",
    }[question_type]
    recent = "\n".join(f"- {p}" for p in forbidden_prompts[-40:]) or "- нет"
    return f"""
Сессия: {session}
Уровень: {level}
{level_rules}
{type_rules}

Не используй и не перефразируй слишком близко эти недавние вопросы:
{recent}

Верни один вопрос типа {question_type}.
""".strip()


def _review(question: CandidateQuestion) -> ReviewResult:
    return client.responses.parse(
        model=cfg.openai_reviewer_model,
        instructions=REVIEWER_RULES,
        input=question.model_dump_json(),
        text_format=ReviewResult,
        max_output_tokens=900,
    ).output_parsed


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
                input=_generation_prompt(level, session, question_type, topic, forbidden_prompts),
                text_format=CandidateQuestion,
                max_output_tokens=1600,
            )
            item = response.output_parsed
            if item is None:
                raise RuntimeError("No parsed question")
            item.prompt = clean_quiz_prompt(item.prompt)
            item.explanation = clip_explanation(item.explanation)
            errors = validate_question(item, level, question_type)
            if errors:
                raise RuntimeError(", ".join(errors))

            review = _review(item)
            if review is None or not review.approved:
                issues = ", ".join(review.issues if review else ["review_missing"])
                raise RuntimeError(f"Reviewer rejected: {issues}")
            if review.corrected_correct_option_id is not None:
                item.correct_option_id = review.corrected_correct_option_id

            log.info(
                "Question approved | session=%s | level=%s | type=%s | attempt=%s | elapsed=%.1fs",
                session, level, question_type, attempt, time.monotonic() - started,
            )
            return item
        except Exception as exc:
            last_error = exc
            log.warning(
                "Question generation attempt failed | session=%s | type=%s | attempt=%s | error=%s",
                session, question_type, attempt, str(exc)[:500],
                exc_info=True,
            )
            if attempt < 4:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Не удалось создать проверенный вопрос: {last_error}")
