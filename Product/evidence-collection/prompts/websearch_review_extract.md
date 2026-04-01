# websearch 结果相关性判断与结构化抽取

目标：读取 `websearch-review-input.json` 中的候选结果，判断是否与目标 POI 相关，并直接产出可落盘的结构化抽取 seed。

输出要求：

- 顶层输出 JSON 对象：`{"items": [...]}`
- 每个 item 必须包含：
  - `result_id`
  - `is_relevant`
  - `confidence`
  - `reason`
  - `source_type`
  - `evidence_ready`
  - `should_fetch`
  - `fetch_url`
  - `extracted`
- `extracted` 内允许输出：
  - `name`
  - `address`
  - `phone`
  - `email`
  - `category`
  - `category_hint`

判断原则：

- 先判断该搜索结果是否真的在描述目标 POI，而不是泛门户、新闻噪音或无关页面
- 能从标题、摘要中直接确定的字段就直接抽取
- 不确定的字段留空，不要编造
- 如果摘要已经足以形成结构化结果，则 `evidence_ready=true`
- 只有当页面明显还有更完整信息可抓取时，才设置 `should_fetch=true`
- `webfetch` 是增强层，不是当前 item 成立的前提；即使 `should_fetch=true`，当前 item 仍要给出可用的结构化结果
