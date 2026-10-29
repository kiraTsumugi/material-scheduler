# 03 · 评估

## 测试预期 vs 实际结果

全部测试：`python -m unittest discover -s tests -v` → **14 passed**。

| 用例 | 预期 | 实际 | 证据文件 |
|---|---|---|---|
| 正常排期 M02@10:00 | `draft_saved`，1 份草稿 | ✅ | `examples/trace_normal.json` |
| 时段冲突 M01@18:00 | `needs_confirm`，建议 19:00，1 份草稿 | ✅ | `examples/trace_slot_conflict.json` |
| 硬性冲突 M05@20:00 | `needs_confirm`，**0 份草稿**（不改时段） | ✅ | `examples/trace_hard_conflict.json` |
| 信息缺失 M03 | `needs_more_info`，0 份草稿 | ✅ | `examples/trace_missing_info.json` |
| 规则风险 M04 | `blocked`，0 份草稿 | ✅ | `examples/trace_rule_risk.json` |
| 保存失败 M06@14:00 | `save_failed`，0 份草稿 | ✅ | `examples/trace_save_failed.json` |
| 素材不存在 MX9 | `needs_more_info` | ✅ | `examples/trace_unknown.json` |
| 重复提交 M01@18:00 ×2 | 只 1 份草稿 | ✅ | `examples/trace_duplicate.json` |
| 畸形模型输出（非 dict / 未知动作 / 绕过读素材） | 不崩溃，优雅失败 | ✅ | `tests/test_agent.py::TestMalformedModelOutput` |

## ReAct 决策证据

`trace_slot_conflict.json` 的完整轨迹（5 步）：

```
step1 read_material       → 拿到 M01 元数据
step2 check_rules         → issues=[]，无风险
step3 query_slots         → 18:00 被 M99 占用，19:00 可用
step4 save_draft(19:00)   ← 模型据 step3 事实改时段，标记 conflict_resolved
step5 finish(needs_confirm) ← 有待确认项，收尾为待确认（非"已发布"）
```

`trace_normal.json` 走的是不同路径（step4 用原时段 10:00，状态 `draft_saved`）。
**同一段循环代码，因工具事实不同走出不同决策** —— 满足 ReAct 要求。

## 真实模型接入验证

`python examples/verify_live_path.py` 启动本地 OpenAI 兼容 mock server，验证
`_call_live` 的 HTTP 契约（payload / Bearer 鉴权 / response_format / JSON 解析）：
→ **通过**。说明 live 路径可跑，非纸面代码。

## 鲁棒性（真实模型接入的崩溃点修复）

在回归中发现三个"纸面 Mock 跑不出、真实 LLM 会踩"的崩溃点，已修复并加测试固化：

1. **模型返回非 dict**（JSON 解析失败/纯文本）原会 `AttributeError` 崩溃
   → 改为契约校验，把错误作为观察喂回令模型自纠，不崩溃。
2. **未知 action** 原会静默循环到步数上限、丢失中间轨迹
   → 改为喂回 `unknown_action` 错误并保留完整 trace。
3. **未经 read_material 直接 save_draft** 原会 `RuntimeError`
   → 改为返回 `material_not_loaded` 观察令模型自纠。

对应测试：`tests/test_agent.py::TestMalformedModelOutput`（3 项）。

## 失败与限制

1. **Mock 非真实模型决策**：默认离线 Mock 是确定性规则器，只证明**流程与边界**，
   不证明真实 LLM 的决策质量。真实能力需配 `MODEL_*` 后跑。
2. **并发**：`DraftStore` 为进程内内存，多进程/并发下不保证幂等（考核范围外）。
   fingerprint 方案天然可迁移到带唯一索引的持久层。
3. **日期范围**：仅合成数据 `2026-11-01`；其他日期返回"无排期数据"。
4. **规则引擎**：仅支持 `le/eq/exists/nonempty` 四种算子，够覆盖验收场景。
5. **未做真实发布接入**：按题意只存草稿。

## 越权/虚报检查

- 全部输出中不含「已发布」字样（`test_never_claims_published` 断言）。
- 保存失败返回 `save_failed`，不返回 `draft_saved`（`test_save_failure_reported` 断言）。
- 硬性要求冲突时不产生草稿（`test_hard_requirement_not_changed` 断言草稿数=0）。
