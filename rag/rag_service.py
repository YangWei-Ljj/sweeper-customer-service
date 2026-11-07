"""总结服务类（改造版）：检索资料 -> 提交模型总结。

改造点：
- 模型/向量库延迟初始化（导入期不再创建模型、不连接数据库）；
- 参考资料随用户消息传入（部分模型对 system 中长资料利用不充分）；
- 检索结果可带元数据返回，便于页面展示引用来源。
"""
from __future__ import annotations

import functools

from langchain_core.documents import Document
from langchain_core.messages import SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from model.factory import get_chat_model
from rag.vector_store import VectorStoreService
from utils.prompt_loader import load_rag_prompts


class RagSummarizeService:
    def __init__(self):
        self.prompt_text = load_rag_prompts()
        self.chain = self._init_chain()

    @functools.cached_property
    def vector_store(self) -> VectorStoreService:
        return VectorStoreService()

    def _init_chain(self):
        # 原提示词含 {input} 与 {context}；作为用户消息模板
        prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessage("你是智能客服的资料检索助手，严格基于参考资料回答，不要编造。"),
                ("human", self.prompt_text),
            ]
        )
        return prompt | get_chat_model() | StrOutputParser()

    def retrieve_docs(self, query: str) -> list[Document]:
        return self.vector_store.similarity_search(query)

    def build_context(self, docs: list[Document]) -> str:
        if not docs:
            return "无相关参考资料"
        context = ""
        for i, doc in enumerate(docs, 1):
            context += f"【参考资料{i}】{doc.page_content}\n"
        return context

    def rag_summarize(self, query: str) -> str:
        docs = self.retrieve_docs(query)
        return self.chain.invoke({"input": query, "context": self.build_context(docs)})

    def rag_summarize_with_sources(self, query: str) -> tuple[str, list[dict]]:
        docs = self.retrieve_docs(query)
        answer = self.chain.invoke({"input": query, "context": self.build_context(docs)})
        sources = [
            {"source": doc.metadata.get("source", "未知"), "content": doc.page_content[:200]}
            for doc in docs
        ]
        return answer, sources
