"""使用报告页：选择用户与月份，基于外部使用记录生成月度报告并持久化。"""
import streamlit as st

import store
from agent.tools.agent_tools import list_available_user_months
from report_service import generate_report

st.set_page_config(page_title="使用报告", page_icon="📊", layout="wide")
st.title("📊 扫地机器人使用报告")

store.init_db()

col1, col2 = st.columns(2)
with col1:
    user_id = st.text_input("用户ID", value="1001")

try:
    user_months = list_available_user_months()
except Exception as e:  # noqa: BLE001
    st.error(f"外部数据加载失败：{e}")
    user_months = {}

months = user_months.get(user_id, [])
with col2:
    month = st.selectbox("选择月份", months if months else [])

if st.button("生成报告", type="primary", disabled=not month):
    with st.spinner("正在生成报告…"):
        try:
            content = generate_report(user_id, month)
            if content:
                st.success("报告已生成并保存")
                st.markdown(content)
            else:
                st.warning("未找到该用户对应月份的使用记录。")
        except Exception as e:  # noqa: BLE001
            st.error(f"报告生成失败：{e}")

st.divider()
st.subheader("历史报告")
for r in store.list_reports(user_id):
    with st.expander(f"📄 {r['month']} 月度报告（生成于 {r['created_at']}）"):
        st.markdown(r["content"])
        st.download_button(
            "下载为 Markdown",
            data=r["content"],
            file_name=f"使用报告_{user_id}_{r['month']}.md",
            key=f"rp_{r['id']}",
        )
