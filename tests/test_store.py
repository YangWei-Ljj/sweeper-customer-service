"""SQLite 会话/消息/月报测试。"""
import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp()) / "agent_test.db"
os.environ["AGENT_DB_PATH"] = str(_tmp)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import store  # noqa: E402


def test_session_lifecycle():
    store.init_db()
    store.create_session("s1", "1001", "t1")
    store.add_message("s1", "user", "你好")
    store.add_message("s1", "assistant", "您好")
    sessions = store.list_sessions("1001")
    assert any(s["session_id"] == "s1" for s in sessions)
    msgs = store.get_messages("s1")
    assert len(msgs) == 2 and msgs[0]["role"] == "user"


def test_report_upsert():
    store.save_report("1001", "2025-01", "报告A")
    store.save_report("1001", "2025-01", "报告B")
    reports = store.list_reports("1001")
    jan = [r for r in reports if r["month"] == "2025-01"]
    assert len(jan) == 1 and jan[0]["content"] == "报告B"


def test_user_isolation():
    store.create_session("s2", "2002", "other")
    assert all(s["session_id"] != "s2" for s in store.list_sessions("1001"))
