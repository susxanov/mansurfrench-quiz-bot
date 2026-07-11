import logging
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from config import settings
from db import get_state, set_state, session_scope
from models import DailyBlock, Question
from service import (
    publish_block_by_id,
    regenerate_block_by_id,
    send_for_approval,
)
from telegram_api import (
    answer_callback,
    edit_reply_markup,
    get_updates,
    send_text,
)

log = logging.getLogger(__name__)
cfg = settings()

HELP = """
/status — состояние бота
/prepare morning — подготовить сегодняшнее утро
/prepare evening — подготовить сегодняшний вечер
/force morning — полный тест утреннего цикла в любой день
/force evening — полный тест вечернего цикла в любой день
/pending — показать ожидающие подтверждения
/approve ID — опубликовать блок по ID
/regenerate ID — пересоздать блок по ID
/pause — приостановить автоматическую подготовку
/resume — возобновить автоматическую подготовку
""".strip()


def is_admin(user_id: int) -> bool:
    return user_id == cfg.admin_telegram_user_id


def status_text() -> str:
    with session_scope() as db:
        count = db.scalar(select(func.count(Question.id))) or 0
        pending = (
            db.scalar(
                select(func.count(DailyBlock.id)).where(
                    DailyBlock.status.in_(
                        ["pending_approval", "publishing_failed"]
                    )
                )
            )
            or 0
        )
        last = db.scalar(
            select(DailyBlock).order_by(DailyBlock.id.desc()).limit(1)
        )

    last_text = (
        f"Последний блок: {last.target_date} {last.session} — {last.status}"
        if last
        else "Последних блоков нет."
    )
    return (
        f"Статус: {'пауза' if get_state('paused') == 'true' else 'работает'}\n"
        f"Вопросов в базе: {count}\n"
        f"Ожидают подтверждения/повтора: {pending}\n"
        f"{last_text}"
    )


def _manual_prepare(session: str, force: bool = False):
    now = datetime.now(ZoneInfo(cfg.timezone))
    today = now.date()
    storage_session = session
    if force:
        # A force test must never collide with today's scheduled/published block.
        storage_session = f"test_{session[0]}_{now.strftime('%H%M%S%f')}"
    try:
        result = send_for_approval(
            today,
            storage_session,
            force=force,
        )
        send_text(result, cfg.admin_telegram_user_id)
    except Exception as exc:
        log.exception("Manual preparation failed | force=%s", force)
        send_text(
            f"Ошибка подготовки: {str(exc)[:500]}",
            cfg.admin_telegram_user_id,
        )


def _run_publish(block_id: int):
    try:
        result = publish_block_by_id(block_id)
        send_text(result, cfg.admin_telegram_user_id)
    except Exception as exc:
        log.exception("Manual publication failed | block_id=%s", block_id)
        send_text(
            f"Ошибка публикации: {str(exc)[:500]}",
            cfg.admin_telegram_user_id,
        )


def _run_regenerate(block_id: int, force: bool = False):
    try:
        result = regenerate_block_by_id(block_id, force=force)
        send_text(result, cfg.admin_telegram_user_id)
    except Exception as exc:
        log.exception("Manual regeneration failed | block_id=%s", block_id)
        send_text(
            f"Ошибка пересоздания: {str(exc)[:500]}",
            cfg.admin_telegram_user_id,
        )


def handle_message(text: str, chat_id: int, user_id: int):
    if not is_admin(user_id):
        return

    parts = text.strip().split()
    cmd = parts[0].lower()
    arg = parts[1].lower() if len(parts) > 1 else ""

    if cmd in {"/start", "/help"}:
        send_text(HELP, chat_id)
    elif cmd == "/status":
        send_text(status_text(), chat_id)
    elif cmd == "/pause":
        set_state("paused", "true")
        send_text("Автоматическая подготовка поставлена на паузу.", chat_id)
    elif cmd == "/resume":
        set_state("paused", "false")
        send_text("Автоматическая подготовка возобновлена.", chat_id)
    elif cmd == "/prepare" and arg in {"morning", "evening"}:
        threading.Thread(
            target=_manual_prepare,
            args=(arg, False),
            daemon=True,
        ).start()
        send_text("Подготовка запущена.", chat_id)
    elif cmd == "/force" and arg in {"morning", "evening"}:
        threading.Thread(
            target=_manual_prepare,
            args=(arg, True),
            daemon=True,
        ).start()
        send_text("Полная проверка цикла запущена.", chat_id)
    elif cmd == "/approve" and arg.isdigit():
        threading.Thread(
            target=_run_publish,
            args=(int(arg),),
            daemon=True,
        ).start()
        send_text("Публикация запущена.", chat_id)
    elif cmd == "/regenerate" and arg.isdigit():
        threading.Thread(
            target=_run_regenerate,
            args=(int(arg), False),
            daemon=True,
        ).start()
        send_text("Пересоздание запущено.", chat_id)
    elif cmd == "/pending":
        with session_scope() as db:
            blocks = list(
                db.scalars(
                    select(DailyBlock)
                    .where(
                        DailyBlock.status.in_(
                            ["pending_approval", "publishing_failed"]
                        )
                    )
                    .order_by(DailyBlock.target_date, DailyBlock.session)
                )
            )
        if not blocks:
            send_text("Нет блоков, ожидающих действия.", chat_id)
        else:
            send_text(
                "\n".join(
                    f"{block.id}: {block.target_date} "
                    f"{block.session} {block.level} — {block.status}"
                    for block in blocks
                ),
                chat_id,
            )
    else:
        send_text(HELP, chat_id)


def handle_callback(callback: dict):
    user = callback.get("from") or {}
    if not is_admin(user.get("id", 0)):
        return

    data = callback.get("data", "")
    callback_id = callback.get("id")
    message = callback.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    message_id = message.get("message_id")

    try:
        action, raw_id = data.split(":", 1)
        block_id = int(raw_id)
        answer_callback(callback_id, "Обрабатываю…")

        if action == "approve":
            result = publish_block_by_id(block_id)
        elif action == "regenerate":
            result = regenerate_block_by_id(block_id, force=False)
        elif action == "regenerate_force":
            result = regenerate_block_by_id(block_id, force=True)
        else:
            raise RuntimeError("Неизвестное действие.")

        if chat_id and message_id:
            edit_reply_markup(chat_id, message_id)
        send_text(result, cfg.admin_telegram_user_id)

    except Exception as exc:
        log.exception("Callback failed")
        try:
            answer_callback(callback_id, "Ошибка")
        except Exception:
            log.exception("Failed to answer callback")
        send_text(
            f"Ошибка: {str(exc)[:500]}",
            cfg.admin_telegram_user_id,
        )


def polling_loop():
    offset = int(get_state("telegram_offset", "0"))
    while True:
        for update in get_updates(offset):
            offset = update["update_id"] + 1
            set_state("telegram_offset", str(offset))

            if update.get("callback_query"):
                handle_callback(update["callback_query"])
                continue

            message = update.get("message") or {}
            chat = message.get("chat") or {}
            user = message.get("from") or {}
            text = message.get("text", "")

            if text.startswith("/") and chat.get("type") == "private":
                try:
                    handle_message(text, chat["id"], user["id"])
                except Exception:
                    log.exception("Admin command failed")
                    send_text(
                        "Команда завершилась ошибкой. Проверьте Railway logs.",
                        chat["id"],
                    )


def start_admin():
    threading.Thread(
        target=polling_loop,
        daemon=True,
        name="admin-polling",
    ).start()
