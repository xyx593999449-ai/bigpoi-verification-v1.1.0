---
name: evidence-collection
description: 面向大 POI 核实流程的证据收集子技能。用于并行执行图商代理、权威网站检索和互联网检索，并且必须通过脚本完成缺失图商补采、证据规范化和正式 `evidence_*.json` 文件写入。适用于父技能需要一个稳定、可回放、严格落盘的 evidence 文件时；本技能不得输出最终核实结论或入库记录。
---

# Evidence Collection

## Core rule

本技能的唯一正式产物是 `evidence_*.json` 文件路径。

只有完成相关性初筛、归并和规范化之后的最终证据文件，才能命名为 `evidence_*.json`，并且内容必须满足下游已联调的正式 evidence 规格。

所有原始结果和过程文件都只能作为过程产物输出到 `output/` 下，且必须使用过程命名，不能伪装成正式 evidence 文件，也不能被父技能写入最终 `index_*.json`。

不要输出：

- 自由格式的证据摘要代替正式文件
- `decision_*.json`
- `record_*.json`
- 只在上下文里展示证据数组而不落盘
- 直接把 `websearch` 或 `webfetch` 的自然语言结果交给父技能

## Use bundled scripts

必须使用以下脚本：

- `evidence-collection/scripts/build_web_source_plan.py`
- `evidence-collection/scripts/call_internal_proxy.py`
- `evidence-collection/scripts/call_map_vendor.py`
- `evidence-collection/scripts/merge_evidence_collection_outputs.py`
- `evidence-collection/scripts/write_evidence_output.py`

## Inputs

正式输入分三类：

- 输入 POI 文件：遵循 `skills-bigpoi-verfication/schema/input.schema.json`
- `websearch` / `webfetch` 分支的原始 JSON 文件
- 缺失图商补采的原始 JSON 文件

固定约束：

- 内部图商代理脚本只接受 `city + poi name`，并固定同时请求 `amap`、`bmap`、`qmap`
- 图商直连脚本固定接受 `city + poi name + source`，默认从 `evidence-collection/config/common.yaml` 读取对应图商凭证；只有需要覆盖时才显式传 `credential`
- 只有在内部图商代理的 `missing_vendors` 非空时，才允许调用图商直连脚本

## Parallel workflow

1. 读取输入 POI 文件。
2. 生成权威网站和互联网检索计划。该脚本会先通过 `skills-bigpoi-verfication/config/poi_type_mapping.yaml` 把 6 位 `poi_type` 映射为类目，再读取对应类型配置：

```bash
python evidence-collection/scripts/build_web_source_plan.py -PoiPath <input.json> -OutputPath <web-plan.json>
```

3. 并行执行三个分支：

- 内部图商代理分支：

```bash
python evidence-collection/scripts/call_internal_proxy.py -PoiName <poi-name> -City <city> -OutputPath <internal-proxy.json>
```

- `websearch` 分支：根据 `web-plan.json` 中的 `official_sources` 与 `internet_sources` 执行搜索，并把结果保存成 JSON 文件。
- `webfetch` 分支：优先抓取 `mode = direct_fetch` 的站点；若 `mode = search_first`，先从 `websearch` 命中中挑选权威页面再抓取，并把结果保存成 JSON 文件。

原始和过程文件命名约束：

- 图商原始结果：`map-raw-<branch>-<timestamp>.json`
- 图商初筛结果：`map-reviewed-<branch>-<timestamp>.json`
- `websearch` 原始结果：`websearch-raw-<timestamp>.json`
- `webfetch` 原始结果：`webfetch-raw-<timestamp>.json`
- 归并中间结果：`collector-merged-<timestamp>.json`

这些文件都属于过程文件：

- 可以存放在 `output/` 下的过程目录中
- 不能命名为 `evidence_*.json`
- 不能写入最终 `index_*.json`

4. 检查 `internal-proxy.json` 的 `missing_vendors`。只有缺失图商才允许补采，每个缺失图商单独执行一次：

```bash
python evidence-collection/scripts/call_map_vendor.py -PoiName <poi-name> -City <city> -Source <amap|bmap|qmap> -OutputPath <vendor-fallback.json>
```

5. 所有分支完成后，先归并再规范化：

```bash
python evidence-collection/scripts/merge_evidence_collection_outputs.py -PoiPath <input.json> -InternalProxyPath <internal-proxy.json> -WebSearchPath <websearch.json> -WebFetchPath <webfetch.json> -VendorFallbackPaths <vendor-a.json> <vendor-b.json> -OutputPath <merged-collector-output.json>
```

6. 运行正式写入脚本，把归并结果落成最终证据文件：

```bash
python evidence-collection/scripts/write_evidence_output.py -PoiPath <input.json> -CollectorOutputPath <merged-collector-output.json> -OutputDirectory <staging-dir>
```

7. 只把脚本返回的 `evidence_path` 交给父技能或 `verification` 子技能。

## Raw branch contract

`websearch` 和 `webfetch` 分支必须输出 JSON 文件，允许两种顶层结构：

- 证据数组
- 含 `evidence_list`、`items` 或 `records` 的对象

每条 item 至少要能归并出：

- `source.source_name`
- `source.source_type`
- `data.name`

推荐直接输出 evidence-like item：

```json
{
  "source": {
    "source_name": "国家卫健委",
    "source_type": "official",
    "source_url": "https://www.nhc.gov.cn/"
  },
  "data": {
    "name": "北京大学第一医院",
    "address": "北京市西城区西什库大街8号"
  }
}
```

## Output contract

正式证据文件必须：

- 文件名为 `evidence_<timestamp>.json`
- 文件内容为最终初筛并规范化后的证据数组
- 每个 item 满足 `skills-bigpoi-verfication/schema/evidence.schema.json` 的 item 结构
- `poi_id` 必须与输入 `id` 一致

过程文件必须：

- 不使用 `evidence_*.json`、`decision_*.json`、`record_*.json`、`index_*.json` 这类正式命名
- 不作为最终交付物返回给父技能
- 不进入父技能最终索引

## Failure handling

若 `merge_evidence_collection_outputs.py` 失败，说明至少有一个分支结果缺字段、结构不对，或与输入 POI 绑定关系不一致。

此时必须：

1. 回到失败分支重新生成 JSON 文件
2. 重新执行归并脚本
3. 重新运行 `write_evidence_output.py`
4. 只返回新的 `evidence_path`

不要：

- 手工拼接证据数组绕过脚本
- 在内部图商已有结果时仍然补采同图商
- 把 `websearch` / `webfetch` 的自然语言结论直接交给 `verification`

## References to load only when needed

仅在需要时读取：

- `skills-bigpoi-verfication/schema/input.schema.json`
- `skills-bigpoi-verfication/schema/evidence.schema.json`
- `skills-bigpoi-verfication/config/poi_type_mapping.yaml`
- `evidence-collection/config/common.yaml`
- `evidence-collection/config/{resolved-category}.yaml`




