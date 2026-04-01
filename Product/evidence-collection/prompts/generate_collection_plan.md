# 证据收集执行计划生成

目标：围绕单个输入 POI，生成计划驱动的 `collection-plan.json`。

要求：

- 只使用预定义节点，不要发明脚本名或路径
- 计划中明确区分 `script`、`model`、`gate`
- `websearch` review 必须先于 `webfetch`
- `merge` 只能消费 reviewed 文件
- `webfetch` 失败时，允许继续使用 `websearch-reviewed`

最少应包含：

- 图商 raw 节点
- 图商 review 节点
- websearch raw 节点
- websearch review 节点
- webfetch gate 或 fallback 说明
- merge 节点
- formal evidence 节点
