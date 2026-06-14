from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    language_code TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS faq_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    intent TEXT NOT NULL,
                    question TEXT NOT NULL,
                    keywords TEXT NOT NULL DEFAULT '[]',
                    answer TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    first_message_id INTEGER,
                    status TEXT NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open', 'closed')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    closed_at TEXT,
                    closed_by_id INTEGER,
                    close_reason TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    ticket_id INTEGER,
                    direction TEXT NOT NULL
                        CHECK (direction IN ('user', 'bot', 'coordinator')),
                    text TEXT NOT NULL,
                    tg_chat_id INTEGER,
                    tg_message_id INTEGER,
                    coordinator_id INTEGER,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(user_id),
                    FOREIGN KEY (ticket_id) REFERENCES tickets(id)
                );

                CREATE TABLE IF NOT EXISTS coordinator_states (
                    coordinator_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    ticket_id INTEGER NOT NULL,
                    mode TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (coordinator_id, chat_id),
                    FOREIGN KEY (ticket_id) REFERENCES tickets(id)
                );

                CREATE INDEX IF NOT EXISTS idx_messages_user_created
                    ON messages(user_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_tickets_status
                    ON tickets(status, updated_at);
                """
            )

    def upsert_user(
        self,
        user_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        language_code: str | None,
    ) -> None:
        now = utcnow()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO users (
                    user_id, username, first_name, last_name,
                    language_code, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    language_code = excluded.language_code,
                    updated_at = excluded.updated_at
                """,
                (user_id, username, first_name, last_name, language_code, now, now),
            )

    def get_user(self, user_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return row_to_dict(row)

    def log_message(
        self,
        *,
        user_id: int,
        direction: str,
        text: str,
        tg_chat_id: int | None = None,
        tg_message_id: int | None = None,
        coordinator_id: int | None = None,
        ticket_id: int | None = None,
    ) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO messages (
                    user_id, ticket_id, direction, text,
                    tg_chat_id, tg_message_id, coordinator_id, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    ticket_id,
                    direction,
                    text,
                    tg_chat_id,
                    tg_message_id,
                    coordinator_id,
                    utcnow(),
                ),
            )
            return int(cursor.lastrowid)

    def attach_message_to_ticket(self, message_id: int, ticket_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE messages SET ticket_id = ? WHERE id = ?",
                (ticket_id, message_id),
            )

    def create_ticket(self, user_id: int, first_message_id: int) -> int:
        now = utcnow()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO tickets (
                    user_id, first_message_id, status,
                    created_at, updated_at
                )
                VALUES (?, ?, 'open', ?, ?)
                """,
                (user_id, first_message_id, now, now),
            )
            return int(cursor.lastrowid)

    def get_ticket(self, ticket_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    t.*,
                    u.username,
                    u.first_name,
                    u.last_name,
                    u.language_code
                FROM tickets t
                JOIN users u ON u.user_id = t.user_id
                WHERE t.id = ?
                """,
                (ticket_id,),
            ).fetchone()
            return row_to_dict(row)

    def list_open_tickets(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    t.*,
                    u.username,
                    u.first_name,
                    u.last_name,
                    (
                        SELECT text
                        FROM messages m
                        WHERE m.ticket_id = t.id AND m.direction = 'user'
                        ORDER BY m.id ASC
                        LIMIT 1
                    ) AS first_text
                FROM tickets t
                JOIN users u ON u.user_id = t.user_id
                WHERE t.status = 'open'
                ORDER BY t.updated_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def close_ticket(
        self,
        ticket_id: int,
        *,
        closed_by_id: int | None,
        reason: str | None = None,
    ) -> None:
        now = utcnow()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE tickets
                SET status = 'closed',
                    updated_at = ?,
                    closed_at = ?,
                    closed_by_id = ?,
                    close_reason = ?
                WHERE id = ?
                """,
                (now, now, closed_by_id, reason, ticket_id),
            )

    def reopen_ticket(self, ticket_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE tickets
                SET status = 'open',
                    updated_at = ?,
                    closed_at = NULL,
                    closed_by_id = NULL,
                    close_reason = NULL
                WHERE id = ?
                """,
                (utcnow(), ticket_id),
            )

    def get_transcript(
        self,
        user_id: int,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT *
            FROM messages
            WHERE user_id = ?
            ORDER BY id ASC
        """
        params: tuple[Any, ...] = (user_id,)
        if limit is not None:
            sql = """
                SELECT *
                FROM (
                    SELECT *
                    FROM messages
                    WHERE user_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                )
                ORDER BY id ASC
            """
            params = (user_id, limit)

        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(row) for row in rows]

    def faq_count(self) -> int:
        with self.connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM faq_items").fetchone()[0])

    def seed_faq(self, items: list[dict[str, Any]], *, replace: bool = False) -> int:
        now = utcnow()
        with self.connect() as conn:
            if replace:
                conn.execute("DELETE FROM faq_items")

            conn.executemany(
                """
                INSERT INTO faq_items (
                    intent, question, keywords, answer,
                    enabled, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 1, ?, ?)
                """,
                [
                    (
                        item.get("intent") or f"faq_{index:03d}",
                        item["question"],
                        json.dumps(item.get("keywords", []), ensure_ascii=False),
                        item["answer"],
                        now,
                        now,
                    )
                    for index, item in enumerate(items, start=1)
                ],
            )
            return len(items)

    def get_faq_items(self, *, enabled_only: bool = True) -> list[dict[str, Any]]:
        where = "WHERE enabled = 1" if enabled_only else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM faq_items {where} ORDER BY id ASC"
            ).fetchall()

        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["keywords"] = json.loads(item.get("keywords") or "[]")
            items.append(item)
        return items

    def set_coordinator_state(
        self,
        *,
        coordinator_id: int,
        chat_id: int,
        ticket_id: int,
        mode: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO coordinator_states (
                    coordinator_id, chat_id, ticket_id, mode, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(coordinator_id, chat_id) DO UPDATE SET
                    ticket_id = excluded.ticket_id,
                    mode = excluded.mode,
                    created_at = excluded.created_at
                """,
                (coordinator_id, chat_id, ticket_id, mode, utcnow()),
            )

    def get_coordinator_state(
        self,
        *,
        coordinator_id: int,
        chat_id: int,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM coordinator_states
                WHERE coordinator_id = ? AND chat_id = ?
                """,
                (coordinator_id, chat_id),
            ).fetchone()
            return row_to_dict(row)

    def clear_coordinator_state(self, *, coordinator_id: int, chat_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                DELETE FROM coordinator_states
                WHERE coordinator_id = ? AND chat_id = ?
                """,
                (coordinator_id, chat_id),
            )

