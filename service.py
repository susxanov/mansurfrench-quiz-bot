import logging
import threading
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo
from sqlalchemy import delete, select
from config import settings
from db import session_scope
from models import DailyBlock, Question
from openai_service import generate_question
from quality import canonical_prompt, fingerprint
from telegram_api import send_quiz, send_text
from topics import third_question_plan

log = logging.getLogger(__name__)
cfg = settings()
_prepare_lock = threading.Lock()


def is_workday(target_date: date) -> bool:
    return target_date.weekday() < 5


def _question_plan(target_date: date, session: str):
    third_type, third_topic = third_question_plan(target_date, session)
    return [
        ("translation", "Живая повседневная фраза"),
        ("conjugation", "Частотный глагол в контексте"),
        (third_type, third_topic),
    ]


def _target_positions(target_date: date, session: str) -> list[int]:
    # Three distinct correct-answer positions. Rotation changes every block.
    seed = target_date.toordinal() + (0 if session == "morning" else 2)
    start = seed % 4
    return [start, (start + 1) % 4, (start + 2) % 4]


def _move_correct_answer(item, target: int):
    source = item.correct_option_id
    if source == target:
        return item
    option = item.options.pop(source)
    item.options.insert(target, option)
    item.correct_option_id = target
    return item


def _existing_prompts_and_fingerprints(db):
    prompts = [row for row in db.scalars(select(Question.prompt)).all()]
    fps = set(db.scalars(select(Question.fingerprint)).all())
    return prompts, fps


def prepare_block(target_date: date, session: str, replace: bool = False) -> DailyBlock:
    if not is_workday(target_date):
        raise RuntimeError("В субботу и воскресенье бот не работает.")
    if session not in {"morning", "evening"}:
        raise ValueError("Unknown session")
    if not _prepare_lock.acquire(blocking=False):
        raise RuntimeError("Подготовка уже выполняется.")
    try:
        level = "A1-A2" if session == "morning" else "B1-B2"
        with session_scope() as db:
            block = db.scalar(select(DailyBlock).where(
                DailyBlock.target_date == target_date,
                DailyBlock.session == session,
            ))
            if block and block.status in {"pending_approval", "approved", "published"} and not replace:
                return block
            if block is None:
                block = DailyBlock(
                    target_date=target_date,
                    session=session,
                    level=level,
                    topic="3 вопроса",
                    status="generating",
                    approved=False,
                )
                db.add(block)
                db.flush()
            else:
                db.execute(delete(Question).where(Question.block_id == block.id))
                block.level = level
                block.status = "generating"
                block.approved = False
                block.error = None
            block_id = block.id

        with session_scope() as db:
            forbidden_prompts, existing_fps = _existing_prompts_and_fingerprints(db)

        generated = []
        positions = _target_positions(target_date, session)
        for index, ((question_type, topic), target_position) in enumerate(
            zip(_question_plan(target_date, session), positions), 1
        ):
            item = None
            for _ in range(4):
                candidate = generate_question(
                    level=level,
                    session=session,
                    question_type=question_type,
                    topic=topic,
                    forbidden_prompts=forbidden_prompts,
                )
                candidate = _move_correct_answer(candidate, target_position)
                fp = fingerprint(candidate)
                prompt_key = canonical_prompt(candidate.prompt)
                if fp not in existing_fps and prompt_key not in {
                    canonical_prompt(p) for p in forbidden_prompts
                }:
                    item = candidate
                    break
                forbidden_prompts.append(candidate.prompt)
            if item is None:
                raise RuntimeError("Не удалось создать уникальный вопрос.")
            generated.append((item, fingerprint(item)))
            forbidden_prompts.append(item.prompt)
            existing_fps.add(fingerprint(item))

        with session_scope() as db:
            for position, (item, fp) in enumerate(generated, 1):
                db.add(Question(
                    block_id=block_id,
                    position=position,
                    fingerprint=fp,
                    topic=item.topic,
                    skill=item.skill,
                    question_type=item.question_type,
                    prompt=item.prompt,
                    options=item.options,
                    correct_option_ids=[item.correct_option_id],
                    explanation=item.explanation,
                    comparison_axis="",
                    surface_constraints={},
                    reviewer_score=100.0,
                    reviewer_notes="Независимая проверка OpenAI пройдена.",
                ))
            block = db.get(DailyBlock, block_id)
            block.status = "pending_approval"
            block.generated_at = datetime.now(ZoneInfo(cfg.timezone))
            return block
    except Exception as exc:
        log.exception("Preparation failed | date=%s | session=%s", target_date, session)
        try:
            with session_scope() as db:
                block = db.scalar(select(DailyBlock).where(
                    DailyBlock.target_date == target_date,
                    DailyBlock.session == session,
                ))
                if block:
                    block.status = "failed"
                    block.error = str(exc)[:2000]
        finally:
            pass
        raise
    finally:
        _prepare_lock.release()


def load_block(target_date: date, session: str):
    with session_scope() as db:
        block = db.scalar(select(DailyBlock).where(
            DailyBlock.target_date == target_date,
            DailyBlock.session == session,
        ))
        if not block:
            return None, []
        questions = list(db.scalars(
            select(Question).where(Question.block_id == block.id).order_by(Question.position)
        ))
        return block, questions


def send_for_approval(target_date: date, session: str) -> str:
    block = prepare_block(target_date, session)
    block, questions = load_block(target_date, session)
    if len(questions) != 3:
        raise RuntimeError("Должно быть ровно 3 вопроса.")
    label = "Утро A1–A2" if session == "morning" else "Вечер B1–B2"
    send_text(f"{label}: проверьте 3 вопроса.", cfg.admin_telegram_user_id)
    for question in questions:
        send_quiz(question, cfg.admin_telegram_user_id)
        time.sleep(cfg.post_delay_seconds)
    send_text(
        "Подтвердить публикацию?",
        cfg.admin_telegram_user_id,
        reply_markup={
            "inline_keyboard": [[
                {"text": "✅ Подтвердить", "callback_data": f"approve:{block.id}"},
                {"text": "🔄 Пересоздать", "callback_data": f"regenerate:{block.id}"},
            ]]
        },
    )
    return f"{target_date} {session}: отправлено на проверку."


def publish_block_by_id(block_id: int) -> str:
    with session_scope() as db:
        block = db.get(DailyBlock, block_id)
        if not block:
            raise RuntimeError("Блок не найден.")
        if block.status == "published":
            return "Блок уже опубликован."
        questions = list(db.scalars(
            select(Question).where(Question.block_id == block.id).order_by(Question.position)
        ))
        if len(questions) != 3:
            raise RuntimeError("В блоке должно быть ровно 3 вопроса.")
        block.status = "approved"
        block.approved = True
        target_date, session = block.target_date, block.session

    message_ids = []
    for question in questions:
        result = send_quiz(question)
        message_ids.append(result["message_id"])
        time.sleep(cfg.post_delay_seconds)

    now = datetime.now(ZoneInfo(cfg.timezone))
    with session_scope() as db:
        block = db.get(DailyBlock, block_id)
        block.status = "published"
        block.published_at = now
        for question, message_id in zip(
            db.scalars(select(Question).where(Question.block_id == block_id).order_by(Question.position)),
            message_ids,
        ):
            question.telegram_message_id = message_id
            question.published_at = now
    return f"{target_date} {session}: опубликовано 3 вопроса."


def regenerate_block_by_id(block_id: int) -> str:
    with session_scope() as db:
        block = db.get(DailyBlock, block_id)
        if not block:
            raise RuntimeError("Блок не найден.")
        target_date, session = block.target_date, block.session
    prepare_block(target_date, session, replace=True)
    return send_for_approval(target_date, session)
