"""治理纯函数 run_governed 单测：拒绝 / 风险审批 / 放行 / 重试 / 降级（不连模型/网络）。"""
import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp()) / "agent_gov_test.db"
os.environ["AGENT_DB_PATH"] = str(_tmp)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.messages import ToolMessage  # noqa: E402

from agent import trace  # noqa: E402
from agent.tools.governance import run_governed  # noqa: E402

trace.init_trace_db()


def _ctx(call_id="c1", approvals=None, run_id="rt"):
    return {"run_id": run_id, "sm": None, "approvals": set(approvals or set())}


def _ok_executor(name):
    def _run():
        return ToolMessage(content=f"result-of-{name}", tool_call_id="c1", name=name)
    return _run


def _tool_call(name, args, call_id="c1"):
    return {"name": name, "args": args, "id": call_id}


def test_unknown_tool_denied():
    msg = run_governed(_tool_call("no_tool", {}), _ctx(), _ok_executor("no_tool"))
    assert "治理拦截" in msg.content


def test_invalid_args_denied():
    msg = run_governed(_tool_call("get_weather", {"location": ""}), _ctx(),
                       _ok_executor("get_weather"))
    assert "治理拦截" in msg.content


def test_risk_without_approval_declined():
    msg = run_governed(
        _tool_call("create_work_order", {"issue": "异响"}, call_id="w1"),
        _ctx(call_id="w1"),
        _ok_executor("create_work_order"),
    )
    assert "需人工确认" in msg.content


def test_risk_with_approval_executes():
    msg = run_governed(
        _tool_call("create_work_order", {"issue": "异响"}, call_id="w2"),
        _ctx(call_id="w2", approvals={"w2"}),
        _ok_executor("create_work_order"),
    )
    assert "result-of-create_work_order" == msg.content


def test_read_tool_success():
    msg = run_governed(_tool_call("get_weather", {"location": "杭州"}), _ctx(),
                       _ok_executor("get_weather"))
    assert "result-of-get_weather" == msg.content


def test_retry_then_success():
    state = {"n": 0}

    def flaky():
        state["n"] += 1
        if state["n"] < 2:
            raise RuntimeError("network blip")
        return _ok_executor("get_weather")()

    msg = run_governed(_tool_call("get_weather", {"location": "杭州"}), _ctx(), flaky)
    assert "result-of-get_weather" == msg.content
    assert state["n"] == 2


def test_degrade_after_retries_exhausted():
    def always_fail():
        raise RuntimeError("down")

    msg = run_governed(_tool_call("get_weather", {"location": "杭州"}), _ctx(), always_fail)
    assert "工具暂不可用" in msg.content

