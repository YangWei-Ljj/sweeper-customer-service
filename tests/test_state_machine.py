"""执行状态机单测：合法转移可达终态、非法转移抛错、异常分支可收尾。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.state_machine import (  # noqa: E402
    AgentStateMachine,
    Event,
    IllegalTransition,
    RunState,
)


def _happy_path() -> AgentStateMachine:
    sm = AgentStateMachine()
    sm.transition(Event.START)                 # PLANNING -> EXECUTING
    sm.transition(Event.TOOL_CALL)             # -> TOOL_PENDING
    sm.transition(Event.TOOL_RESULT)           # -> OBSERVING
    sm.transition(Event.CONTINUE)              # -> EXECUTING
    sm.transition(Event.ANSWER)                # -> SYNTHESIZING
    sm.transition(Event.FINISH)                # -> DONE
    return sm


def test_happy_path_reaches_done():
    sm = _happy_path()
    assert sm.state == RunState.DONE
    assert sm.is_terminal


def test_risk_approval_flow():
    sm = AgentStateMachine()
    sm.transition(Event.START)
    sm.transition(Event.TOOL_CALL)
    sm.transition(Event.NEED_APPROVAL)        # -> APPROVAL_REQUIRED
    assert sm.state == RunState.APPROVAL_REQUIRED
    # 批准后重新进入工具执行
    sm.transition(Event.APPROVED)              # -> TOOL_PENDING
    assert sm.state == RunState.TOOL_PENDING
    # 拒绝则回模型
    sm2 = AgentStateMachine()
    sm2.transition(Event.START)
    sm2.transition(Event.TOOL_CALL)
    sm2.transition(Event.NEED_APPROVAL)
    sm2.transition(Event.DECLINED)             # -> EXECUTING
    assert sm2.state == RunState.EXECUTING


def test_deny_returns_to_executing():
    sm = AgentStateMachine()
    sm.transition(Event.START)
    sm.transition(Event.TOOL_CALL)
    sm.transition(Event.DENY)                  # -> EXECUTING
    assert sm.state == RunState.EXECUTING


def test_illegal_transition_raises():
    sm = _happy_path()  # 已到 DONE
    for ev in (Event.START, Event.TOOL_CALL, Event.ANSWER, Event.FAIL):
        try:
            sm.transition(ev)
            raise AssertionError(f"DONE 后不应能转移 {ev}")
        except IllegalTransition:
            pass


def test_cannot_start_then_finish_directly():
    """PLANNING 不能直接 FINISH/ANSWER。"""
    sm = AgentStateMachine()
    for ev in (Event.FINISH, Event.ANSWER, Event.TOOL_RESULT):
        try:
            sm.transition(ev)
            raise AssertionError(f"PLANNING 不应能响应 {ev}")
        except IllegalTransition:
            pass


def test_exception_branches_finish_to_done():
    for ev, state in (
        (Event.FAIL, RunState.FAILED),
        (Event.DEGRADE, RunState.DEGRADED),
        (Event.HALT, RunState.RECURSION_HALTED),
    ):
        sm = AgentStateMachine()
        sm.transition(Event.START)
        sm.transition(ev)
        assert sm.state == state
        sm.transition(Event.FINISH)
        assert sm.state == RunState.DONE


def test_force_from_running_to_halt():
    sm = AgentStateMachine()
    sm.transition(Event.START)
    sm.force(RunState.RECURSION_HALTED)
    assert sm.state == RunState.RECURSION_HALTED
    sm.transition(Event.FINISH)
    assert sm.state == RunState.DONE


def test_force_blocked_after_done():
    sm = _happy_path()
    try:
        sm.force(RunState.EXECUTING)
        raise AssertionError("DONE 后不应能 force")
    except IllegalTransition:
        pass
