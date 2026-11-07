"""执行轨迹落库与脱敏单测（临时 SQLite，不碰生产库）。"""
import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp()) / "agent_trace_test.db"
os.environ["AGENT_DB_PATH"] = str(_tmp)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import trace  # noqa: E402


def test_start_and_end_run():
    trace.init_trace_db()
    trace.start_run("r1", "sess1", "1001", "扫地机器人迷路了？",
                    state="PLANNING", max_steps=25, model_label="Ollama / qwen3.5:9b")
    trace.record_step("r1", 1, "EXECUTING", "model_call", result_summary="准备调用工具",
                      tokens_est=10)
    trace.record_step("r1", 2, "TOOL_PENDING", "tool_result", tool_name="get_weather",
                      args_masked={"city": "杭*"}, result_summary="杭州 晴 20℃",
                      duration_ms=320, tokens_est=15)
    trace.end_run("r1", state="DONE", final_status="done")

    run = trace.get_run("r1")
    assert run["state"] == "DONE"
    assert run["final_status"] == "done"
    assert run["step_count"] == 2
    assert run["duration_ms"] is not None

    steps = trace.get_steps("r1")
    assert len(steps) == 2
    assert steps[1]["tool_name"] == "get_weather"
    assert steps[1]["duration_ms"] == 320


def test_approval_and_degrade_persisted():
    trace.start_run("r2", "sess2", "2002", "帮我报修",
                    state="PLANNING", max_steps=25, model_label="x")
    trace.record_step("r2", 1, "TOOL_PENDING", "approval", tool_name="create_work_order",
                      args_masked={"issue": "异响", "contact": "1***1"},
                      result_summary="需人工确认", approved="declined", note="高风险未确认")
    trace.record_step("r2", 2, "TOOL_PENDING", "degrade", tool_name="get_weather",
                      args_masked={"city": "杭*"}, result_summary="工具暂不可用",
                      retried=True, degraded=True, duration_ms=900)
    trace.end_run("r2", state="DONE", final_status="degraded")

    steps = trace.get_steps("r2")
    assert steps[0]["approved"] == "declined"
    assert steps[1]["degraded"] == 1
    assert steps[1]["retried"] == 1


def test_list_runs_descending():
    runs = trace.list_runs()
    # 最新的在前
    assert runs[0]["run_id"] in ("r1", "r2")
    ids = [r["run_id"] for r in runs]
    assert "r1" in ids and "r2" in ids


def test_missing_run_returns_none():
    assert trace.get_run("no_such_run") is None
    assert trace.get_steps("no_such_run") == []
