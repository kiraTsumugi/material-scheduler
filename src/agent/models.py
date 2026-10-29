"""核心数据结构。

设计原则：把"特殊情况"从代码里删掉，放进数据里。
- 素材的风险来自规则表（数据），不是散落 if 分支。
- 幂等键来自数据结构本身（request_fingerprint），不是额外去重逻辑。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def load_json(name: str) -> Any:
    with open(DATA_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


@dataclass
class Material:
    id: str
    title: str
    date: str
    metadata: dict
    publish_requirement: dict  # {"time": "18:00", "level": "hard"|"soft"}
    requested_by: str = "content_team"

    @property
    def is_hard(self) -> bool:
        """硬性发布时间要求：未经用户同意不得更改。"""
        return self.publish_requirement.get("level") == "hard"

    @property
    def requested_time(self) -> str:
        return self.publish_requirement.get("time", "")


@dataclass
class Draft:
    """草稿。request_fingerprint 是幂等性的根。

    相同 (material_id, requested_time) 只允许存在一份草稿。
    """
    material_id: str
    requested_time: str
    suggested_time: str
    status: str  # draft_saved / duplicate
    risk_summary: str
    pending_confirmations: list[str] = field(default_factory=list)

    @property
    def fingerprint(self) -> str:
        raw = f"{self.material_id}|{self.requested_time}".encode()
        return hashlib.sha256(raw).hexdigest()[:16]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["fingerprint"] = self.fingerprint
        return d


def material_from_dict(d: dict) -> Material:
    return Material(
        id=d["id"],
        title=d["title"],
        date=d["date"],
        metadata=d.get("metadata", {}),
        publish_requirement=d.get("publish_requirement", {}),
        requested_by=d.get("requested_by", "content_team"),
    )
