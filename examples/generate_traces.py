#!/usr/bin/env python3
"""生成 examples/ 下的运行记录（Trace）。

运行：python examples/generate_traces.py
会写出 examples/trace_*.json 与实际输出 examples/run_*.txt。
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agent.llm import ModelClient
from src.agent.react_loop import run
from src.agent.tools import DraftStore, Tools

EX = ROOT / "examples"

CASES = [
    ("normal", "M02", "10:00", "正常排期：请求时段空闲"),
    ("slot_conflict", "M01", "18:00", "时段冲突(soft)：18:00 被占，建议 19:00 待确认"),
    ("hard_conflict", "M05", "20:00", "硬性要求冲突：20:00 被占且 level=hard，不擅自改"),
    ("missing_info", "M03", None, "信息缺失：缺 category/copyright/duration_sec"),
    ("rule_risk", "M04", None, "规则风险：时长 180s 超限，阻断"),
    ("save_failed", "M06", "14:00", "保存失败：后端故障注入"),
    ("unknown", "MX9", None, "素材不存在"),
    ("duplicate", "M01", "18:00", "重复提交：连跑两次只出一份草稿"),
]


def main():
    EX.mkdir(exist_ok=True)
    index = []
    for name, mid, t, desc in CASES:
        tools = Tools(DraftStore())
        model = ModelClient(offline=True)
        if name == "duplicate":
            run(mid, t, model=model, tools=tools)
            r = run(mid, t, model=model, tools=tools)
        else:
            r = run(mid, t, model=model, tools=tools)
        record = {
            "case": name,
            "description": desc,
            "material_id": mid,
            "requested_time": t,
            "model_mode": model.mode,
            "status": r.status,
            "pending": r.pending,
            "final": r.final,
            "draft_count": len(tools.store.all()),
            "trace": [vars(s) for s in r.trace],
        }
        path = EX / f"trace_{name}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

        # 同时落盘 CLI 实际 stdout
        cmd = [sys.executable, "-m", "src.main", mid, "--offline", "-v"]
        if t:
            cmd += ["--time", t]
        out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        (EX / f"run_{name}.txt").write_text(out.stdout, encoding="utf-8")
        index.append((name, desc, r.status, len(tools.store.all())))
        print(f"[{name}] status={r.status} drafts={len(tools.store.all())}")

    lines = ["# 运行记录索引", "",
             "| 用例 | 场景 | 最终状态 | 草稿数 | Trace 文件 | CLI 输出 |",
             "|---|---|---|---|---|---|"]
    for name, desc, status, n in index:
        lines.append(f"| {name} | {desc} | `{status}` | {n} | "
                     f"[trace_{name}.json](trace_{name}.json) | [run_{name}.txt](run_{name}.txt) |")
    (EX / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("written to", EX)


if __name__ == "__main__":
    main()
