# 04 · AI 辅助说明

## 使用的 AI 工具与范围

| 环节 | AI 参与 | 说明 |
|---|---|---|
| 需求拆解 | 是 | 把题目转成验收点表（docs/01）|
| 数据结构设计 | 是 | 讨论出 fingerprint 幂等方案 |
| 代码实现 | 是 | src/ 全部初稿由 AI（Claude Code）生成 |
| 决策边界设计 | 是 | missing/violation 区分、hard 保护 |
| 测试编写 | 是 | tests/ 由 AI 生成 |
| 运行验证 | 是 | 本地实际执行，见下 |
| 文档撰写 | 是 | docs/ 由 AI 生成 |

## 个人修改与把关

在 AI 生成的基础上，做了以下**人工判断与修改**（这些是 AI 初稿没有的）：

1. **状态语义修正**：AI 初稿里"草稿已保存但有冲突"仍返回 `draft_saved`，掩盖了待确认项。
   人工要求拆出 `needs_confirm`，把"保存"和"确认"两件事解耦。
2. **信息缺失独立成态**：AI 初稿把字段缺失和规则违规都归为 `blocked`。
   人工要求区分 `needs_more_info`，因为二者业务动作不同（请求补充 vs 阻断）。
3. **保存失败独立成态**：从 `blocked` 拆出 `save_failed`，避免"规则拦截"与"存储故障"混淆，
   满足题目"保存失败须明确返回失败"。
4. **live 路径真实性验证**：不接受"能调通就行"，要求起本地 mock server 验证 HTTP 契约。
5. **删除冗余兜底**：AI 初稿在 `_latest_material` 有一处无用兜底（读空列表），人工发现逻辑死代码。

## 验证记录

- `python -m unittest discover -s tests -v` → 11 passed（本地实跑）
- `python examples/generate_traces.py` → 8 组 Trace 落盘（本地实跑）
- `python examples/verify_live_path.py` → HTTP 契约通过（本地实跑）
- 人工逐份核对 `examples/trace_*.json` 的决策链是否合理

## 边界声明

- 默认离线 Mock 为 AI 生成的确定性规则器，**不代表真实 LLM 决策质量**。
- 真实模型能力需配置 `MODEL_BASE_URL/API_KEY/NAME` 后实测，本次未接真实付费模型。
- 所有合成数据由 AI 生成，无真实用户隐私。
