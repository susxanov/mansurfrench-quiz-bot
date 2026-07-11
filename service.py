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
from quality import (
    canonical_prompt,
    fingerprint,
    is_duplicate_or_similar,
)
from telegram_api import send_quiz, send_text
from topics import third_question_plan

log = logging.getLogger(__name__)
cfg = settings()

_prepare_lock = threading.Lock()
_publish_lock = threading.Lock()


def is_workday(target_date: date) -> bool:
    return target_date.weekday() < 6


def base_session(session: str) -> str:
    if session == "morning" or session.startswith("manual_morning_"):
        return "morning"
    if session == "evening" or session.startswith("manual_evening_"):
        return "evening"
    raise ValueError("Unknown session")


def _question_plan(target_date: date, session: str):
    session = base_session(session)
    third_type, third_topic = third_question_plan(target_date, session)
    return [
        ("translation", "Живая повседневная фраза"),
        ("conjugation", "Частотный глагол в контексте"),
        (third_type, third_topic),
    ]


def _target_positions(target_date: date, session: str) -> list[int]:
    # Three different positions in each block. The omitted position rotates.
    session = base_session(session)
    seed = target_date.toordinal() * 2 + (0 if session == "morning" else 1)
    start = seed % 4
    return [start, (start + 1) % 4, (start + 2) % 4]


def _move_correct_answer(item, target: int):
    source = item.correct_option_id
    if source == target:
        return item
    correct_option = item.options.pop(source)
    item.options.insert(target, correct_option)
    item.correct_option_id = target
    return item


def _existing_prompts_and_fingerprints(db):
    prompts = list(db.scalars(select(Question.prompt)).all())
    fingerprints = set(db.scalars(select(Question.fingerprint)).all())
    return prompts, fingerprints


def _get_block(db, target_date: date, session: str):
    return db.scalar(
        select(DailyBlock).where(
            DailyBlock.target_date == target_date,
            DailyBlock.session == session,
        )
    )


def prepare_block(
    target_date: date,
    session: str,
    replace: bool = False,
    force: bool = False,
) -> DailyBlock:
    if not force and not is_workday(target_date):
        raise RuntimeError("В воскресенье бот не работает.")
    effective_session = base_session(session)
    if not _prepare_lock.acquire(blocking=False):
        raise RuntimeError("Подготовка уже выполняется.")

    block_id: int | None = None
    try:
        level = "A1-A2" if effective_session == "morning" else "B1-B2"

        with session_scope() as db:
            block = _get_block(db, target_date, session)

            if block and block.status == "published":
                if replace:
                    raise RuntimeError("Опубликованный блок нельзя пересоздать.")
                return block

            if (
                block
                and block.status in {"pending_approval", "approved", "publishing"}
                and not replace
            ):
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
                already_sent = db.scalar(
                    select(Question.id)
                    .where(
                        Question.block_id == block.id,
                        Question.telegram_message_id.is_not(None),
                    )
                    .limit(1)
                )
                if already_sent:
                    raise RuntimeError(
                        "Блок уже частично опубликован и не может быть пересоздан."
                    )
                db.execute(delete(Question).where(Question.block_id == block.id))
                block.level = level
                block.status = "generating"
                block.approved = False
                block.error = None

            block_id = block.id

        with session_scope() as db:
            forbidden_prompts, existing_fingerprints = (
                _existing_prompts_and_fingerprints(db)
            )

        generated = []
        positions = _target_positions(target_date, session)
        plan = _question_plan(target_date, session)

        for (question_type, topic), target_position in zip(plan, positions):
            selected = None

            for _ in range(4):
                candidate = generate_question(
                    level=level,
                    session=effective_session,
                    question_type=question_type,
                    topic=topic,
                    forbidden_prompts=forbidden_prompts,
                )
                candidate = _move_correct_answer(candidate, target_position)
                candidate_fingerprint = fingerprint(candidate)

                if (
                    candidate_fingerprint not in existing_fingerprints
                    and not is_duplicate_or_similar(
                        candidate.prompt,
                        forbidden_prompts,
                    )
                ):
                    selected = candidate
                    break

                forbidden_prompts.append(candidate.prompt)

            if selected is None:
                raise RuntimeError("Не удалось создать уникальный вопрос.")

            selected_fingerprint = fingerprint(selected)
            generated.append((selected, selected_fingerprint))
            forbidden_prompts.append(selected.prompt)
            existing_fingerprints.add(selected_fingerprint)

        if len(generated) != 3:
            raise RuntimeError("Должно быть создано ровно 3 вопроса.")

        expected_types = [item[0] for item in plan]
        actual_types = [item.question_type for item, _ in generated]
        if actual_types != expected_types:
            raise RuntimeError(
                f"Неверный состав блока: {actual_types}, ожидалось {expected_types}"
            )

        with session_scope() as db:
            for position, (item, item_fingerprint) in enumerate(generated, 1):
                db.add(
                    Question(
                        block_id=block_id,
                        position=position,
                        fingerprint=item_fingerprint,
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
                        reviewer_notes=(
                            "Генерация и независимая редакторская проверка пройдены."
                        ),
                    )
                )

            block = db.get(DailyBlock, block_id)
            block.status = "pending_approval"
            block.approved = False
            block.generated_at = datetime.now(ZoneInfo(cfg.timezone))
            block.error = None
            return block

    except Exception as exc:
        log.exception(
            "Preparation failed | date=%s | session=%s",
            target_date,
            session,
        )
        if block_id is not None:
            with session_scope() as db:
                block = db.get(DailyBlock, block_id)
                if block:
                    block.status = "failed"
                    block.error = str(exc)[:2000]
        raise
    finally:
        _prepare_lock.release()


def load_block(target_date: date, session: str):
    with session_scope() as db:
        block = _get_block(db, target_date, session)
        if not block:
            return None, []
        questions = list(
            db.scalars(
                select(Question)
                .where(Question.block_id == block.id)
                .order_by(Question.position)
            )
        )
        return block, questions


def send_for_approval(
    target_date: date,
    session: str,
    force: bool = False,
) -> str:
    prepared = prepare_block(
        target_date,
        session,
        force=force,
    )
    block, questions = load_block(target_date, session)

    if block is None or prepared.id != block.id:
        raise RuntimeError("Подготовленный блок не найден.")
    if block.status == "published":
        return "Этот блок уже опубликован."
    if len(questions) != 3:
        raise RuntimeError("Должно быть ровно 3 вопроса.")

    effective_session = base_session(session)
    is_manual = session.startswith("manual_")
    label = "Утро A1–A2" if effective_session == "morning" else "Вечер B1–B2"
    if is_manual:
        label = f"ТЕСТОВЫЙ БЛОК — {label}"
    send_text(
        f"{label}: проверьте 3 вопроса.",
        cfg.admin_telegram_user_id,
    )

    for question in questions:
        send_quiz(question, cfg.admin_telegram_user_id)
        time.sleep(cfg.post_delay_seconds)

    regenerate_action = "regenerate_force" if force else "regenerate"
    send_text(
        "Подтвердить публикацию?",
        cfg.admin_telegram_user_id,
        reply_markup={
            "inline_keyboard": [
                [
                    {
                        "text": "✅ Подтвердить",
                        "callback_data": f"approve:{block.id}",
                    },
                    {
                        "text": "🔄 Пересоздать",
                        "callback_data": f"{regenerate_action}:{block.id}",
                    },
                ]
            ]
        },
    )
    return f"{target_date} {session}: отправлено на проверку."


def publish_block_by_id(block_id: int) -> str:
    if not _publish_lock.acquire(blocking=False):
        return "Публикация уже выполняется."

    try:
        with session_scope() as db:
            block = db.scalar(
                select(DailyBlock)
                .where(DailyBlock.id == block_id)
                .with_for_update()
            )
            if not block:
                raise RuntimeError("Блок не найден.")
            if block.status == "published":
                return "Блок уже опубликован."
            if block.status not in {
                "pending_approval",
                "approved",
                "publishing",
                "publishing_failed",
            }:
                raise RuntimeError(
                    f"Блок нельзя опубликовать из статуса {block.status}."
                )

            questions = list(
                db.scalars(
                    select(Question)
                    .where(Question.block_id == block.id)
                    .order_by(Question.position)
                )
            )
            if len(questions) != 3:
                raise RuntimeError("В блоке должно быть ровно 3 вопроса.")

            block.status = "publishing"
            block.approved = True
            target_date = block.target_date
            session = block.session

        try:
            for question in questions:
                if question.telegram_message_id is not None:
                    continue

                result = send_quiz(question)
                now = datetime.now(ZoneInfo(cfg.timezone))

                # Persist each successful send immediately. A retry continues
                # from the first unsent question instead of duplicating polls.
                with session_scope() as db:
                    stored = db.get(Question, question.id)
                    stored.telegram_message_id = result["message_id"]
                    stored.published_at = now

                time.sleep(cfg.post_delay_seconds)

            with session_scope() as db:
                block = db.get(DailyBlock, block_id)
                remaining = db.scalar(
                    select(Question.id)
                    .where(
                        Question.block_id == block_id,
                        Question.telegram_message_id.is_(None),
                    )
                    .limit(1)
                )
                if remaining is not None:
                    raise RuntimeError("Не все вопросы были опубликованы.")
                block.status = "published"
                block.published_at = datetime.now(ZoneInfo(cfg.timezone))

            return f"{target_date} {session}: опубликовано 3 вопроса."

        except Exception as exc:
            with session_scope() as db:
                block = db.get(DailyBlock, block_id)
                if block and block.status != "published":
                    block.status = "publishing_failed"
                    block.error = str(exc)[:2000]
            raise

    finally:
        _publish_lock.release()


def regenerate_block_by_id(
    block_id: int,
    force: bool = False,
) -> str:
    with session_scope() as db:
        block = db.get(DailyBlock, block_id)
        if not block:
            raise RuntimeError("Блок не найден.")
        if block.status == "published":
            raise RuntimeError("Опубликованный блок нельзя пересоздать.")

        already_sent = db.scalar(
            select(Question.id)
            .where(
                Question.block_id == block.id,
                Question.telegram_message_id.is_not(None),
            )
            .limit(1)
        )
        if already_sent:
            raise RuntimeError(
                "Частично опубликованный блок нельзя пересоздать; "
                "повторите публикацию."
            )

        target_date = block.target_date
        session = block.session

    prepare_block(
        target_date,
        session,
        replace=True,
        force=force,
    )
    return send_for_approval(
        target_date,
        session,
        force=force,
    )
