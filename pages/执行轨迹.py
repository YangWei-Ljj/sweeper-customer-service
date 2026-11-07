"""执行轨迹页（第二轮·可观测）。

查看每次 Agent run 的逐步轨迹：状态机转移、工具调用、脱敏入参、结果摘要、
耗时、是否重试/降级、审批结论。失败/降级/超步/审批拒绝均可在此复盘。
"""
import json

import streamlit as st

from agent import trace

st.set_page_config(page_title="执行轨迹", page_icon="🔍", layout="wide")
st.title("🔍 Agent 执行轨迹")

trace.init_trace_db()

runs = trace.list_runs(limit=50)
if not runs:
    st.info("暂无执行记录。先在「智能客服」页发起一次对话，再回到这里查看轨迹。")
    st.stop()

# ---- 顶部 run 列表 ----
status_emoji = {
    "done": "✅",
    "failed": "❌",
    "degraded": "⚠️",
    "recursion_halted": "🛑",
}

st.subheader(f"最近 {len(runs)} 次 run")
sel = st.selectbox(
    "选择一次 run",
    options=[r["run_id"] for r in runs],
    format_func=lambda rid: next(
        f"{status_emoji.get(r['final_status'], '·')} {r['started_at']} · {r['query'][:28]} "
        f"({r['state']}/{r['final_status']}, {r['step_count']}步, {r['duration_ms']}ms)"
        for r in runs if r["run_id"] == rid
    ),
)

run = next(r for r in runs if r["run_id"] == sel)
steps = trace.get_steps(sel)

# ---- run 概览 ----
c1, c2, c3, c4 = st.columns(4)
c1.metric("最终状态", run["state"])
c2.metric("结论", run.get("final_status") or "-")
c3.metric("耗时(ms)", run.get("duration_ms") or "-")
c4.metric("步数 / 上限", f"{run.get('step_count', 0)} / {run.get('max_steps', 25)}")

st.caption(
    f"用户 {run.get('user_id')} · 会话 {run.get('session_id') or '-'} · "
    f"模型 {run.get('model_label')} · token估算 {run.get('tokens_est')}"
)
with st.expander("本次提问 / 错误摘要"):
    st.markdown(f"**问：** {run.get('query')}")
    if run.get("error"):
        st.error(run["error"])

st.divider()
st.subheader("逐步轨迹")

if not steps:
    st.info("该 run 没有工具步记录（可能为直接回答或异常提前终止）。")
else:
    for s in steps:
        flags = []
        if s.get("retried"):
            flags.append("🔁重试")
        if s.get("degraded"):
            flags.append("⚠️降级")
        if s.get("approved") not in (None, "na"):
            flags.append(f"审批:{s['approved']}")
        flag_str = "　".join(flags)

        with st.container(border=True):
            head = f"**#{s['step_no']}** `{s['state']}` · {s['event']}"
            if s.get("tool_name"):
                head += f" · 工具 `{s['tool_name']}`"
            if s.get("duration_ms") is not None:
                head += f" · {s['duration_ms']}ms"
            if flag_str:
                head += f"　{flag_str}"
            st.markdown(head)

            col_a, col_b = st.columns(2)
            with col_a:
                st.caption("入参（已脱敏）")
                st.json(s.get("args_masked") or {}, expanded=False)
            with col_b:
                st.caption("结果摘要")
                st.write(s.get("result_summary") or "—")
