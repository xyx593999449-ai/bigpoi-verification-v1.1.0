# 图商候选相关性判断

目标：针对单个图商分支的候选列表，判断哪些候选与输入 POI 真实相关，仅输出结构化 review seed。

输出要求：

- 顶层输出 JSON 对象
- 使用 `vendors -> vendor -> candidate_decisions` 结构
- 每条 `candidate_decisions` 必须包含：
  - `candidate_key`
  - `is_relevant`
  - `reason`

判断原则：

- 优先看名称是否高度一致或仅存在行政区补全、省市前缀差异
- 再看地址、坐标、行政区是否明显相符
- 连锁分店、周边办事点、政务服务页、景点页不要误判为目标 POI
- 无法确认时默认 `is_relevant=false`
