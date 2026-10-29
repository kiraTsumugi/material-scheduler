# 交付说明 · 素材审核与发布排期 Agent

## 提交信息

| 项 | 内容 |
|---|---|
| 题号 | 素材审核与发布排期 Agent（项目题四选一） |
| GitHub URL | https://github.com/kiraTsumugi/material-scheduler |
| 分支 | `main` |
| 最终 commit SHA | `cdbe40efb908cf68ea7712066ccfcc7639ca2c7f` |
| 运行方式 | CLI |
| 依赖 | 零第三方依赖，Python ≥ 3.10 |

> 若后续对 commit 做了 `amend`（如改作者身份）或新增提交，请回填上表的 **SHA**。

## 一句话概述

面向内容团队的发布排期助手：模型驱动的 ReAct 循环读素材、查规则、查时段、存草稿，
产出**无冲突、可确认**的排期**草稿**；只存草稿不发布，硬性发布时间要求受保护。

## 评审入口（先看这里）

```bash
cd material-scheduler

# 冲突消解全过程：每一步「动作 → 参数 → 决策依据」
python -m src.main M01 --time 18:00 -v

# 全量测试
python -m unittest discover -s tests -v
```

预期：M01 请求 18:00（已被占用）→ 模型建议 19:00 → 状态 `needs_confirm`（**不是**"已发布"）。

## 需求映射（验收点 → 证据）

| 验收点 | 命令 | 状态 | 证据文件 |
|---|---|---|---|
| 正常排期 | `python -m src.main M02 --time 10:00` | `draft_saved` | `examples/trace_normal.json` |
| 时段冲突 | `python -m src.main M01 --time 18:00` | `needs_confirm` | `examples/trace_slot_conflict.json` |
| 硬性要求冲突 | `python -m src.main M05 --time 20:00` | `needs_confirm`，**0 草稿** | `examples/trace_hard_conflict.json` |
| 素材信息缺失 | `python -m src.main M03` | `needs_more_info` | `examples/trace_missing_info.json` |
| 规则风险 | `python -m src.main M04` | `blocked` | `examples/trace_rule_risk.json` |
| 保存失败 | `python -m src.main M06 --time 14:00` | `save_failed` | `examples/trace_save_failed.json` |
| 重复提交 | 同请求连跑两次 | 只 1 份草稿 | `examples/trace_duplicate.json` |
| 步数上限 | 强制循环模型 | `incomplete` | `tests/test_agent.py::TestStepLimit` |
| 畸形模型输出 | 非 dict/未知动作/绕过读素材 | 不崩溃 | `tests/test_agent.py::TestMalformedModelOutput` |

## 核心思路（文件里放不下的取舍）

### 1. 工具返回事实，决策权 100% 归模型
`src/agent/tools.py` 的四个工具**只返回事实**：素材原始字段（可能缺）、触发的规则列表、
时段占用情况、保存结果。工具**不判断**"该不该发、要不要改时段"。
于是代码主干里没有 `if 冲突 then 改时段` 这类硬分支——分支在模型里，由工具事实驱动。
**同一段循环代码，因 `query_slots` 返回不同而走出不同决策**，这才是有效的 ReAct。

### 2. 用数据结构消除特殊情况
- **幂等**：`Draft.fingerprint = hash(material_id | requested_time)`，`DraftStore` 以它为键。
  重复提交天然只产生一份草稿——不需要扫描比对、不需要额外去重代码。
- **状态正交**：把"已保存/待确认/资料不足/被阻断/保存失败/未完成"拆成 6 个独立状态码。
  最初只有一个"成功"状态，会掩盖"待确认"——这是本题最大的语义陷阱。

### 3. 硬性要求保护是硬约束，不是提示词
`publish_requirement.level == "hard"` 时，冲突分支**只允许** `finish(needs_confirm)`，
**禁止** `save_draft` 替代时段。约束同时写进 SYSTEM_PROMPT（约束真实模型）与
OfflineMock（约束离线路径）——双重保险，且测试断言"此场景草稿数=0"。

### 4. 为什么不用框架
LangGraph / ADK 等在本例只提供循环骨架，与 30 行原生循环相比无增益，反而引入依赖和
理解成本。**能解释取舍比用不用框架重要**，故原生实现。

### 5. Mock 与真实模型同构
`ModelClient.decide(system, messages) -> action` 是唯一接口。离线 Mock（确定性规则器）
消费对话历史里的工具事实、产出同构动作，因此**切换后端不改循环代码**。
live 路径用标准库 `urllib` 直连任意 OpenAI 兼容端点，`examples/verify_live_path.py`
用本地 mock server 验证了 HTTP 契约（payload / Bearer 鉴权 / JSON 解析）。

## 已知限制（诚实声明）

1. **默认离线 Mock 不代表真实 LLM 决策质量**——只验证流程与决策边界。真实模型能力需配置
   `MODEL_BASE_URL / MODEL_API_KEY / MODEL_NAME` 后实测（本次未接真实付费模型）。
2. **并发**：`DraftStore` 为进程内内存，多进程并发下不保证幂等（考核范围外）；
   fingerprint 方案可平滑迁移到带唯一索引的持久层。
3. **单日排期**：仅合成数据日期 `2026-11-01`，其他日期返回"无排期数据"。
4. **规则引擎**仅支持 `le / eq / exists / nonempty` 四种算子，覆盖验收场景。

## 目录导览

```
README.md              环境/安装/运行/评审入口
SUBMISSION.md          本文件（交付说明）
BRIEF.md               实现前说明（10 行内）
src/agent/             models / tools / llm / react_loop
src/main.py            CLI 入口
tests/test_agent.py    11 项测试，覆盖全部验收点
examples/              Trace + CLI 输出 + INDEX + 生成脚本 + live 验证脚本
data/                  合成素材/排期/规则（含说明 README）
docs/01-requirements.md    需求与验收标准
docs/02-solution.md        调用流程、动态决策、技术取舍
docs/03-evaluation.md      测试预期/实际结果/失败与限制
docs/04-ai-usage.md        AI 辅助范围、个人修改、验证记录
docs/05-retrospective.md   最难问题、学习收获、下一步
```

## AI 使用摘要（详见 docs/04）

代码与文档初稿由 AI（Claude Code）生成；人工把关修正了：状态语义拆分（needs_confirm /
needs_more_info / save_failed 从单一"成功"中解耦）、删除 `_latest_material` 死代码、
要求 live 路径起 server 实证。所有数据为合成，无真实隐私或密钥。
