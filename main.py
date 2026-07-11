import logging
import signal
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from admin import start_admin
from config import settings
from db import get_state, init_db, session_scope
from health import start_health_server
from models import DailyBlock
from service import send_for_approval
from telegram_api import send_text

cfg = settings()

logging.basicConfig(
    level=getattr(logging, cfg.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger(__name__)


def scheduled_prepare(session: str):
    if get_state("paused") == "true":
        return

    today = datetime.now(ZoneInfo(cfg.timezone)).date()
    if today.weekday() >= 6:
        return

    try:
        result = send_for_approval(today, session)
        log.info(result)
    except Exception as exc:
        log.exception("Scheduled preparation failed | session=%s", session)
        try:
            send_text(
                f"Ошибка автоматической подготовки {session}: "
                f"{str(exc)[:500]}",
                cfg.admin_telegram_user_id,
            )
        except Exception:
            log.exception("Failed to notify admin")


def _block_exists_today(session: str) -> bool:
    today = datetime.now(ZoneInfo(cfg.timezone)).date()
    with session_scope() as db:
        block_id = db.scalar(
            select(DailyBlock.id)
            .where(
                DailyBlock.target_date == today,
                DailyBlock.session == session,
                DailyBlock.status.in_(
                    [
                        "generating",
                        "pending_approval",
                        "approved",
                        "publishing",
                        "publishing_failed",
                        "published",
                    ]
                ),
            )
            .limit(1)
        )
    return block_id is not None


def startup_catchup():
    if get_state("paused") == "true":
        return

    now = datetime.now(ZoneInfo(cfg.timezone))
    if now.weekday() >= 6:
        return

    morning_time = now.replace(
        hour=cfg.morning_hour,
        minute=cfg.morning_minute,
        second=0,
        microsecond=0,
    )
    evening_time = now.replace(
        hour=cfg.evening_hour,
        minute=cfg.evening_minute,
        second=0,
        microsecond=0,
    )

    sessions = []
    if now >= morning_time and not _block_exists_today("morning"):
        sessions.append("morning")
    if now >= evening_time and not _block_exists_today("evening"):
        sessions.append("evening")

    for session in sessions:
        scheduled_prepare(session)


def main():
    init_db()
    start_health_server()
    start_admin()

    scheduler = BackgroundScheduler(
        timezone=ZoneInfo(cfg.timezone),
        job_defaults={"coalesce": True, "max_instances": 1},
    )
    scheduler.add_job(
        scheduled_prepare,
        CronTrigger(
            day_of_week="mon-sat",
            hour=cfg.morning_hour,
            minute=cfg.morning_minute,
            timezone=cfg.timezone,
        ),
        args=["morning"],
        id="morning_review",
        replace_existing=True,
        misfire_grace_time=7200,
    )
    scheduler.add_job(
        scheduled_prepare,
        CronTrigger(
            day_of_week="mon-sat",
            hour=cfg.evening_hour,
            minute=cfg.evening_minute,
            timezone=cfg.timezone,
        ),
        args=["evening"],
        id="evening_review",
        replace_existing=True,
        misfire_grace_time=7200,
    )
    scheduler.start()

    threading.Thread(
        target=startup_catchup,
        daemon=True,
        name="startup-catchup",
    ).start()

    log.info(
        "Started | Monday-Saturday | morning=%02d:%02d | "
        "evening=%02d:%02d | timezone=%s",
        cfg.morning_hour,
        cfg.morning_minute,
        cfg.evening_hour,
        cfg.evening_minute,
        cfg.timezone,
    )

    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    while not stopping:
        time.sleep(2)

    scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
