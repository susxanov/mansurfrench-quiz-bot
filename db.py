import logging
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from config import settings
from models import Base, BotState

log = logging.getLogger(__name__)
cfg = settings()
engine = create_engine(cfg.database_url, pool_pre_ping=True, pool_recycle=300)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


_POSTGRES_SAFE_MIGRATIONS = (
    # create_all() never widens existing VARCHAR columns. Previous releases used
    # VARCHAR(80/100/160), while GPT-generated labels can legitimately be longer.
    # Converting them to TEXT is non-destructive and preserves indexes/constraints.
    "ALTER TABLE IF EXISTS questions ALTER COLUMN topic TYPE TEXT",
    "ALTER TABLE IF EXISTS questions ALTER COLUMN skill TYPE TEXT",
    "ALTER TABLE IF EXISTS daily_blocks ALTER COLUMN session TYPE TEXT",
    "ALTER TABLE IF EXISTS daily_blocks ALTER COLUMN level TYPE TEXT",
    "ALTER TABLE IF EXISTS daily_blocks ALTER COLUMN topic TYPE TEXT",
    "ALTER TABLE IF EXISTS daily_blocks ALTER COLUMN status TYPE TEXT",
)


def _run_safe_migrations() -> None:
    if engine.dialect.name != "postgresql":
        return

    with engine.begin() as connection:
        for statement in _POSTGRES_SAFE_MIGRATIONS:
            connection.execute(text(statement))
    log.info("Database schema migrations applied successfully")


def init_db() -> None:
    Base.metadata.create_all(engine)
    _run_safe_migrations()

    with SessionLocal.begin() as db:
        defaults = {
            "paused": "false",
            "telegram_offset": "0",
            "content_version": cfg.content_version,
        }
        for key, value in defaults.items():
            if db.get(BotState, key) is None:
                db.add(BotState(key=key, value=value))


@contextmanager
def session_scope():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_state(key: str, default: str = "") -> str:
    with session_scope() as db:
        row = db.get(BotState, key)
        return row.value if row else default


def set_state(key: str, value: str) -> None:
    with session_scope() as db:
        row = db.get(BotState, key)
        if row:
            row.value = value
        else:
            db.add(BotState(key=key, value=value))
