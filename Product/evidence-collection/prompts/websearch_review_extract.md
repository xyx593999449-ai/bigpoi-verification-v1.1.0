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
  - `entity_relation`
  - `evidence_ready`
  - `should_read`
  - `read_url`
  - `extracted`
- 必须覆盖输入中的每一条 `review_items`
- 不允许把所有结果统一判成 `true`
- 不允许输出 `auto_generated` 或“兜底全保留”风格的 seed
- `extracted` 内允许输出：
  - `name`
  - `address`
  - `phone`
  - `email`
  - `category`
  - `category_hint`

判断原则：

- 先判断该搜索结果是否真的在描述目标 POI 本体，而不是泛门户、新闻噪音、站点导航、下属机构或无关页面
- 必须先给出 `entity_relation`，只允许以下枚举值：
  - `poi_body`：页面主体就是目标 POI 本体，或该机构直接发布/对应的正式记录页面，可直接作为正式 evidence
  - `subordinate_org`：页面主体是目标 POI 的下属机构、服务中心、办公室、居委会、工作站等
  - `same_region`：页面主体是同名行政区、街道区域、地理百科或辖区介绍，不是目标 POI 本体
  - `mention_only`：页面主体不是目标 POI，只是在导航栏、正文列表、招录单位名单、友情链接、页脚等位置顺带提到
  - `unrelated`：与目标 POI 无关
- 只有 `entity_relation=poi_body` 时，才允许 `is_relevant=true`
- 对官方来源，以下页面通常应判为 `poi_body`：
  - 页面标题直接包含目标机构全称或稳定简称
  - 目标机构自己的政府信息公开页、年度报告页、机构概况页、依申请公开页、办事指南页
  - 明确以目标机构为发布主体或办理主体的正式记录页面
- 即使页面是“工作总结 / 年度报告 / 政府信息公开 / 依申请公开系统 / 招录用人单位详情”，只要页面主体明确对应目标机构本体，也应判为 `poi_body`
- 如果标题只是新闻、专题、职位公告、门户导航页，但正文仅顺带提到目标 POI，必须判为 `entity_relation=mention_only` 且 `is_relevant=false`
- 如果页面描述的是下属机构、社会组织服务中心、居委会、征兵办公室、服务站、停车场、出入口等，必须判为 `subordinate_org` 且 `is_relevant=false`
- 如果页面描述的是“西丽街道”这类行政区/街道区域，而不是“西丽街道办事处”本体，必须判为 `same_region` 且 `is_relevant=false`
- 如果只是门户站点新闻页、活动页、专题页、宣传页的正文或导航里列出目标机构名称，而页面主体不是该机构本体，则仍然必须判为 `mention_only`
- 能从标题、摘要中直接确定的字段就直接抽取
- 不确定的字段留空，不要编造
- 如果摘要已经足以形成结构化结果，且 `entity_relation=poi_body`，则 `evidence_ready=true`
- 只有当页面明显还有更完整信息可抓取时，才设置 `should_read=true`
- `webreader` 是增强层，不是当前 item 成立的前提；即使 `should_read=true`，当前 item 仍要给出可用的结构化结果
- 当 `is_relevant=true` 时，`extracted.name` 必须有值，且 `evidence_ready=true`
