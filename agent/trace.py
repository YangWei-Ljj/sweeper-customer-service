"""执行轨迹持久化（第二轮·可观测核心）。

两张表（与 store.py 同一个 SQLite 文件，WAL）：
- agent_runs：一次对话 run 一行（状态、耗时、步数、模型、最终结论、错误摘要）
- agent_steps：run 内每一步一行（状态、事件、工具名、脱敏入参、结果摘要、耗时、
  是否重试/降级、审批结论、token 估算）

设计：
- 全部入参在写入前经 mask_args 脱敏；结果摘要截断 500 字符；
- 任何写轨迹的异常都不应影响主对话流程（吞掉并打日志）；
- 纯 SQLite，不依赖模型/网络，便于单测（测试用临时库）。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from store import DB_PATH, get_conn
from utils.logger_handler import logger

_RESULT_MAX = 500


def init_trace_db() -> None:
    """建表（幂等）。在应用启动与测试 setup 时调用。"""
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS agent_runs (
                run_id TEXT PRIMARY KEY,
                session_id TEXT,
                user_id TEXT,
                query TEXT,
                state TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                duration_ms INTEGER,
                step_count INTEGER NOT NULL DEFAULT 0,
                max_steps INTEGER,
                model_label TEXT,
                tokens_est INTEGER NOT NULL DEFAULT 0,
                final_status TEXT,
                error TEXT
            );
            CREATE TABLE IF NOT EXISTS agent_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                step_no INTEGER NOT NULL,
                state TEXT NOT NULL,
                event TEXT NOT NULL,
                tool_name TEXT,
                args_masked TEXT,
                result_summary TEXT,
                duration_ms INTEGER,
                retried INTEGER NOT NULL DEFAULT 0,
                degraded INTEGER NOT NULL DEFAULT 0,
                approved TEXT NOT NULL DEFAULT 'na',
                tokens_est INTEGER NOT NULL DEFAULT 0,
                note TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_steps_run ON agent_steps(run_id, step_no);
            CREATE INDEX IF NOT EXISTS idx_runs_started ON agent_runs(started_at DESC);
            """
        )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def start_run(
    run_id: str,
    session_id: str,
    user_id: str,
    query: str,
    state: str,
    max_steps: int,
    model_label: str,
) -> None:
    try:
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO agent_runs
                   (run_id, session_id, user_id, query, state, started_at, max_steps, model_label)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (run_id, session_id, user_id, query, state, _now(), max_steps, model_label),
            )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[trace] start_run 写轨迹失败（不影响主流程）：{e}")


def record_step(
    run_id: str,
    step_no: int,
    state: str,
    event: str,
    tool_name: str | None = None,
    args_masked: dict[str, Any] | None = None,
    result_summary: str | None = None,
    duration_ms: int | None = None,
    retried: bool = False,
    degraded: bool = False,
    approved: str = "na",
    tokens_est: int = 0,
    note: str | None = None,
) -> None:
    try:
        if result_summary and len(result_summary) > _RESULT_MAX:
            result_summary = result_summary[:_RESULT_MAX] + "…[截断]"
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO agent_steps
                   (run_id, step_no, state, event, tool_name, args_masked, result_summary,
                    duration_ms, retried, degraded, approved, tokens_est, note, created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id, step_no, state, event, tool_name,
                    json.dumps(args_masked, ensure_ascii=False) if args_masked else None,
                    result_summary, int(duration_ms) if duration_ms is not None else None,
                    1 if retried else 0, 1 if degraded else 0, approved,
                    int(tokens_est), note, _now(),
                ),
            )
            conn.execute(
                "UPDATE agent_runs SET step_count=?, tokens_est=tokens_est+? WHERE run_id=?",
                (step_no, int(tokens_est), run_id),
            )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[trace] record_step 写轨迹失败（不影响主流程）：{e}")


def end_run(
    run_id: str,
    state: str,
    final_status: str,
    error: str | None = None,
) -> None:
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT started_at FROM agent_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            duration_ms = None
            if row:
                try:
                    start = datetime.fromisoformat(row["started_at"])
                    duration_ms = int((datetime.now() - start).total_seconds() * 1000)
                except Exception:  # noqa: BLE001
                    duration_ms = None
            conn.execute(
                """UPDATE agent_runs
                   SET state=?, ended_at=?, duration_ms=?, final_status=?, error=?
                   WHERE run_id=?""",
                (state, _now(), duration_ms, final_status,
                 (error or "")[:_RESULT_MAX] or None, run_id),
            )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[trace] end_run 写轨迹失败（不影响主流程）：{e}")


def list_runs(limit: int = 50) -> list[dict]:
    try:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_runs ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


def get_run(run_id: str) -> dict | None:
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM agent_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        return dict(row) if row else None
    except sqlite3.OperationalError:
        return None


def get_steps(run_id: str) -> list[dict]:
    try:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_steps WHERE run_id=? ORDER BY step_no ASC, id ASC",
                (run_id,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            if d.get("args_masked"):
                try:
                    d["args_masked"] = json.loads(d["args_masked"])
                except Exception:  # noqa: BLE001
                    pass
            out.append(d)
        return out
    except sqlite3.OperationalError:
        return []
