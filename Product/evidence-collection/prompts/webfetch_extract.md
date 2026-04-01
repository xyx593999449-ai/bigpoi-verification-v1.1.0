# webfetch 页面理解与补强抽取

目标：针对 `webfetch` 抓取到的高价值页面，补充 `websearch-reviewed` 中不稳定或缺失的字段。

输出要求：

- 顶层输出 JSON 对象：`{"items": [...]}`
- 每个 item 必须包含：
  - `fetch_id`
  - `source_url`
  - `is_relevant`
  - `confidence`
  - `reason`
  - `enhances_result_id`
  - `extracted`

判断原则：

- 只补强页面能明确支持的字段
- 对已有高置信字段不要随意覆盖
- 页面无关或抓取失败时，返回空数组或不相关结果，不得阻断 `websearch-reviewed` 的下游执行
