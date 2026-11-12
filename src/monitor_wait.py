"""Wait for the monitor to persist a terminal quality result for one body."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any


# Akkor jelzi, ha a publisher által elküldött munkadarabhoz a monitor nem készít végleges minősítést a megadott időn belül.
class MonitorCompletionTimeout(TimeoutError):
    """Raised when a body was published but the monitor did not finalize it in time."""


# Megvárom, amíg a monitor az adott body_id rekordját végleges állapotba írja; a PUBACK önmagában még nem minőségi eredmény.
def wait_for_body_completion(
    body_id: str,
    db_path: str | Path,
    timeout_seconds: float = 30.0,
    poll_interval_seconds: float = 0.025,
) -> dict[str, Any]:
    """Wait until SQLite shows a terminal status for body_id; use a single deadline."""
    if not body_id.strip():
        raise ValueError("A body_id nem lehet üres.")
    if timeout_seconds <= 0:
        raise ValueError("A timeout_seconds értékének pozitívnak kell lennie.")
    if poll_interval_seconds <= 0:
        raise ValueError("A poll_interval_seconds értékének pozitívnak kell lennie.")

    path = Path(db_path)
    deadline = time.monotonic() + timeout_seconds
    last_db_error: str | None = None
    while True:
        if path.exists():
            try:
                with sqlite3.connect(str(path), timeout=0.25) as conn:
                    row = conn.execute(
                        "SELECT status, completed_at, duration_seconds FROM bodies WHERE body_id=?",
                        (body_id,),
                    ).fetchone()
                last_db_error = None
            except sqlite3.Error as exc:
                last_db_error = str(exc)
                row = None
            if row is not None and row[0] != "FOLYAMATBAN":
                return {
                    "body_id": body_id,
                    "status": str(row[0]),
                    "completed_at": row[1],
                    "duration_seconds": row[2],
                    "confirmed_at_epoch": time.time(),
                }

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            detail = f"Karosszéria {body_id} nincs véglegesítve {timeout_seconds:.1f} másodperc alatt."
            if last_db_error:
                detail += f" Utolsó adatbázishiba: {last_db_error}"
            raise MonitorCompletionTimeout(detail)
        time.sleep(min(poll_interval_seconds, remaining))
