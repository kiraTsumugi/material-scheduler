"""业务工具层。

铁律：工具只返回"事实"，绝不返回"决策"。
- read_material 返回素材原始字段（可能缺字段）。
- check_rules 返回触发的规则列表（数据驱动，无 if 分支）。
- query_slots 返回时段占用事实。
- save_draft 是唯一有副作用的工具：幂等 + 可失败。

工具不判断"该不该发布""要不要改时段"——那是模型的活。
"""
from __future__ import annotations

from .models import Draft, Material, load_json


class DraftStore:
    """草稿内存存储。以 fingerprint 为键 → 天然幂等。"""

    def __init__(self):
        self._by_fp: dict[str, Draft] = {}

    def get(self, fp: str) -> Draft | None:
        return self._by_fp.get(fp)

    def put(self, draft: Draft) -> None:
        self._by_fp[draft.fingerprint] = draft

    def all(self) -> list[Draft]:
        return list(self._by_fp.values())


class Tools:
    def __init__(self, store: DraftStore | None = None):
        self._materials = {m["id"]: m for m in load_json("materials.json").values()}
        self._rules = load_json("rules.json")["rules"]
        self._schedule = load_json("schedule.json")
        self.store = store or DraftStore()

    # --- 1. 读素材 ---------------------------------------------------------
    def read_material(self, material_id: str) -> dict:
        raw = self._materials.get(material_id)
        if raw is None:
            return {"ok": False, "error": "not_found", "material_id": material_id}
        # 如实返回，缺失字段就是缺失——工具不替模型补全。
        return {"ok": True, "material": raw}

    # --- 2. 规则检查 -------------------------------------------------------
    def check_rules(self, material_id: str) -> dict:
        raw = self._materials.get(material_id)
        if raw is None:
            return {"ok": False, "error": "not_found", "material_id": material_id}
        md = raw.get("metadata", {})
        issues = []
        for r in self._rules:
            f = r["field"]
            op = r["op"]
            present = f in md
            val = md.get(f)
            hit = False
            if op == "exists":
                hit = not present
            elif op == "nonempty":
                hit = (not present) or (val is None) or (val == [] or val == "")
            elif not present:
                hit = True  # 字段缺失 → 无法满足该规则
            elif op == "le":
                try:
                    hit = float(val) > float(r["value"])
                except (TypeError, ValueError):
                    hit = True
            elif op == "eq":
                hit = val != r["value"]
            if hit:
                # kind 区分"信息缺失"与"内容违规"——二者对应不同的模型决策。
                empty = val is None or val == [] or val == ""
                is_missing = (not present) or (op in ("exists", "nonempty") and empty)
                issues.append({
                    "rule_id": r["id"],
                    "desc": r["desc"],
                    "severity": r["severity"],
                    "kind": "missing" if is_missing else "violation",
                    "field": f,
                    "actual": val if present else "<missing>",
                })
        blocked = [i for i in issues if i["severity"] == "block"]
        missing = [i for i in issues if i["kind"] == "missing"]
        return {
            "ok": True,
            "material_id": material_id,
            "issues": issues,
            "blocked": len(blocked) > 0,
            "has_missing": len(missing) > 0,
            "missing_fields": sorted({i["field"] for i in missing}),
        }

    def _required_fields(self) -> list[str]:
        return [r["field"] for r in self._rules]

    # --- 3. 查时段 ---------------------------------------------------------
    def query_slots(self, date: str) -> dict:
        if date != self._schedule["date"]:
            return {"ok": True, "date": date, "all_slots": [],
                    "occupied": {}, "available": [],
                    "note": "无该日期排期数据"}
        occ = self._schedule["occupied"]
        all_slots = self._schedule["all_slots"]
        available = [s for s in all_slots if s not in occ]
        return {"ok": True, "date": date, "all_slots": all_slots,
                "occupied": occ, "available": available}

    def slot_status(self, date: str, time: str) -> str:
        """单点查询：'occupied' | 'available' | 'invalid'"""
        if date != self._schedule["date"]:
            return "invalid"
        if time in self._schedule["occupied"]:
            return "occupied"
        if time in self._schedule["all_slots"]:
            return "available"
        return "invalid"

    def nearest_available(self, date: str, time: str) -> str | None:
        q = self.query_slots(date)
        avail = q["available"]
        if not avail:
            return None
        # 优先向后找最近的，找不到再向前。
        later = [s for s in avail if s > time]
        return later[0] if later else avail[-1]

    # --- 4. 存草稿（唯一有副作用，幂等 + 可失败）--------------------------
    def save_draft(self, draft: Draft) -> dict:
        # 故障注入：模拟后端保存失败（用于验证失败路径）。
        if draft.material_id in self._schedule.get("_fail_save_injection", []):
            return {"ok": False, "error": "save_failed",
                    "message": "后端存储返回错误，草稿未保存", "fingerprint": draft.fingerprint}
        existing = self.store.get(draft.fingerprint)
        if existing is not None:
            return {"ok": True, "status": "duplicate", "fingerprint": draft.fingerprint,
                    "message": "相同请求已存在草稿，未重复保存", "draft": existing.to_dict()}
        draft.status = "draft_saved"
        self.store.put(draft)
        return {"ok": True, "status": "draft_saved", "fingerprint": draft.fingerprint,
                "message": "草稿已保存", "draft": draft.to_dict()}
