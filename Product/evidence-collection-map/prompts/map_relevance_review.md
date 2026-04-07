# 图商候选相关性判断

目标：针对 `map-review-input.json` 中单个或多个图商分支的候选卡片，判断哪些候选与输入 POI 真实相关，仅输出结构化 review seed。

输出要求：

- 顶层输出 JSON 对象
- 使用 `vendors -> vendor -> candidate_decisions` 结构
- 每条 `candidate_decisions` 必须包含：
  - `candidate_key`
  - `is_relevant`
  - `reason`
- 必须覆盖输入中的每一条候选，逐条输出判断
- 不要只输出 `keep_candidates`
- 不要输出 `auto_generated`、`fallback` 一类兜底状态

判断原则：

- 优先看名称是否高度一致或仅存在行政区补全、省市前缀差异
- 再看地址、坐标、行政区是否明显相符
- 连锁分店、周边办事点、政务服务页、景点页不要误判为目标 POI
- `北门`、`西门`、`停车场`、`社区活动中心`、`居民小组`、`征兵办公室` 这类附属点位或下属机构，默认不等于输入 POI 本体
- 无法确认时默认 `is_relevant=false`
