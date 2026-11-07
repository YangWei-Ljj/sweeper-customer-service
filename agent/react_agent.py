"""ReAct 智能体（第二轮·执行治理旗舰版）。

在第一轮基础上新增：
- 显式执行状态机（PLANNING->...->DONE，异常 FAILED/DEGRADED/RECURSION_HALTED）；
- 每次 run 开/关轨迹（agent_runs + agent_steps），脱敏入参、耗时、重试/降级/审批留痕；
- 工具治理中间件（schema 校验 + 权限分级 + risk 人工确认闸门）；
- 高风险工具（dry-run）纳入白名单；
- 单 run 总时长上限 + 图级最大步数，异常优雅收尾（绝不把堆栈抛给前端）。

第一轮能力全部保留：token 级流式、多轮记忆、loop_guard 同参保护、最终回答净化。
"""
from __future__ import annotations

import time
import uuid

from langchain.agents import create_agent
from langchain_core.messages import AIMessageChunk
from langgraph.errors import GraphRecursionError

from agent import trace
from agent.state_machine import AgentStateMachine, Event, IllegalTransition, RunState
from agent.tools.agent_tools import (
    CURRENT_LOCATION,
    CURRENT_USER_ID,
    fetch_external_data,
    fill_context_for_report,
    get_current_month,
    get_user_id,
    get_user_location,
    rag_summarize,
)
from agent.tools.governance import governance
from agent.tools.mcp_weather import get_weather
from agent.tools.middleware import log_before_model, loop_guard, monitor_tool, report_prompt_switch
from agent.tools.risk_tools import create_work_order, order_consumables, reset_device
from model.factory import chat_model_label, get_chat_model
from utils.logger_handler import logger
from utils.prompt_loader import load_system_prompts
from utils.text_clean import sanitize_final_answer

# 图级最大步数（硬兜底）
MAX_RECURSION_STEPS = 25
# 单 run 总时长上限（秒）：超过即优雅收尾
MAX_RUN_SECONDS = 120


class ReactAgent:
    def __init__(self):
        trace.init_trace_db()
        self.agent = create_agent(
            model=get_chat_model(),
            system_prompt=load_system_prompts(),
            tools=[
                rag_summarize,
                get_weather,
                get_user_location,
                get_user_id,
                get_current_month,
                fetch_external_data,
                fill_context_for_report,
                # 高风险（dry-run，治理中间件会拦截未确认调用）
                create_work_order,
                reset_device,
                order_consumables,
            ],
            # governance 最外层：先授权/审批/写轨迹，再进 loop_guard
            middleware=[
                governance,
                loop_guard,
                monitor_tool,
                log_before_model,
                report_prompt_switch,
            ],
        )

    def _safe_transition(self, sm: AgentStateMachine, event: Event) -> None:
        try:
            sm.transition(event)
        except IllegalTransition:
            logger.debug(f"[state] 跳过非法转移事件 {event.value}（当前 {sm.state.value}）")

    def execute_stream(self, query: str, history: list[dict] | None = None,
                       user_id: str = "1001", location: str = "杭州",
                       session_id: str | None = None,
                       approvals: set[str] | None = None):
        """逐 token 流式回答，并完整记录一次 run 的执行轨迹。"""
        query = (query or "").strip()
        run_id = uuid.uuid4().hex
        sm = AgentStateMachine()

        # 空输入：直接友好返回，不开 run
        if not query:
            yield "抱歉，我没有收到您的问题，请输入您想咨询的内容。"
            return

        trace.start_run(
            run_id=run_id, session_id=session_id or "", user_id=user_id,
            query=query[:500], state=sm.state.value, max_steps=MAX_RECURSION_STEPS,
            model_label=chat_model_label(),
        )
        started = time.perf_counter()

        messages = [
            {"role": m["role"], "content": m["content"]}
            for m in (history or [])
            if m.get("role") in ("user", "assistant") and m.get("content")
        ]
        messages.append({"role": "user", "content": query})

        uid_token = CURRENT_USER_ID.set(str(user_id))
        loc_token = CURRENT_LOCATION.set(str(location))
        final_status = "done"
        error_msg = None
        final_answer_emitted = False

        try:
            cur_step = None
            cur_text: list[str] = []
            cur_has_tool = False

            try:
                stream = self.agent.stream(
                    {"messages": messages},
                    stream_mode="messages",
                    context={
                        "report": False,
                        "run_id": run_id,
                        "sm": sm,
                        "approvals": set(approvals or set()),
                    },
                    config={"recursion_limit": MAX_RECURSION_STEPS},
                )
                for chunk, metadata in stream:
                    # 单 run 总时长上限
                    if time.perf_counter() - started > MAX_RUN_SECONDS:
                        raise TimeoutError(f"超过单 run 时长上限 {MAX_RUN_SECONDS}s")

                    node = metadata.get("langgraph_node")
                    step = metadata.get("langgraph_step")

                    if node in ("model", "agent") and isinstance(chunk, AIMessageChunk):
                        # 第一个模型轮次：PLANNING -> EXECUTING
                        if sm.state == RunState.PLANNING:
                            self._safe_transition(sm, Event.START)
                        if step != cur_step:
                            # 收尾上一个模型轮次（无工具调用 = 最终回答）
                            if cur_step is not None and not cur_has_tool and cur_text:
                                self._safe_transition(sm, Event.ANSWER)
                                self._safe_transition(sm, Event.FINISH)
                                out = sanitize_final_answer("".join(cur_text))
                                final_answer_emitted = True
                                yield out
                            cur_step, cur_text, cur_has_tool = step, [], False
                        if chunk.content:
                            cur_text.append(chunk.content)
                        if getattr(chunk, "tool_call_chunks", None):
                            cur_has_tool = True
                            self._safe_transition(sm, Event.TOOL_CALL)
                    elif node == "tools":
                        cur_has_tool = True
                        if sm.state == RunState.TOOL_PENDING:
                            self._safe_transition(sm, Event.TOOL_RESULT)
                        if sm.state == RunState.OBSERVING:
                            self._safe_transition(sm, Event.CONTINUE)

                if cur_step is not None and not cur_has_tool and cur_text:
                    self._safe_transition(sm, Event.ANSWER)
                    self._safe_transition(sm, Event.FINISH)
                    out = sanitize_final_answer("".join(cur_text))
                    final_answer_emitted = True
                    yield out

            except GraphRecursionError:
                final_status = "recursion_halted"
            except TimeoutError as te:
                final_status = "recursion_halted"
                error_msg = str(te)
            except Exception as e:  # noqa: BLE001
                final_status = "failed"
                error_msg = str(e)[:300]
                logger.exception(f"[agent] run {run_id} 执行异常")

            # 异常/超时分支的友好收尾
            if final_status == "recursion_halted":
                sm.force(RunState.RECURSION_HALTED)
                self._safe_transition(sm, Event.FINISH)
                msg = (
                    "抱歉，本次任务执行步数/时长已达安全上限，为避免无限循环已自动停止。"
                    "请换一个更具体的问题，或减少连续查询的步骤。"
                )
                yield sanitize_final_answer(msg)
            elif final_status == "failed":
                sm.force(RunState.FAILED)
                self._safe_transition(sm, Event.FINISH)
                msg = "抱歉，处理您的问题时出现了内部错误，请稍后重试或换个问法。"
                yield sanitize_final_answer(msg)
            elif not final_answer_emitted:
                self._safe_transition(sm, Event.FINISH)

        finally:
            CURRENT_USER_ID.reset(uid_token)
            CURRENT_LOCATION.reset(loc_token)
            trace.end_run(
                run_id=run_id, state=sm.state.value,
                final_status=final_status, error=error_msg,
            )


if __name__ == "__main__":
    agent = ReactAgent()
    for chunk in agent.execute_stream("扫地机器人迷路了怎么办？"):
        print(chunk, end="", flush=True)
