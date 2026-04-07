# webreader 页面提取与结构化 review

目标：读取 `webreader-review-input.json` 的候选页面，从正文提取 POI 关键信息并输出结构化 review seed。

输出要求：

- 顶层输出 JSON 对象：`{"items": [...]}`
- 每个 item 必须包含：
  - `result_id`
  - `is_relevant`
  - `confidence`
  - `reason`
  - `source_type`
  - `existence_status`
  - `extracted`
- 必须覆盖输入中的每一条 `review_items`
- `existence_status` 只允许：
  - `active`
  - `changed`
  - `merged`
  - `revoked`
  - `unknown`

提取重点：

- 提取 `name`、`address`、`phone`、`category`
- 可补充 `status`、`level`、`email`
- 判断是否存在“迁址、归并、撤销、变更”类信号
- 页面明显无关时，`is_relevant=false`，并在 `reason` 写明原因

质量要求：

- 不确定的信息不要编造
- 仅从页面内容中提取，不做主观推断
- `is_relevant=true` 时，`extracted.name` 必须有值
