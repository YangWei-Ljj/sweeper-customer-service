"""Agent 控制权与健壮性单测（纯函数，不依赖真实模型/网络）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.tools.middleware import MAX_IDENTICAL_TOOL_CALLS, loop_decision  # noqa: E402
from utils.text_clean import looks_like_tool_call_json, sanitize_final_answer  # noqa: E402


# ---------- 最终回答净化 ----------
def test_sanitize_strips_think_block():
    raw = "<think>我需要先查一下天气，调用 get_weather</think>\n杭州今天晴，适合扫地机器人工作。"
    out = sanitize_final_answer(raw)
    assert "<think>" not in out and "</think>" not in out
    assert "杭州今天晴" in out


def test_sanitize_strips_thinking_lines():
    raw = "思考：用户在问故障，我先调用 rag\n\n迷路常见原因是轮缠，建议清理滚刷。"
    out = sanitize_final_answer(raw)
    assert "思考：" not in out
    assert "迷路常见原因" in out


def test_sanitize_strips_tool_call_json():
    raw = '正常回答内容{"tool_calls":[{"name":"get_weather","args":{"city":"杭州"}}]}后续结论'
    out = sanitize_final_answer(raw)
    assert "tool_calls" not in out
    assert "正常回答内容" in out and "后续结论" in out


def test_sanitize_empty():
    assert sanitize_final_answer("") == ""
    assert sanitize_final_answer(None) == ""


def test_looks_like_tool_call_json():
    assert looks_like_tool_call_json('{"tool_calls": []}') is True
    assert looks_like_tool_call_json("扫地机器人很好用") is False


# ---------- 循环保护（纯函数 loop_decision） ----------
def test_loop_decision_stops_after_repeat():
    """同一工具相同参数累计调用达到上限后返回应停止=True。"""
    ctx = {}
    # 前 MAX-1 次不应停止
    for _ in range(MAX_IDENTICAL_TOOL_CALLS - 1):
        should_stop, repeat = loop_decision(ctx, "get_weather", {"city": "杭州"})
        assert should_stop is False
    # 第 MAX 次：命中循环保护
    should_stop, repeat = loop_decision(ctx, "get_weather", {"city": "杭州"})
    assert should_stop is True
    assert repeat == MAX_IDENTICAL_TOOL_CALLS


def test_loop_decision_allows_different_args():
    """不同参数的工具调用不应被误判为循环。"""
    ctx = {}
    for city in ("杭州", "北京", "上海"):
        should_stop, _ = loop_decision(ctx, "get_weather", {"city": city})
        assert should_stop is False


def test_loop_decision_is_isolated_per_context():
    """不同请求上下文互不影响（每次任务独立计数）。"""
    c1, c2 = {}, {}
    loop_decision(c1, "t", {"a": 1})
    loop_decision(c1, "t", {"a": 1})
    should_stop1, _ = loop_decision(c1, "t", {"a": 1})
    should_stop2, _ = loop_decision(c2, "t", {"a": 1})
    assert should_stop1 is True
    assert should_stop2 is False
