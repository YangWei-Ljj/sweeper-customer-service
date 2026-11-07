"""向量库服务（改造版）：

- 持久化目录统一通过 get_abs_path 解析（修复原版相对 CWD 产生多处孤儿库）；
- 嵌入模型延迟初始化（factory 单例，导入期不创建模型）；
- 入库带 source 元数据，支持按来源列出/删除；
- 新增 txt/md 文本直传与 PDF/TXT 目录加载。
"""
from __future__ import annotations

import os
from datetime import datetime

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from model.factory import get_embeddings
from utils.config_handler import chroma_conf
from utils.file_handler import (
    get_file_md5_hex,
    listdir_with_allowed_type,
    pdf_loader,
    txt_loader,
)
from utils.logger_handler import logger
from utils.path_tool import get_abs_path

_SEPARATORS = ["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""]


class VectorStoreService:
    def __init__(self):
        persist_dir = get_abs_path(chroma_conf["persist_directory"])
        os.makedirs(persist_dir, exist_ok=True)
        self.vector_store = Chroma(
            collection_name=chroma_conf["collection_name"],
            embedding_function=get_embeddings(),
            persist_directory=persist_dir,
        )
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=int(chroma_conf.get("chunk_size", 400)),
            chunk_overlap=int(chroma_conf.get("chunk_overlap", 80)),
            separators=chroma_conf.get("separators", _SEPARATORS),
            length_function=len,
        )
        self.md5_path = get_abs_path(chroma_conf["md5_hex_store"])

    def get_retriever(self, k: int | None = None):
        k = k or int(chroma_conf.get("k", 4))
        return self.vector_store.as_retriever(search_kwargs={"k": k})

    def similarity_search(self, query: str, k: int | None = None) -> list[Document]:
        return self.get_retriever(k).invoke(query)

    # ---------- 去重 ----------
    def _md5_processed(self, md5_hex: str) -> bool:
        if not os.path.exists(self.md5_path):
            open(self.md5_path, "w", encoding="utf-8").close()
            return False
        with open(self.md5_path, "r", encoding="utf-8") as f:
            return md5_hex in {line.strip() for line in f if line.strip()}

    def _save_md5(self, md5_hex: str) -> None:
        with open(self.md5_path, "a", encoding="utf-8") as f:
            f.write(md5_hex + "\n")

    # ---------- 入库 ----------
    def add_text(self, text: str, source: str, md5_hex: str | None = None) -> int:
        """直接入库文本，返回新增块数。"""
        if md5_hex is None:
            import hashlib
            md5_hex = hashlib.md5(text.encode("utf-8")).hexdigest()
        if self._md5_processed(md5_hex):
            return 0
        chunks = self.splitter.split_text(text)
        if not chunks:
            return 0
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        metadatas = [{"source": source, "chunk_index": i, "create_time": now} for i in range(len(chunks))]
        self.vector_store.add_texts(chunks, metadatas=metadatas)
        self._save_md5(md5_hex)
        return len(chunks)

    def add_file(self, path: str) -> int:
        """入库单个文件（txt/pdf）。"""
        md5_hex = get_file_md5_hex(path)
        if not md5_hex or self._md5_processed(md5_hex):
            logger.info(f"[加载知识库]{path} 已存在，跳过")
            return 0
        if path.lower().endswith(".pdf"):
            documents = pdf_loader(path)
        elif path.lower().endswith((".txt", ".md")):
            documents = txt_loader(path)
        else:
            logger.warning(f"[加载知识库]不支持的文件类型：{path}")
            return 0
        if not documents:
            return 0
        chunks = self.splitter.split_documents(documents)
        if not chunks:
            return 0
        for i, doc in enumerate(chunks):
            doc.metadata = {"source": os.path.basename(path), "chunk_index": i}
        self.vector_store.add_documents(chunks)
        self._save_md5(md5_hex)
        return len(chunks)

    def load_document(self) -> dict:
        """加载 data_path 下全部知识文件（幂等）。返回 {文件: 块数}。"""
        result = {}
        data_path = get_abs_path(chroma_conf["data_path"])
        for path in listdir_with_allowed_type(
            data_path, tuple(chroma_conf["allow_knowledge_file_type"])
        ):
            try:
                n = self.add_file(path)
                if n:
                    result[os.path.basename(path)] = n
                    logger.info(f"[加载知识库]{path} 加载成功，{n} 块")
            except Exception as e:  # noqa: BLE001
                logger.error(f"[加载知识库]{path} 加载失败：{e}", exc_info=True)
        return result

    # ---------- 管理 ----------
    def list_documents(self) -> list[dict]:
        data = self.vector_store.get(include=["metadatas", "documents"])
        stats = {}
        for meta, content in zip(data.get("metadatas", []), data.get("documents", [])):
            source = (meta or {}).get("source", "未知")
            item = stats.setdefault(source, {"source": source, "chunks": 0, "preview": content[:60]})
            item["chunks"] += 1
        return sorted(stats.values(), key=lambda x: x["source"])

    def delete_document(self, source: str) -> int:
        data = self.vector_store.get(where={"source": source}, include=["metadatas"])
        ids = data.get("ids", [])
        if ids:
            self.vector_store.delete(ids=ids)
        return len(ids)
