"""模型双通道切换 + 外部工具失败降级（不发起真实网络请求，仅校验构建结果与兜底路径）。"""
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import model.factory as factory  # noqa: E402
from agent.tools.agent_tools import fetch_external_data  # noqa: E402
from agent.tools.mcp_weather import render_weather  # noqa: E402


def test_ollama_is_default_provider():
    assert factory.MODEL_PROVIDER == "ollama"


def test_get_chat_model_ollama_builds_local_client():
    factory.reset_model_cache()
    with mock.patch.object(factory, "MODEL_PROVIDER", "ollama"):
        model = factory.get_chat_model()
        assert "localhost:11434" in str(model.openai_api_base)
        assert model.model_name == factory.OLLAMA_MODEL


def test_get_chat_model_deepseek_requires_key():
    factory.reset_model_cache()
    with mock.patch.object(factory, "MODEL_PROVIDER", "deepseek"), \
         mock.patch.object(factory, "DEEPSEEK_API_KEY", ""):
        try:
            factory.get_chat_model()
            raise AssertionError("无 Key 时应抛出 RuntimeError")
        except RuntimeError as e:
            assert "DEEPSEEK_API_KEY" in str(e) or "ollama" in str(e)


def test_get_chat_model_deepseek_with_key_builds_cloud_client():
    factory.reset_model_cache()
    with mock.patch.object(factory, "MODEL_PROVIDER", "deepseek"), \
         mock.patch.object(factory, "DEEPSEEK_API_KEY", "fake-key-123"):
        model = factory.get_chat_model()
        assert "api.deepseek.com" in str(model.openai_api_base)
        assert model.openai_api_key.get_secret_value() == "fake-key-123"
        factory.reset_model_cache()


def test_mcp_weather_error_envelope_renders_graceful():
    """MCP 受控错误信封映射为友好中文文案（不把技术错误抛给用户）。"""
    assert "暂不支持该城市" in render_weather(
        {"status": "error", "error": {"code": "CITY_NOT_ALLOWED", "message": "x"}})
    assert "暂未配置访问凭据" in render_weather(
        {"status": "error", "error": {"code": "MISSING_TOKEN", "message": "x"}})
    assert "超时" in render_weather(
        {"status": "error", "error": {"code": "UPSTREAM_TIMEOUT", "message": "x"}})


def test_mcp_weather_ok_envelope_renders():
    """MCP 成功信封渲染为可读天气字符串。"""
    out = render_weather({"status": "ok", "data": {
        "location": "杭州", "text": "晴", "temp_c": "17",
        "high": "19", "low": "12", "source": "itboy-weather", "cache_hit": False}})
    assert "杭州" in out and "晴" in out and "17" in out


def test_fetch_external_data_missing_returns_empty():
    """查无记录时返回空串，供上层判断（不抛异常）。"""
    out = fetch_external_data.invoke({"user_id": "__no_such_user__", "month": "2099-01"})
    assert out == ""
