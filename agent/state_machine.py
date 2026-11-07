"""Agent 执行状态机（第二轮·执行治理核心）。

把 LangGraph 内部黑盒的 ReAct 循环，在应用层显式建模为可单测的状态机：

状态主线：
    PLANNING -> EXECUTING -> TOOL_PENDING -> OBSERVING
              -> (risk 时 APPROVAL_REQUIRED) -> SYNTHESIZING -> DONE
异常分支：FAILED / DEGRADED / RECURSION_HALTED（均可再 FINISH 到 DONE 做友好收尾）

设计原则：
- 纯 Python，不依赖模型/网络/DB，全部逻辑可单测；
- 非法转移直接抛 IllegalTransition（宁可报错也不静默走错路）；
- 运行态（非终态）才能被 FAIL/DEGRADE/HALT 命中；
- DONE / FAILED / DEGRADED / RECURSION_HALTED 为终态（FAILED/DEGRADED/RECURSION_HALTED 可 FINISH 到 DONE）。
"""
from __future__ import annotations

from enum import Enum


class RunState(str, Enum):
    """一次 Agent run 的执行状态。"""

    PLANNING = "PLANNING"            # 已建档、尚未进入模型
    EXECUTING = "EXECUTING"          # 模型决策中
    TOOL_PENDING = "TOOL_PENDING"    # 模型已决定调工具、等待执行
    OBSERVING = "OBSERVING"          # 已拿到工具观察、待回模型
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"  # risk 工具等待人工确认
    SYNTHESIZING = "SYNTHESIZING"    # 信息足够、正在合成最终回答
    DONE = "DONE"                    # 正常完成
    FAILED = "FAILED"                # 未捕获异常（友好收尾）
    DEGRADED = "DEGRADED"            # 可恢复降级（部分结果）
    RECURSION_HALTED = "RECURSION_HALTED"  # 超步/同参循环保护强制停止


class Event(str, Enum):
    """驱动状态转移的事件。"""

    START = "START"
    TOOL_CALL = "TOOL_CALL"
    TOOL_RESULT = "TOOL_RESULT"
    NEED_APPROVAL = "NEED_APPROVAL"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    DENY = "DENY"
    CONTINUE = "CONTINUE"
    ANSWER = "ANSWER"
    FINISH = "FINISH"
    FAIL = "FAIL"
    DEGRADE = "DEGRADE"
    HALT = "HALT"


# 可被异常事件命中的运行态（非终态）
_RUNNING_STATES = frozenset(
    {
        RunState.PLANNING,
        RunState.EXECUTING,
        RunState.TOOL_PENDING,
        RunState.OBSERVING,
        RunState.APPROVAL_REQUIRED,
        RunState.SYNTHESIZING,
    }
)

# 合法转移表：{(当前状态, 事件): 目标状态}
_TRANSITIONS: dict[tuple[RunState, Event], RunState] = {
    (RunState.PLANNING, Event.START): RunState.EXECUTING,
    (RunState.EXECUTING, Event.TOOL_CALL): RunState.TOOL_PENDING,
    (RunState.EXECUTING, Event.ANSWER): RunState.SYNTHESIZING,
    (RunState.TOOL_PENDING, Event.TOOL_RESULT): RunState.OBSERVING,
    (RunState.TOOL_PENDING, Event.NEED_APPROVAL): RunState.APPROVAL_REQUIRED,
    (RunState.TOOL_PENDING, Event.DENY): RunState.EXECUTING,
    (RunState.APPROVAL_REQUIRED, Event.APPROVED): RunState.TOOL_PENDING,
    (RunState.APPROVAL_REQUIRED, Event.DECLINED): RunState.EXECUTING,
    (RunState.OBSERVING, Event.CONTINUE): RunState.EXECUTING,
    (RunState.OBSERVING, Event.ANSWER): RunState.SYNTHESIZING,
    (RunState.SYNTHESIZING, Event.FINISH): RunState.DONE,
    # 异常分支：任意运行态均可命中
    (RunState.PLANNING, Event.FAIL): RunState.FAILED,
    (RunState.EXECUTING, Event.FAIL): RunState.FAILED,
    (RunState.TOOL_PENDING, Event.FAIL): RunState.FAILED,
    (RunState.OBSERVING, Event.FAIL): RunState.FAILED,
    (RunState.APPROVAL_REQUIRED, Event.FAIL): RunState.FAILED,
    (RunState.SYNTHESIZING, Event.FAIL): RunState.FAILED,
    (RunState.PLANNING, Event.DEGRADE): RunState.DEGRADED,
    (RunState.EXECUTING, Event.DEGRADE): RunState.DEGRADED,
    (RunState.TOOL_PENDING, Event.DEGRADE): RunState.DEGRADED,
    (RunState.OBSERVING, Event.DEGRADE): RunState.DEGRADED,
    (RunState.APPROVAL_REQUIRED, Event.DEGRADE): RunState.DEGRADED,
    (RunState.SYNTHESIZING, Event.DEGRADE): RunState.DEGRADED,
    (RunState.PLANNING, Event.HALT): RunState.RECURSION_HALTED,
    (RunState.EXECUTING, Event.HALT): RunState.RECURSION_HALTED,
    (RunState.TOOL_PENDING, Event.HALT): RunState.RECURSION_HALTED,
    (RunState.OBSERVING, Event.HALT): RunState.RECURSION_HALTED,
    (RunState.APPROVAL_REQUIRED, Event.HALT): RunState.RECURSION_HALTED,
    (RunState.SYNTHESIZING, Event.HALT): RunState.RECURSION_HALTED,
    # 异常态友好收尾到 DONE
    (RunState.FAILED, Event.FINISH): RunState.DONE,
    (RunState.DEGRADED, Event.FINISH): RunState.DONE,
    (RunState.RECURSION_HALTED, Event.FINISH): RunState.DONE,
}


class IllegalTransition(Exception):
    """非法的状态转移（例如终态后再调用工具）。"""


class AgentStateMachine:
    """一次 run 的状态机实例。纯内存、可单测。"""

    def __init__(self) -> None:
        self._state: RunState = RunState.PLANNING
        self.history: list[tuple[str, str]] = []  # [(event_name, state_name_after)]

    @property
    def state(self) -> RunState:
        return self._state

    @property
    def is_terminal(self) -> bool:
        return self._state in (RunState.DONE, RunState.FAILED,
                               RunState.DEGRADED, RunState.RECURSION_HALTED)

    @property
    def is_running(self) -> bool:
        return self._state in _RUNNING_STATES

    def transition(self, event: Event) -> RunState:
        """按事件转移到下一个合法状态；非法转移抛 IllegalTransition。"""
        key = (self._state, event)
        if key not in _TRANSITIONS:
            raise IllegalTransition(
                f"非法状态转移：状态 {self._state.value} 不能响应事件 {event.value}"
            )
        nxt = _TRANSITIONS[key]
        self._state = nxt
        self.history.append((event.value, nxt.value))
        return nxt

    def force(self, state: RunState) -> RunState:
        """仅供收尾兜底：直接置位（如 GraphRecursionError 直接进 RECURSION_HALTED）。

        会校验：只能从运行态进入异常/终态，禁止从 DONE 再挪动。
        """
        if self._state == RunState.DONE:
            raise IllegalTransition("已在终态 DONE，不允许再强制置位")
        self._state = state
        self.history.append(("FORCE", state.value))
        return state
