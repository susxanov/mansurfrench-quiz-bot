import logging
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import func, select
from config import settings
from db import get_state, set_state, session_scope
from models import DailyBlock, Question
from service import (
    load_block,
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
/pending — показать ожидающие подтверждения
/pause — пауза
/resume — продолжить
""".strip()


def is_admin(user_id: int) -> bool:
    return user_id == cfg.admin_telegram_user_id


def status_text() -> str:
    with session_scope() as db:
        count = db.scalar(select(func.count(Question.id))) or 0
        pending = db.scalar(select(func.count(DailyBlock.id)).where(
            DailyBlock.status == "pending_approval"
        )) or 0
        last = db.scalar(select(DailyBlock).order_by(DailyBlock.id.desc()).limit(1))
    return (
        f"Статус: {'пауза' if get_state('paused') == 'true' else 'работает'}\n"
        f"Вопросов в базе: {count}\n"
        f"Ожидают подтверждения: {pending}\n"
        + (
            f"Последний блок: {last.target_date} {last.session} — {last.status}"
            if last else "Последних блоков нет."
        )
    )


def _manual_prepare(session: str):
    today = datetime.now(ZoneInfo(cfg.timezone)).date()
    try:
        result = send_for_approval(today, session)
        send_text(result, cfg.admin_telegram_user_id)
    except Exception as exc:
        log.exception("Manual preparation failed")
        send_text(f"Ошибка подготовки: {str(exc)[:500]}", cfg.admin_telegram_user_id)


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
        threading.Thread(target=_manual_prepare, args=(arg,), daemon=True).start()
        send_text("Подготовка запущена.", chat_id)
    elif cmd == "/pending":
        with session_scope() as db:
            blocks = list(db.scalars(select(DailyBlock).where(
                DailyBlock.status == "pending_approval"
            ).order_by(DailyBlock.target_date, DailyBlock.session)))
        if not blocks:
            send_text("Нет блоков, ожидающих подтверждения.", chat_id)
        else:
            send_text("\n".join(
                f"{b.id}: {b.target_date} {b.session} {b.level}" for b in blocks
            ), chat_id)
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
            result = regenerate_block_by_id(block_id)
        else:
            return
        if chat_id and message_id:
            edit_reply_markup(chat_id, message_id)
        send_text(result, cfg.admin_telegram_user_id)
    except Exception as exc:
        log.exception("Callback failed")
        answer_callback(callback_id, "Ошибка")
        send_text(f"Ошибка: {str(exc)[:500]}", cfg.admin_telegram_user_id)


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
                handle_message(text, chat["id"], user["id"])


def start_admin():
    threading.Thread(target=polling_loop, daemon=True, name="admin-polling").start()
