# 运行记录索引

| 用例 | 场景 | 最终状态 | 草稿数 | Trace 文件 | CLI 输出 |
|---|---|---|---|---|---|
| normal | 正常排期：请求时段空闲 | `draft_saved` | 1 | [trace_normal.json](trace_normal.json) | [run_normal.txt](run_normal.txt) |
| slot_conflict | 时段冲突(soft)：18:00 被占，建议 19:00 待确认 | `needs_confirm` | 1 | [trace_slot_conflict.json](trace_slot_conflict.json) | [run_slot_conflict.txt](run_slot_conflict.txt) |
| hard_conflict | 硬性要求冲突：20:00 被占且 level=hard，不擅自改 | `needs_confirm` | 0 | [trace_hard_conflict.json](trace_hard_conflict.json) | [run_hard_conflict.txt](run_hard_conflict.txt) |
| missing_info | 信息缺失：缺 category/copyright/duration_sec | `needs_more_info` | 0 | [trace_missing_info.json](trace_missing_info.json) | [run_missing_info.txt](run_missing_info.txt) |
| rule_risk | 规则风险：时长 180s 超限，阻断 | `blocked` | 0 | [trace_rule_risk.json](trace_rule_risk.json) | [run_rule_risk.txt](run_rule_risk.txt) |
| save_failed | 保存失败：后端故障注入 | `save_failed` | 0 | [trace_save_failed.json](trace_save_failed.json) | [run_save_failed.txt](run_save_failed.txt) |
| unknown | 素材不存在 | `needs_more_info` | 0 | [trace_unknown.json](trace_unknown.json) | [run_unknown.txt](run_unknown.txt) |
| duplicate | 重复提交：连跑两次只出一份草稿 | `needs_confirm` | 1 | [trace_duplicate.json](trace_duplicate.json) | [run_duplicate.txt](run_duplicate.txt) |
