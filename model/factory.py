"""模型工厂（改造版）：Ollama 本地为主 / DeepSeek 云端备选双模型，延迟初始化、可配置、可测试。

- 对话模型：默认 MODEL_PROVIDER=ollama（本地免费、隐私不出本机），可一键切到 deepseek（云端，需 Key）；
- 嵌入模型：统一使用本地 Ollama（免费、隐私不出本机）。
"""
from __future__ import annotations

import functools
import os
from abc import ABC, abstractmethod
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_ollama import OllamaEmbeddings
from langchain_openai import ChatOpenAI

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# 默认本地 Ollama 为主；云端 DeepSeek 为备选（需 DEEPSEEK_API_KEY）
MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "ollama").strip().lower()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-flash").strip()
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1").strip()
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:9b").strip()
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "qwen3-embedding:4b").strip()
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.1"))
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "90"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "3"))


@functools.lru_cache(maxsize=1)
def get_chat_model() -> BaseChatModel:
    if MODEL_PROVIDER == "ollama":
        return ChatOpenAI(
            model=OLLAMA_MODEL,
            base_url=OLLAMA_BASE_URL,
            api_key="ollama",
            temperature=LLM_TEMPERATURE,
            timeout=LLM_TIMEOUT_SECONDS,
            max_retries=LLM_MAX_RETRIES,
        )
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY，请在 .env 中填写或设置 MODEL_PROVIDER=ollama")
    return ChatOpenAI(
        model=DEEPSEEK_MODEL,
        base_url=DEEPSEEK_BASE_URL,
        api_key=DEEPSEEK_API_KEY,
        temperature=LLM_TEMPERATURE,
        timeout=LLM_TIMEOUT_SECONDS,
        max_retries=LLM_MAX_RETRIES,
    )


@functools.lru_cache(maxsize=1)
def get_embeddings() -> Embeddings:
    return OllamaEmbeddings(
        model=OLLAMA_EMBED_MODEL,
        base_url=OLLAMA_BASE_URL.replace("/v1", ""),
    )


def chat_model_label() -> str:
    return f"Ollama / {OLLAMA_MODEL}" if MODEL_PROVIDER == "ollama" else f"DeepSeek / {DEEPSEEK_MODEL}"


def reset_model_cache() -> None:
    """清空模型单例缓存（主要供测试在切换 provider 后重建模型用）。"""
    get_chat_model.cache_clear()
    get_embeddings.cache_clear()


class BaseModelFactory(ABC):
    @abstractmethod
    def generator(self):
        raise NotImplementedError


class ChatModelFactory(BaseModelFactory):
    def generator(self) -> BaseChatModel:
        return get_chat_model()


class EmbeddingsFactory(BaseModelFactory):
    def generator(self) -> Embeddings:
        return get_embeddings()
