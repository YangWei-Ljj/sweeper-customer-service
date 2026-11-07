"""高风险工具（模拟 / dry-run）。

这些工具代表"有副作用"的动作：报修派单 / 重置设备 / 下单耗材。
在治理注册表中权限=risk、require_approval=True；**未获人工确认前不会被真正执行**。

为安全与可演示：本模块不真删、真下单、真派单——只是登记意图并返回确认信息。
真实对接业务系统属于后续接入，当前为 dry-run（在返回文案中明确标注"模拟"）。
"""
from __future__ import annotations

from langchain_core.tools import tool


@tool(description="为用户创建扫地机器人报修工单（高风险操作，需人工确认）")
def create_work_order(issue: str, contact: str = "") -> str:
    return (
        f"[模拟·未真实派单] 已登记报修意图：问题={issue}"
        + (f"，联系方式={contact}" if contact else "")
        + "。该操作属高风险，需人工确认后才会真实派单。"
    )


@tool(description="重置指定扫地机器人设备到出厂状态（高风险操作，需人工确认）")
def reset_device(device_id: str) -> str:
    return (
        f"[模拟·未真实重置] 已登记重置意图：设备={device_id}。"
        "重置会清空本机配置，属高风险，需人工确认后才会真实执行。"
    )


@tool(description="下单购买扫地机器人耗材（高风险操作，需人工确认）")
def order_consumables(item: str, qty: int = 1) -> str:
    return (
        f"[模拟·未真实下单] 已登记下单意图：耗材={item} ×{qty}。"
        "下单会产生费用，属高风险，需人工确认后才会真实执行。"
    )
