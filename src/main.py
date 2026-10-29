"""CLI 入口。

用法：
  python -m src.main M01                          # 使用素材默认要求
  python -m src.main M01 --time 18:00             # 用户指定时段（覆盖默认）
  python -m src.main M01 --time 18:00 --json      # 输出机器可读 JSON
  python -m src.main M01 --time 18:00 --trace out.json   # 同时落盘 trace
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from .agent.llm import ModelClient
from .agent.react_loop import Result, run
from .agent.tools import Tools, DraftStore

STATUS_LABEL = {
    "draft_saved": "草稿已保存",
    "needs_confirm": "待用户确认",
    "needs_more_info": "资料不足，待补充",
    "blocked": "已阻断（规则违规）",
    "save_failed": "保存失败",
    "incomplete": "未完成（步数超限）",
}


def _result_to_dict(r: Result) -> dict:
    return {
        "status": r.status,
        "status_label": STATUS_LABEL.get(r.status, r.status),
        "material_id": r.material_id,
        "pending": r.pending,
        "final": r.final,
        "trace": [asdict(s) for s in r.trace],
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="material-scheduler")
    p.add_argument("material_id", help="素材 ID，如 M01")
    p.add_argument("--time", default=None, help="用户指定发布时间 HH:MM（覆盖素材默认要求）")
    p.add_argument("--json", action="store_true", help="以 JSON 输出完整结果")
    p.add_argument("--trace", default=None, help="将完整 trace 写入指定文件")
    p.add_argument("--offline", action="store_true", help="强制离线 Mock 模型")
    p.add_argument("--verbose", "-v", action="store_true", help="打印每步决策")
    args = p.parse_args(argv)

    model = ModelClient(offline=True if args.offline else None)
    tools = Tools(DraftStore())

    result = run(args.material_id, requested_time=args.time, model=model, tools=tools)
    out = _result_to_dict(result)
    out["model_mode"] = model.mode

    if args.trace:
        with open(args.trace, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if result.status != "incomplete" else 2

    if args.verbose:
        print(f"[model] {model.mode}")
        for s in result.trace:
            print(f"  step {s.n}: {s.action} args={s.args}  ← {s.reason}")
            if s.observation:
                print(f"           obs={json.dumps(s.observation, ensure_ascii=False)[:160]}")

    print(f"\n素材: {result.material_id}")
    print(f"状态: {STATUS_LABEL.get(result.status, result.status)}")
    print(f"决策依据: {result.final.get('reason', '')}")
    if result.pending:
        print("待确认项:")
        for item in result.pending:
            print(f"  - {item}")
    saved = next((s.observation for s in result.trace
                  if s.action == "save_draft" and s.observation), None)
    if saved:
        if saved.get("ok"):
            print(f"保存结果: {saved.get('status')} ({saved.get('message', '')})")
        else:
            print(f"保存结果: 失败 - {saved.get('message', saved.get('error', ''))}")
    else:
        print("保存结果: 未保存草稿")

    return 0 if result.status != "incomplete" else 2


if __name__ == "__main__":
    sys.exit(main())
