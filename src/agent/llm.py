"""模型接入层。

两种后端：
1. 真实模型：任何 OpenAI 兼容端点（OpenAI / DashScope / DeepSeek / 本地 vLLM...）。
   仅用标准库 urllib，零依赖。
2. 离线 Mock：无 API key 时自动降级。基于工具返回的"事实"做确定性决策。
   边界声明：Mock 只验证流程与决策边界，不证明真实模型的决策能力。

对外统一接口：decide(system, messages) -> dict(动作)
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


class ModelClient:
    def __init__(self, offline: bool | None = None):
        self.base_url = os.environ.get("MODEL_BASE_URL", "").rstrip("/")
        self.api_key = os.environ.get("MODEL_API_KEY", "")
        self.model = os.environ.get("MODEL_NAME", "gpt-4o-mini")
        if offline is None:
            offline = not (self.base_url and self.api_key)
        self.offline = offline

    @property
    def mode(self) -> str:
        return "offline-mock" if self.offline else f"live:{self.model}"

    def decide(self, system: str, messages: list[dict]) -> dict:
        if self.offline:
            return OfflineMock.decide(messages)
        return self._call_live(system, messages)

    # --- 真实模型 ---------------------------------------------------------
    def _call_live(self, system: str, messages: list[dict]) -> dict:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode())
            content = body["choices"][0]["message"]["content"]
            return _parse_action(content)
        except urllib.error.URLError as e:  # 网络层失败
            raise RuntimeError(f"model_call_failed: {e}") from e


def _parse_action(content: str) -> dict:
    """从模型输出里抠出 JSON 动作。模型可能包裹 ```json```，做一次宽松解析。"""
    s = content.strip()
    if s.startswith("```"):
        s = s.strip("`")
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s[:-3]
    start, end = s.find("{"), s.rfind("}")
    if start >= 0 and end > start:
        s = s[start:end + 1]
    return json.loads(s)


class OfflineMock:
    """确定性决策器。输入是对话消息，输出与真实模型同构的动作 dict。

    关键：它只消费"工具事实"，不消费预设剧本——因此两条路径会因为
    工具结果不同而走出不同的动作序列，这才是有效的 ReAct 行为验证。
    """

    @staticmethod
    def decide(messages: list[dict]) -> dict:
        facts = OfflineMock._collect_facts(messages)
        used = facts["used_tools"]
        material = facts["material"]
        rules = facts["rules"]
        slots = facts["slots"]

        # 已尝试保存 → 根据保存结果收尾（幂等/失败都在这处理）
        if "save_draft" in used:
            save = facts["last_save"] or {}
            pending = facts["last_pending"]
            if not save.get("ok"):
                return {"action": "finish", "status": "save_failed",
                        "reason": "草稿保存失败：" + save.get("message", "未知错误"),
                        "pending": ["保存失败，请重试或联系后端"]}
            if save.get("status") == "duplicate":
                status = "needs_confirm" if pending else "draft_saved"
                return {"action": "finish", "status": status,
                        "reason": "相同请求草稿已存在（幂等），未重复保存",
                        "pending": pending}
            # 存在待确认项 → 状态为待确认（草稿已存，但需用户拍板）
            if pending:
                return {"action": "finish", "status": "needs_confirm",
                        "reason": "草稿已保存，但存在待用户确认项",
                        "pending": pending}
            return {"action": "finish", "status": "draft_saved",
                    "reason": "草稿保存成功，无待确认项",
                    "pending": []}

        # 步骤 1：还没读素材 → 读素材
        if "read_material" not in used:
            return {"action": "read_material",
                    "args": {"material_id": facts["target_id"]},
                    "reason": "先获取素材元数据"}

        # 素材不存在 → 请求补充
        if material is None:
            return {"action": "finish", "status": "needs_more_info",
                    "reason": "素材不存在，无法排期",
                    "pending": ["请确认素材 ID"]}

        # 步骤 2：还没查规则 → 查规则
        if "check_rules" not in used:
            return {"action": "check_rules",
                    "args": {"material_id": material["id"]},
                    "reason": "检查审核规则"}

        # 规则问题分两类：信息缺失 → 请求补充；内容违规 → 阻断
        if rules:
            block_issues = [i for i in rules.get("issues", []) if i["severity"] == "block"]
            missing_issues = [i for i in block_issues if i.get("kind") == "missing"]
            violation_issues = [i for i in block_issues if i.get("kind") != "missing"]
            if missing_issues:
                fields = "、".join(sorted({i["field"] for i in missing_issues}))
                return {"action": "finish", "status": "needs_more_info",
                        "reason": f"素材信息缺失，无法完成审核：{fields}",
                        "pending": [f"请补充素材字段：{fields}"]}
            if violation_issues:
                msgs = [i["desc"] for i in violation_issues]
                return {"action": "finish", "status": "blocked",
                        "reason": "存在阻断级规则风险：" + "；".join(msgs),
                        "pending": msgs}

        # 步骤 3：还没查时段 → 查时段
        if "query_slots" not in used:
            return {"action": "query_slots",
                    "args": {"date": material["date"]},
                    "reason": "查询目标日期可用时段"}

        req_time = material["publish_requirement"]["time"]
        is_hard = material["publish_requirement"]["level"] == "hard"
        occupied = slots.get("occupied", {})
        available = slots.get("available", [])
        missing = [i for i in (rules or {}).get("issues", []) if i["severity"] == "warn"]

        warnings = [i["desc"] for i in missing]

        # 时段空闲 → 直接存草稿
        if req_time in available:
            return {"action": "save_draft",
                    "args": {"suggested_time": req_time, "status": "ok"},
                    "reason": f"请求时段 {req_time} 可用，保存草稿",
                    "pending": warnings}

        # 时段被占用 → 冲突处理
        if req_time in occupied:
            if is_hard:
                # 硬性要求：绝不擅自改时段，只能请求确认或阻断
                return {"action": "finish", "status": "needs_confirm",
                        "reason": f"硬性要求时段 {req_time} 已被占用，无权更改，需用户确认",
                        "pending": [f"请求时段 {req_time} 被 {occupied[req_time]} 占用，"
                                    "且为硬性要求，请确认是否调整"]}
            alt = OfflineMock._next_available(available, req_time)
            if alt is None:
                return {"action": "finish", "status": "needs_confirm",
                        "reason": "目标日期无可用时段", "pending": ["无可用时段，请指定日期"]}
            return {"action": "save_draft",
                    "args": {"suggested_time": alt, "status": "conflict_resolved"},
                    "reason": f"请求时段 {req_time} 被占用，改用可用时段 {alt}，标记待确认",
                    "pending": [f"请求时段 {req_time} 被占用，已建议 {alt}，待用户确认"]
                               + warnings}

        # 时段非法
        return {"action": "finish", "status": "needs_confirm",
                "reason": f"时段 {req_time} 非法或不在排期范围",
                "pending": [f"请确认时段 {req_time}"]}

    @staticmethod
    def _next_available(available: list[str], req_time: str) -> str | None:
        if not available:
            return None
        later = [s for s in available if s > req_time]
        return later[0] if later else available[-1]

    # --- 事实收集：从对话历史里还原工具返回 --------------------------------
    @staticmethod
    def _collect_facts(messages: list[dict]) -> dict:
        used, material, rules, slots = [], None, None, None
        target_id = None
        last_save = None
        last_pending: list[str] = []
        for m in messages:
            if m.get("role") == "assistant":
                try:
                    act = _parse_action(m.get("content", ""))
                    name = act.get("action")
                    if name:
                        used.append(name)
                    if name == "read_material":
                        target_id = act.get("args", {}).get("material_id")
                    if name == "save_draft":
                        last_pending = act.get("pending", [])
                except Exception:
                    pass
            if m.get("role") == "tool" or m.get("role") == "user":
                try:
                    obs = json.loads(m.get("content", ""))
                except Exception:
                    continue
                if not isinstance(obs, dict):
                    continue
                if "material_id" in obs and "task" in obs:  # 初始意图
                    target_id = obs["material_id"]
                elif "material" in obs:
                    material = obs["material"]
                elif "issues" in obs:
                    rules = obs
                elif "available" in obs:
                    slots = obs
                elif "fingerprint" in obs:  # save_draft 的返回
                    last_save = obs
        return {"used_tools": used, "material": material, "rules": rules,
                "slots": slots, "target_id": target_id,
                "last_save": last_save, "last_pending": last_pending}
