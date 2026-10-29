# data/ 说明

全部为**合成数据**，不含任何真实用户隐私或密钥。

| 文件 | 内容 |
|---|---|
| `materials.json` | 素材库。每个素材含 `metadata`（type/duration_sec/category/tags/copyright）与 `publish_requirement {time, level}`。`level`: `hard`=硬性要求（不可擅自改），`soft`=可协商。 |
| `schedule.json` | 目标日期排期：`all_slots` 全部时段、`occupied` 已占用时段（键=时段，值=占用素材 ID）。`_fail_save_injection` 为故障注入列表。 |
| `rules.json` | 审核规则表。算子：`le` / `eq` / `exists` / `nonempty`；`severity`: `block` / `warn`。 |

## 素材与验收场景映射

| 素材 | 特征 | 覆盖场景 |
|---|---|---|
| M01 | 无风险，默认 18:00 但被占 | 时段冲突(soft) / 重复提交 |
| M02 | 无风险，10:00 空闲 | 正常排期 |
| M03 | 缺 category/copyright/duration_sec | 信息缺失 |
| M04 | duration 180s | 规则风险(阻断) |
| M05 | 20:00 + level=hard，且被占 | 硬性要求冲突 |
| M06 | 14:00 空闲，但在故障注入名单 | 保存失败 |
| M07 | **不存在**（用 MX9 测试）| 素材不存在 |

## 故障注入

`schedule.json._fail_save_injection` 列出的素材，`save_draft` 会返回失败，
用于验证"保存失败须明确返回"这一验收点（M06）。
