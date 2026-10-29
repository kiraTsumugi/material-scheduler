# 02 · 方案

## 调用流程

```
用户意图(素材ID, 期望时段)
      │
      ▼
┌─────────────────────────────────────────┐
│ ReAct 循环 (src/agent/react_loop.py)     │
│  模型 decide() ──► 动作                    │
│      │                                     │
│      ├─ read_material  ──► 素材事实         │
│      ├─ check_rules    ──► 规则事实         │
│      ├─ query_slots    ──► 时段事实         │
│      ├─ save_draft     ──► 保存结果(幂等)   │
│      └─ finish         ──► 结束             │
│      ▲                    │                │
│      └── 观察结果喂回 ◄────┘                │
│  步数上限 8 → 超限 status=incomplete        │
└─────────────────────────────────────────┘
```

## 动态决策（ReAct 的核心）

**工具只返回事实，决策权 100% 归模型。** 这是"消除特殊情况"的体现：代码里没有
`if 冲突 then 改时段` 这类硬分支；分支在**模型**里，且由工具事实驱动。

两条典型路径因工具结果不同而分叉：

- **路径 A（空闲）**：`read → check_rules(空) → query_slots(10:00空闲) → save_draft(10:00) → finish(draft_saved)`
- **路径 B（冲突）**：`read → check_rules(空) → query_slots(18:00被占) → save_draft(19:00, conflict_resolved) → finish(needs_confirm)`

同一段循环代码，因 `query_slots` 的事实不同，模型在 step 4 做了不同决策。见 `examples/`。

## 关键设计取舍

### 1. 幂等键放进数据结构，而非额外去重逻辑
`Draft.fingerprint = hash(material_id | requested_time)`。`DraftStore` 以 fingerprint 为键 →
**重复提交天然只产生一份草稿**，无需扫描比对。数据结构消除特殊情况。

### 2. 硬性要求保护
`publish_requirement.level == "hard"` 时，模型在冲突分支只允许 `finish(needs_confirm)`，
禁止 `save_draft` 替代时段。约束同时写进 SYSTEM_PROMPT（对真实模型）与 OfflineMock（对离线）。

### 3. 区分「信息缺失」与「内容违规」
`check_rules` 给每个问题打 `kind: missing|violation`：
- `missing` → `needs_more_info`（请求补充，不阻断）
- `violation` → `blocked`（阻断）
二者对应不同决策，故在**事实层**就区分开。

### 4. 零依赖
环境无第三方 HTTP 库，故用标准库 `urllib` 直连 OpenAI 兼容端点。框架（LangGraph 等）
在本例只提供循环骨架，与 30 行循环相比无增益，且引入依赖——**不引入**。

### 5. Mock 与真实模型同构
`ModelClient.decide(system, messages) -> action dict` 是唯一接口。OfflineMock 消费对话里的
工具事实产出同样结构的动作。因此切换后端不改循环代码；Mock 覆盖**决策边界**的验证，
真实模型覆盖**语言理解**能力。

## 技术栈

- Python 3.12，标准库 only（无 requirements 依赖，见 `requirements.txt` 说明）
- 模型：OpenAI 兼容 `/chat/completions`（`response_format=json_object`）
