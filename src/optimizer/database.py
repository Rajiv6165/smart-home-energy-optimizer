from contextlib import contextmanager
from typing import Generator
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings

_settings = get_settings()
_engine = create_engine(_settings.database_url, echo=False)


def init_db() -> None:
    # 1. Create any new tables (User, etc.)
    SQLModel.metadata.create_all(_engine)

    with _engine.connect() as conn:
        # 2. Sensor table — ensure is_deleted column exists
        cursor = conn.execute(text("PRAGMA table_info(sensor)"))
        sensor_cols = [row[1] for row in cursor.fetchall()]
        if sensor_cols and "is_deleted" not in sensor_cols:
            conn.execute(text("ALTER TABLE sensor ADD COLUMN is_deleted BOOLEAN DEFAULT 0"))
            conn.commit()

        # 3. ScheduleRun table — ensure carbon_kg and carbon_saved_kg columns exist
        cursor = conn.execute(text("PRAGMA table_info(schedulerun)"))
        run_cols = [row[1] for row in cursor.fetchall()]
        if run_cols and "carbon_kg" not in run_cols:
            conn.execute(text("ALTER TABLE schedulerun ADD COLUMN carbon_kg REAL"))
            conn.commit()
        if run_cols and "carbon_saved_kg" not in run_cols:
            conn.execute(text("ALTER TABLE schedulerun ADD COLUMN carbon_saved_kg REAL"))
            conn.commit()


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
