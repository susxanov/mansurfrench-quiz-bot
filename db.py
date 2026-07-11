from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config import settings
from models import Base, BotState

cfg = settings()
engine = create_engine(cfg.database_url, pool_pre_ping=True, pool_recycle=300)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal.begin() as db:
        defaults = {
            "paused": "false",
            "telegram_offset": "0",
            "content_version": "3.0",
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
