"""工具注册表与治理裁决单测：schema 校验、权限分级、risk 审批、脱敏。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.registry import (  # noqa: E402
    NoArgs,
    Outcome,
    Permission,
    estimate_tokens,
    mask_args,
)
from agent.tool_registry import build_default_registry  # noqa: E402


def _reg():
    return build_default_registry()


def test_default_registry_lists_whitelist():
    names = set(_reg().names())
    assert {
        "rag_summarize", "get_weather", "get_user_location", "get_user_id",
        "get_current_month", "fetch_external_data", "fill_context_for_report",
        "create_work_order", "reset_device", "order_consumables",
    } == names


def test_unknown_tool_denied():
    d = _reg().authorize("hack_everything", {})
    assert d.outcome == Outcome.DENY


def test_schema_validity_allows():
    d = _reg().authorize("get_weather", {"location": "杭州"})
    assert d.outcome == Outcome.ALLOW
    assert d.normalized == {"location": "杭州"}


def test_schema_invalid_denied():
    # location 为空（min_length=1）
    d = _reg().authorize("get_weather", {"location": ""})
    assert d.outcome == Outcome.DENY
    # month 格式非法
    d2 = _reg().authorize("fetch_external_data", {"user_id": "1", "month": "2025/01"})
    assert d2.outcome == Outcome.DENY
    # 缺必填
    d3 = _reg().authorize("fetch_external_data", {"user_id": "1"})
    assert d3.outcome == Outcome.DENY


def test_read_tools_need_no_approval():
    for name, args in (
        ("rag_summarize", {"query": "x"}),
        ("get_weather", {"location": "杭州"}),
        ("fetch_external_data", {"user_id": "1", "month": "2025-01"}),
    ):
        d = _reg().authorize(name, args)
        assert d.outcome == Outcome.ALLOW, name


def test_risk_tool_requires_approval():
    reg = _reg()
    # 未批准 -> NEED_APPROVAL
    d = reg.authorize("create_work_order", {"issue": "异响"}, call_id="c1")
    assert d.outcome == Outcome.NEED_APPROVAL
    # 批准后 -> ALLOW
    d2 = reg.authorize("create_work_order", {"issue": "异响"},
                       approved_call_ids={"c1"}, call_id="c1")
    assert d2.outcome == Outcome.ALLOW
    # 别的 call_id 不算批准
    d3 = reg.authorize("create_work_order", {"issue": "异响"},
                       approved_call_ids={"other"}, call_id="c1")
    assert d3.outcome == Outcome.NEED_APPROVAL


def test_risk_permission_flagged():
    reg = _reg()
    assert reg.get("reset_device").permission == Permission.RISK
    assert reg.get("reset_device").require_approval is True
    assert reg.get("get_weather").permission == Permission.READ


def test_mask_args():
    masked = mask_args({"user_id": "1001", "contact": "13800000000",
                        "city": "杭州", "location": "上海", "issue": "异响"})
    assert masked["user_id"].startswith("1") and "***" in masked["user_id"]
    assert masked["city"].endswith("*")
    assert masked["location"].endswith("*")
    assert masked["issue"] == "异响"  # 非敏感字段原样


def test_estimate_tokens():
    assert estimate_tokens("") == 0
    assert estimate_tokens("扫地机器人迷路了怎么办") > 0
