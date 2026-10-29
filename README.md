# 素材审核与发布排期 Agent

面向内容团队的发布排期助手：找出待处理素材，做审核规则检查与时段冲突消解，产出一份**无冲突、可确认**的发布排期**草稿**。只保存草稿，不接真实发布。

模型驱动 ReAct 循环：**模型选动作 → 执行工具 → 观察结果 → 模型调整下一步或结束**。硬性发布时间要求受保护，冲突时请求确认而非擅自更改。

## 快速开始

无需任何第三方依赖（纯标准库），Python ≥ 3.10。

```bash
# 1. 正常排期：请求时段空闲
python -m src.main M02 --time 10:00

# 2. 时段冲突：18:00 被占用 → 建议 19:00 并标记待确认
python -m src.main M01 --time 18:00 -v

# 3. 硬性要求冲突：20:00 被占且 level=hard → 不擅自改，请求确认
python -m src.main M05 --time 20:00 -v

# 4. 信息缺失：缺字段 → 请求补充
python -m src.main M03

# 5. 规则风险：时长超限 → 阻断
python -m src.main M04

# 6. 保存失败：后端故障注入 → 明确返回失败
python -m src.main M06 --time 14:00

# JSON 输出 / 落盘 trace
python -m src.main M01 --time 18:00 --json
python -m src.main M01 --time 18:00 --trace examples/trace_out.json
```

**评审入口**：`python -m src.main M01 --time 18:00 -v` 会打印每一步的 `动作 → 参数 → 决策依据`，即完整 ReAct Trace。

## 运行模式

- **离线 Mock（默认，无 key 时自动）**：确定性决策，消费工具返回的事实。`--offline` 强制。
  边界：Mock 只验证**流程与决策边界**，不证明真实模型的决策能力。
- **真实模型**：任意 OpenAI 兼容端点。设置环境变量后自动启用：
  ```bash
  export MODEL_BASE_URL=https://api.openai.com/v1
  export MODEL_API_KEY=sk-...
  export MODEL_NAME=gpt-4o-mini
  python -m src.main M01 --time 18:00 -v
  ```

## 测试

```bash
python -m unittest discover -s tests -v        # 11 项测试，覆盖全部验收点
python examples/generate_traces.py             # 重新生成 examples/ 运行记录
python examples/verify_live_path.py            # 验证真实模型 HTTP 接入路径契约
```

## 决策模型

| 工具事实 | 模型动作 | 最终状态 |
|---|---|---|
| 时段空闲 | save_draft | `draft_saved` |
| 时段被占 + soft | save_draft(替代时段) | `needs_confirm` |
| 时段被占 + hard | finish | `needs_confirm`（不改时段）|
| 字段缺失 | finish | `needs_more_info` |
| 规则 block 违规 | finish | `blocked` |
| 保存失败 | finish | `save_failed` |
| 步数超限 | abort | `incomplete` |

## 目录

```
src/agent/        核心：models / tools / llm / react_loop
src/main.py       CLI 入口
tests/            可执行测试
examples/         运行记录（Trace + CLI 输出）+ 生成脚本
data/             合成素材 / 排期 / 规则
docs/             01~05 设计文档
BRIEF.md          实现前说明
```

详见 [docs/01-requirements.md](docs/01-requirements.md) 起的设计文档。
