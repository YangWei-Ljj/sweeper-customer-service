"""知识库管理页：上传知识文件、查看文档列表、删除、全量重建。"""
import os
import tempfile

import streamlit as st

from rag.vector_store import VectorStoreService
from utils.config_handler import chroma_conf
from utils.path_tool import get_abs_path

st.set_page_config(page_title="知识库管理", page_icon="📚", layout="wide")
st.title("📚 知识库管理")


@st.cache_resource
def get_vector_store() -> VectorStoreService:
    return VectorStoreService()


vs = get_vector_store()

tab1, tab2 = st.tabs(["📄 文档列表", "⬆️ 上传与重建"])

with tab1:
    docs = vs.list_documents()
    st.caption(f"当前共 {len(docs)} 个知识文件")
    if docs:
        for d in docs:
            col1, col2, col3 = st.columns([5, 1, 1])
            col1.markdown(f"**{d['source']}**　·　{d['chunks']} 块　·　预览：{d['preview']}…")
            col2.download_button(
                "查看",
                data=d["preview"],
                file_name="preview.txt",
                key=f"dl_{d['source']}",
                use_container_width=True,
            )
            if col3.button("删除", key=f"del_{d['source']}", use_container_width=True):
                n = vs.delete_document(d["source"])
                st.cache_resource.clear()
                st.success(f"已删除 {d['source']}（{n} 块）")
                st.rerun()
    else:
        st.info("知识库为空，请先在「上传与重建」页添加文件或执行重建。")

with tab2:
    allowed = tuple(chroma_conf["allow_knowledge_file_type"])
    st.markdown(f"支持格式：**{', '.join(allowed)}**，单文件 ≤ 20MB")
    uploaded = st.file_uploader("上传知识文件", type=allowed)
    if uploaded is not None and st.button("加入知识库", type="primary"):
        data_dir = get_abs_path(chroma_conf["data_path"])
        os.makedirs(data_dir, exist_ok=True)
        save_path = os.path.join(data_dir, uploaded.name)
        with open(save_path, "wb") as f:
            f.write(uploaded.getbuffer())
        with st.spinner("正在切分并生成向量（本地嵌入模型，可能需要数十秒）…"):
            try:
                n = vs.add_file(save_path)
                st.success(f"已入库 {uploaded.name}：{n} 个块" if n else f"{uploaded.name} 已存在，已跳过")
            except Exception as e:  # noqa: BLE001
                st.error(f"入库失败：{e}")

    st.divider()
    st.markdown("**全量重建**：清空当前向量库，重新加载 `data/` 下所有知识文件。")
    if st.button("清空并全量重建"):
        with st.spinner("正在全量重建…"):
            import chromadb
            from utils.config_handler import chroma_conf as conf

            persist_dir = get_abs_path(conf["persist_directory"])
            client = chromadb.PersistentClient(path=persist_dir)
            try:
                client.delete_collection(conf["collection_name"])
            except Exception:  # noqa: BLE001
                pass
            md5_path = get_abs_path(conf["md5_hex_store"])
            if os.path.exists(md5_path):
                open(md5_path, "w", encoding="utf-8").close()
            st.cache_resource.clear()
            vs2 = VectorStoreService()
            result = vs2.load_document()
            st.success(f"重建完成：{len(result)} 个文件，{sum(result.values())} 个块")
            st.rerun()
