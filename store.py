"""SQLite 持久化（会话 / 消息 / 月报）。

数据目录与文件由环境变量 AGENT_DB_PATH 控制，默认项目根 data/agent.db。
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

DB_PATH = os.getenv("AGENT_DB_PATH", str(Path(__file__).resolve().parent / "data" / "agent.db"))


def get_conn() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS chat_sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT '1001',
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                sources TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS monthly_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                month TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, month)
            );
            """
        )


# ---------- 会话 ----------
def create_session(session_id: str, user_id: str, title: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO chat_sessions(session_id,user_id,title,created_at,updated_at) VALUES(?,?,?,?,?)",
            (session_id, user_id, title, now, now),
        )


def list_sessions(user_id: str, limit: int = 30) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM chat_sessions WHERE user_id=? ORDER BY updated_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_session(session_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM chat_sessions WHERE session_id=?", (session_id,)).fetchone()
    return dict(row) if row else None


def delete_session(session_id: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM chat_messages WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM chat_sessions WHERE session_id=?", (session_id,))


def add_message(session_id: str, role: str, content: str, sources: list | None = None) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO chat_messages(session_id,role,content,sources,created_at) VALUES(?,?,?,?,?)",
            (session_id, role, content, json.dumps(sources, ensure_ascii=False) if sources else None, now),
        )
        conn.execute("UPDATE chat_sessions SET updated_at=? WHERE session_id=?", (now, session_id))


def get_messages(session_id: str, limit: int = 100) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM chat_messages WHERE session_id=? ORDER BY id ASC LIMIT ?", (session_id, limit)
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["sources"] = json.loads(d["sources"]) if d.get("sources") else None
        result.append(d)
    return result


# ---------- 月报 ----------
def save_report(user_id: str, month: str, content: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO monthly_reports(user_id,month,content,created_at) VALUES(?,?,?,?)
               ON CONFLICT(user_id,month) DO UPDATE SET content=excluded.content, created_at=excluded.created_at""",
            (user_id, month, content, now),
        )


def list_reports(user_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM monthly_reports WHERE user_id=? ORDER BY month DESC", (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]
