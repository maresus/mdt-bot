"""Admin audit trail utilities."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


def _get_db_path() -> Path:
    project_root = Path(__file__).resolve().parents[2]
    data_dir = project_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "admin_audit.db"


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            actor TEXT,
            role TEXT,
            action TEXT NOT NULL,
            reservation_id INTEGER,
            ip TEXT,
            details TEXT
        )
        """
    )
    conn.commit()


def log_admin_action(
    action: str,
    reservation_id: int | None = None,
    actor: str | None = None,
    role: str | None = None,
    ip: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    try:
        db_path = _get_db_path()
        conn = sqlite3.connect(db_path)
        _ensure_table(conn)

        payload = json.dumps(details or {}) if details else None
        conn.execute(
            """
            INSERT INTO admin_audit (ts, actor, role, action, reservation_id, ip, details)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.utcnow().isoformat(timespec="seconds"),
                actor,
                role,
                action,
                reservation_id,
                ip,
                payload,
            ),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[ADMIN AUDIT] Failed to log action: {exc}")


def list_admin_audit(limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
    db_path = _get_db_path()
    if not db_path.exists():
        return []

    conn = sqlite3.connect(db_path)
    _ensure_table(conn)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        """
        SELECT id, ts, actor, role, action, reservation_id, ip, details
        FROM admin_audit
        ORDER BY id DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    )
    rows = cur.fetchall()
    conn.close()

    results: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if item.get("details"):
            try:
                item["details"] = json.loads(item["details"])
            except Exception:
                pass
        results.append(item)
    return results
