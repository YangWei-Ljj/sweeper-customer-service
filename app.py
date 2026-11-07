"""智扫通机器人智能客服（改造版主入口）。

- 多页：本页为智能问答；知识库管理、使用报告见左侧页面；
- 会话持久化（SQLite）、多轮记忆、真实 token 流式；
- 用户ID/城市在侧栏设置，替代原版随机。
"""
import uuid

import streamlit as st

import store
from agent import trace
from agent.react_agent import ReactAgent
from model.factory import (
    DEEPSEEK_API_KEY,
    MODEL_PROVIDER,
    chat_model_label,
    OLLAMA_BASE_URL,
)
from rag.vector_store import VectorStoreService

st.set_page_config(page_title="智扫通机器人智能客服", page_icon="🤖", layout="wide")
store.init_db()
trace.init_trace_db()


@st.cache_resource
def get_agent() -> ReactAgent:
    return ReactAgent()


@st.cache_resource
def get_vector_store() -> VectorStoreService:
    return VectorStoreService()


def model_status() -> tuple[bool, str]:
    try:
        from openai import OpenAI

        if MODEL_PROVIDER == "ollama":
            client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")
            client.models.list()
        else:
            client = OpenAI(api_key=DEEPSEEK_API_KEY)
            client.models.list()
        return True, "正常"
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:80]


# ---------- 侧栏 ----------
with st.sidebar:
    st.header("🤖 智扫通客服")
    ok, msg = model_status()
    st.caption(f"模型：{chat_model_label()}")
    if ok:
        st.success("模型服务正常", icon="✅")
    else:
        st.error(f"模型服务异常：{msg}", icon="❌")

    st.divider()
    default_user = st.session_state.get("user_id", "1001")
    default_loc = st.session_state.get("location", "杭州")
    user_id = st.text_input("用户ID", value=default_user, key="user_id_input")
    location = st.text_input("所在城市", value=default_loc, key="location_input")
    st.session_state["user_id"] = user_id or "1001"
    st.session_state["location"] = location or "杭州"

    st.divider()
    if st.button("➕ 新会话", use_container_width=True):
        st.session_state["current_session"] = None
        st.rerun()

    sessions = store.list_sessions(st.session_state["user_id"])
    for s in sessions:
        if st.button(f"💬 {s['title'][:18]}", key=f"sess_{s['session_id']}", use_container_width=True):
            st.session_state["current_session"] = s["session_id"]
            st.rerun()

    st.divider()
    st.caption("知识库：左侧「📚 知识库管理」可上传资料、重建索引；\n使用报告：左侧「📊 使用报告」生成月报。")

# ---------- 主区 ----------
st.title("智扫通机器人智能客服")
st.caption("支持扫地机器人 100 问、故障排除、维护保养、选购指南等知识库问答；也可查询当前城市天气。")

session_id = st.session_state.get("current_session")
if not session_id:
    session_id = uuid.uuid4().hex
    store.create_session(session_id, st.session_state["user_id"], "新会话")
    st.session_state["current_session"] = session_id

history_msgs = store.get_messages(session_id)
for m in history_msgs:
    with st.chat_message(m["role"]):
        st.write(m["content"])
        if m.get("sources"):
            with st.expander(f"📎 引用来源（{len(m['sources'])}）"):
                for i, s in enumerate(m["sources"], 1):
                    st.markdown(f"**[{i}] {s.get('source','未知')}**")
                    st.caption(s.get("content", ""))

prompt = st.chat_input("请输入问题，例如：扫地机器人迷路了怎么办？")
if prompt:
    # 首条消息作为会话标题
    if not history_msgs:
        conn = store.get_conn()
        conn.execute("UPDATE chat_sessions SET title=? WHERE session_id=?", (prompt[:30], session_id))
        conn.commit()
        conn.close()
    store.add_message(session_id, "user", prompt)
    with st.chat_message("user"):
        st.write(prompt)

    history_for_agent = [
        {"role": m["role"], "content": m["content"]} for m in history_msgs[-19:]
    ]
    with st.chat_message("assistant"):
        answer = st.write_stream(
            get_agent().execute_stream(
                prompt,
                history=history_for_agent,
                user_id=st.session_state["user_id"],
                location=st.session_state["location"],
                session_id=session_id,
            )
        )
    store.add_message(session_id, "assistant", answer)
    st.rerun()
