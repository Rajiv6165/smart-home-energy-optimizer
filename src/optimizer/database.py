from contextlib import contextmanager
from typing import Generator

from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings

_settings = get_settings()
_engine = create_engine(_settings.database_url, echo=False)


def init_db() -> None:
    SQLModel.metadata.create_all(_engine)


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    session = Session(_engine, expire_on_commit=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
