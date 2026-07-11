import logging
import time
import requests
from tenacity import retry, stop_after_attempt, wait_exponential
from config import settings

log = logging.getLogger(__name__)
cfg = settings()
BASE = f"https://api.telegram.org/bot{cfg.telegram_bot_token}"


class TelegramError(RuntimeError):
    pass


@retry(stop=stop_after_attempt(4), wait=wait_exponential(min=1, max=10), reraise=True)
def call(method: str, payload: dict):
    response = requests.post(f"{BASE}/{method}", json=payload, timeout=45)
    body = response.json() if response.content else {}
    if response.status_code == 429 or response.status_code >= 500:
        raise TelegramError(f"Transient Telegram error: {response.status_code} {body}")
    if response.status_code >= 400 or not body.get("ok"):
        raise TelegramError(f"Telegram rejected {method}: {response.status_code} {body}")
    return body["result"]


def send_text(text: str, chat_id=None, reply_markup=None):
    payload = {
        "chat_id": chat_id or cfg.telegram_channel,
        "text": text,
        "link_preview_options": {"is_disabled": True},
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return call("sendMessage", payload)


def edit_reply_markup(chat_id: int, message_id: int, reply_markup=None):
    return call("editMessageReplyMarkup", {
        "chat_id": chat_id,
        "message_id": message_id,
        "reply_markup": reply_markup or {"inline_keyboard": []},
    })


def answer_callback(callback_query_id: str, text: str):
    return call("answerCallbackQuery", {
        "callback_query_id": callback_query_id,
        "text": text,
        "show_alert": False,
    })


def send_quiz(question, chat_id=None):
    return call("sendPoll", {
        "chat_id": chat_id or cfg.telegram_channel,
        "question": question.prompt,
        "options": [{"text": option} for option in question.options],
        "type": "quiz",
        "correct_option_ids": [question.correct_option_ids[0]],
        "allows_multiple_answers": False,
        "explanation": question.explanation,
        "is_anonymous": True,
        "shuffle_options": False,
    })


def get_updates(offset: int):
    try:
        return call("getUpdates", {
            "offset": offset,
            "timeout": 25,
            "allowed_updates": ["message", "callback_query"],
        })
    except Exception:
        log.exception("getUpdates failed")
        time.sleep(5)
        return []
