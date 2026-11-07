"""工具层离线测试（不依赖网络/模型）。"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.tools.agent_tools import (  # noqa: E402
    CURRENT_LOCATION,
    CURRENT_USER_ID,
    fetch_external_data,
    get_current_month,
    list_available_user_months,
)
from utils.file_handler import listdir_with_allowed_type  # noqa: E402


def test_current_month_is_real():
    assert get_current_month.invoke({}) == datetime.now().strftime("%Y-%m")


def test_user_context_vars():
    uid = CURRENT_USER_ID.set("9999")
    loc = CURRENT_LOCATION.set("北京")
    try:
        assert get_current_month.invoke({})  # 触发工具加载
        from agent.tools.agent_tools import get_user_id, get_user_location
        assert get_user_id.invoke({}) == "9999"
        assert get_user_location.invoke({}) == "北京"
    finally:
        CURRENT_USER_ID.reset(uid)
        CURRENT_LOCATION.reset(loc)


def test_external_data_csv_parse():
    # 原版用 split(",") 会破坏含逗号/竖线的字段；csv 模块应正确解析出 6 列
    users = list_available_user_months()
    assert users, "外部记录应解析出用户"
    uid = sorted(users)[0]
    month = users[uid][0]
    record = fetch_external_data.invoke({"user_id": uid, "month": month})
    assert "使用记录" in record
    assert "效率" in record


def test_listdir_non_dir_returns_empty():
    # 原版 bug：非目录返回扩展名元组
    result = listdir_with_allowed_type("not_a_dir_xyz", (".txt",))
    assert result == tuple()
