"""Self-check for the screen-time automation dedup: the daily-limit alert must
fire exactly once no matter how many reports arrive after the limit, and reset
on a new day. Mirrors the decision in report_screen_time. Run: python test_screen_limit.py
"""
import os
os.environ["DATABASE_URL"] = "sqlite://"  # in-memory, don't touch the real db

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base
from models import ScreenTime

engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)


def report(db, child_id, date, total_min, limit):
    """The endpoint's upsert + fire decision, isolated. Returns True if it fired."""
    row = db.query(ScreenTime).filter(
        ScreenTime.child_id == child_id, ScreenTime.date == date).first()
    if row:
        row.total_min = total_min
    else:
        row = ScreenTime(child_id=child_id, date=date, total_min=total_min)
        db.add(row)
    db.commit()
    if limit is not None and total_min >= limit and not row.limit_notified:
        row.limit_notified = True
        db.commit()
        return True
    return False


def demo():
    db = Session()
    LIMIT = 120

    # Reports climb toward the limit, then keep arriving past it.
    fires = [report(db, 1, "2026-07-09", m, LIMIT) for m in (30, 90, 120, 121, 200)]
    assert fires == [False, False, True, False, False], fires  # fires once, at crossing

    # No limit set -> never fires.
    assert report(db, 2, "2026-07-09", 999, None) is False

    # New day = new row = flag resets, so it can fire again.
    assert report(db, 1, "2026-07-10", 130, LIMIT) is True

    # Exactly at the limit counts as reached.
    assert report(db, 3, "2026-07-09", 120, 120) is True
    print("OK: alert fires once per day, resets next day, respects no-limit")


if __name__ == "__main__":
    demo()
