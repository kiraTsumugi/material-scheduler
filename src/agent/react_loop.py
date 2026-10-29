"""ReAct 决策循环。

循环骨架：模型输出动作 → 执行工具 → 把观察结果喂回模型 → 模型决定下一步。
硬约束：
- 步数上限 MAX_STEPS，达到即返回 status=incomplete，绝不假装成功。
- 动作分发无业务 if：工具名从模型动作里读，事实由工具产出，决策由模型做。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from .llm import ModelClient
from .models import Draft
from .tools import Tools

MAX_STEPS = 8
TOOL_ACTIONS = {"read_material", "check_rules", "query_slots", "save_draft"}

SYSTEM_PROMPT = """你是"素材审核与发布排期 Agent"。你的职责：为待发布素材生成无冲突、可确认的发布排期草稿。

你有 4 个工具，只能通过下面 JSON 动作调用：
- {"action":"read_material","args":{"material_id":"..."},"reason":"..."}
- {"action":"check_rules","args":{"material_id":"..."},"reason":"..."}
- {"action":"query_slots","args":{"date":"YYYY-MM-DD"},"reason":"..."}
- {"action":"save_draft","args":{"suggested_time":"HH:MM","status":"ok|conflict_resolved"},"reason":"...","pending":["..."]}
结束用：{"action":"finish","status":"draft_saved|needs_confirm|blocked|incomplete","reason":"...","pending":["..."]}

铁律：
1. 只保存草稿，绝不声称"已发布"。
2. 硬性发布要求(publish_requirement.level=hard)未经用户同意不得更改，冲突时只能请求确认或阻断。
3. 时段被占用时，若为 soft 要求可建议替代时段并标记待确认。
4. 规则存在 block 级风险时阻断；存在 warn 时作为待确认项列出。
5. 每次只输出一个 JSON 动作，不要多余文字。"""


@dataclass
class Step:
    n: int
    action: str
    args: dict
    reason: str
    observation: dict | None = None


@dataclass
class Result:
    status: str
    material_id: str
    trace: list[Step] = field(default_factory=list)
    final: dict = field(default_factory=dict)
    pending: list[str] = field(default_factory=list)
    saved: dict | None = None


def run(material_id: str, requested_time: str | None = None,
        model: ModelClient | None = None, tools: Tools | None = None) -> Result:
    model = model or ModelClient()
    tools = tools or Tools()

    user_intent = f"请为素材 {material_id} 生成发布排期草稿。"
    if requested_time:
        user_intent += f" 用户希望发布时间 {requested_time}（覆盖素材默认要求）。"
    # 结构化意图：既是给模型的任务描述，也携带解析所需字段。
    intent = {"task": user_intent, "material_id": material_id,
              "requested_time": requested_time}

    messages: list[dict] = [{"role": "user", "content": json.dumps(intent, ensure_ascii=False)}]
    trace: list[Step] = []

    for step_no in range(1, MAX_STEPS + 1):
        action = model.decide(SYSTEM_PROMPT, messages)

        # 契约校验：真实模型可能返回非 dict（解析失败/纯文本）。
        # 不崩溃——把错误作为观察喂回，让模型自我纠正。
        if not isinstance(action, dict):
            step = Step(n=step_no, action="<invalid>", args={},
                        reason="模型返回非结构化输出",
                        observation={"error": "invalid_action", "got": str(action)[:120]})
            trace.append(step)
            messages.append({"role": "user", "content": json.dumps(
                {"error": "invalid_action",
                 "hint": "请只输出一个 JSON 动作对象"}, ensure_ascii=False)})
            continue

        name = action.get("action", "")
        args = action.get("args", {}) or {}
        reason = action.get("reason", "")
        step = Step(n=step_no, action=name, args=args, reason=reason)

        # 模型想结束
        if name == "finish":
            step.observation = {"finished": True, "status": action.get("status")}
            trace.append(step)
            return Result(status=action.get("status", "incomplete"),
                          material_id=material_id, trace=trace,
                          final=action, pending=action.get("pending", []))

        # 模型要调工具
        if name in TOOL_ACTIONS:
            obs = _dispatch(tools, name, args, material_id, messages, requested_time)
            step.observation = obs
            trace.append(step)
            messages.append({"role": "assistant", "content": json.dumps(action)})
            messages.append({"role": "user", "content": json.dumps(obs, ensure_ascii=False)})
            if name == "save_draft":
                continue
            continue

        # 未知动作：喂回错误，让模型重选（而非静默循环）
        step.observation = {"error": "unknown_action", "action": name,
                            "valid": sorted(TOOL_ACTIONS | {"finish"})}
        trace.append(step)
        messages.append({"role": "user", "content": json.dumps(
            {"error": "unknown_action", "action": name,
             "hint": "请从合法动作中重选"}, ensure_ascii=False)})

    # 超过步数上限
    trace.append(Step(n=MAX_STEPS + 1, action="abort",
                      args={}, reason="达到步数上限",
                      observation={"error": "max_steps_exceeded"}))
    return Result(status="incomplete", material_id=material_id, trace=trace,
                  final={"reason": f"达到最大步数 {MAX_STEPS} 仍未完成"},
                  pending=["执行步数超限，未完成任务"])


def _dispatch(tools: Tools, name: str, args: dict, material_id: str,
              messages: list[dict], requested_time: str | None) -> dict:
    if name == "read_material":
        obs = tools.read_material(args.get("material_id", material_id))
        # 应用用户的时段覆盖（用户显式要求优先）
        if obs.get("ok") and requested_time:
            obs["material"]["publish_requirement"]["time"] = requested_time
        return obs
    if name == "check_rules":
        return tools.check_rules(args.get("material_id", material_id))
    if name == "query_slots":
        return tools.query_slots(args.get("date", ""))
    if name == "save_draft":
        # 需要素材的 requested_time 作为幂等键——从历史事实里取。
        # 若模型绕过 read_material 直接保存，返回错误观察令其自纠，而非崩溃。
        mat = _latest_material(messages, requested_time)
        if mat is None:
            return {"ok": False, "error": "material_not_loaded",
                    "message": "保存前必须先调用 read_material 获取素材"}
        draft = Draft(
            material_id=mat["id"],
            requested_time=mat["publish_requirement"]["time"],
            suggested_time=args.get("suggested_time", mat["publish_requirement"]["time"]),
            status=args.get("status", "ok"),
            risk_summary="",
            pending_confirmations=args.get("pending", []),
        )
        return tools.save_draft(draft)
    return {"ok": False, "error": "unknown_action", "action": name}


def _latest_material(messages: list[dict],
                     requested_time: str | None) -> dict | None:
    """从对话历史里取最近一次 read_material 的观察结果。找不到返回 None。"""
    for m in reversed(messages):
        try:
            obs = json.loads(m.get("content", ""))
        except Exception:
            continue
        if isinstance(obs, dict) and "material" in obs:
            mat = obs["material"]
            if requested_time:
                mat["publish_requirement"]["time"] = requested_time
            return mat
    return None
