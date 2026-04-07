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
- 直接把 `websearch` 或 `webreader` 的自然语言结果交给父技能

当前术语说明：

- `websearch`：按 `query` 走内部搜索代理，收集候选网站、标题、摘要与候选 URL
- `webfetch`：当前仓库中的旧命名，业务上表示“页面增强层”
- `webreader`：后续拟替换 `webfetch` 的内部代理，按指定 `url` 读取页面信息

## Use bundled scripts

Use the following executable entry scripts:

- `evidence-collection/scripts/build_web_source_plan.py`
- `evidence-collection/scripts/websearch_adapter.py`
- `evidence-collection/scripts/call_internal_proxy.py`
- `evidence-collection/scripts/call_map_vendor.py`
- `evidence-collection/scripts/prepare_map_review_input.py`
- `evidence-collection/scripts/prepare_websearch_review_input.py`
- `evidence-collection/scripts/build_webreader_plan.py`
- `evidence-collection/scripts/webreader_adapter.py`
- `evidence-collection/scripts/prepare_webreader_review_input.py`
- `evidence-collection/scripts/validate_webreader_review_seed.py`
- `evidence-collection/scripts/write_webreader_review.py`
- `evidence-collection/scripts/validate_map_review_seed.py`
- `evidence-collection/scripts/validate_websearch_review_seed.py`
- `evidence-collection/scripts/write_map_relevance_review.py`
- `evidence-collection/scripts/write_websearch_review.py`
- `evidence-collection/scripts/build_webfetch_plan.py`
- `evidence-collection/scripts/merge_evidence_collection_outputs.py`
- `evidence-collection/scripts/write_evidence_output.py`

The following files are local helper modules for internal `import` only. Do not execute them directly:

- `evidence-collection/scripts/run_context.py`
- `evidence-collection/scripts/evidence_collection_common.py`
## Inputs

- 所有过程 JSON 文件必须位于 `output/runs/{run_id}/process/` 或 `output/runs/{run_id}/staging/`
- 所有可被脚本消费的中间 JSON 都必须绑定本次 `run_id`、`poi_id`与 `created_at`

正式输入分三类：

- 输入 POI 文件：遵循 `skills-bigpoi-verification/schema/input.schema.json`
- `websearch` / `webreader` 分支的原始 JSON 文件或 reviewed JSON 文件
- 缺失图商补采的原始 JSON 文件

职责边界补充：

- `websearch` 负责“找候选页面”，不是页面正文读取器
- 当前 `webfetch` 所在位置后续应由 `webreader` 接管
- 图商线与 `websearch/webreader` 线是并行关系，不是替换关系

固定约束：

- 内部图商代理脚本只接受 `city + poi name`，并固定同时请求 `amap`、`bmap`、`qmap`
- 图商直连脚本固定接受 `city + poi name + source`，默认从 `evidence-collection/config/common.yaml` 读取对应图商凭证；只有需要覆盖时才显式传 `credential`
- 只有在内部图商代理的 `missing_vendors` 非空时，才允许调用图商直连脚本

仅在需要时读取以下提示词文件：

- `evidence-collection/prompts/generate_collection_plan.md`
- `evidence-collection/prompts/map_relevance_review.md`
- `evidence-collection/prompts/websearch_review_extract.md`
- `evidence-collection/prompts/webfetch_extract.md`
- `evidence-collection/prompts/webreader_extract.md`

## Preferred workflow

优先采用“计划驱动 + reviewed gate”的流程，而不是把 raw 结果直接写进 formal evidence。

### 1. 生成 collection todo / plan

- 先根据输入 POI 生成本次采集 todo，明确：
  - 哪些脚本节点要执行
  - 哪些模型节点要执行
  - 每个节点的输入文件、输出文件和落盘路径
  - `webreader` 是否需要执行
  - 当 `webreader` 失败时如何 fallback 到 `websearch-reviewed`

补充说明：

- 当前 todo 中的 `webfetch` 位置，后续应统一替换为 `webreader`
- 该替换只影响页面增强层，不影响前面的 `websearch` 搜索发现层

### 2. 执行 raw 采集

- 图商 raw：

- `build_web_source_plan.py`

```bash
python evidence-collection/scripts/call_internal_proxy.py -PoiName <poi-name> -City <city> -PoiId <poi-id> -TaskId <task-id> -RunId <run-id> -OutputPath <output/runs/{run_id}/process/map-raw-internal-proxy.json>
```

- `websearch` raw：

```bash
python evidence-collection/scripts/build_web_source_plan.py -PoiPath <input.json> -OutputPath <web-plan.json>
python evidence-collection/scripts/websearch_adapter.py -WebPlanPath <web-plan.json> -OutputPath <output/runs/{run_id}/process/websearch-raw.json> -PoiId <poi-id> -TaskId <task-id> -RunId <run-id>
```

### 3. 模型执行 review 节点

- 图商线：
  1. 先运行：

```bash
python evidence-collection/scripts/prepare_map_review_input.py -PoiPath <input.json> -RawMapPath <map-raw.json> -OutputPath <map-review-input.json> -RunId <run-id> -TaskId <task-id>
```

  2. 必须让子 agent / Task 只读取 `map-review-input.json`，按 `prompts/map_relevance_review.md` 输出 `map-review-seed.json`
  3. 必须运行：

```bash
python evidence-collection/scripts/validate_map_review_seed.py -MapReviewInputPath <map-review-input.json> -ReviewSeedPath <map-review-seed.json>
```

  4. 校验通过后再运行：

```bash
python evidence-collection/scripts/write_map_relevance_review.py -RawMapPath <map-raw.json> -ReviewSeedPath <map-review-seed.json> -OutputPath <output/runs/{run_id}/process/map-reviewed.json> -PoiId <poi-id> -TaskId <task-id> -RunId <run-id>
```

- `websearch` 线：
  1. 先运行：

```bash
python evidence-collection/scripts/prepare_websearch_review_input.py -PoiPath <input.json> -WebSearchRawPath <websearch-raw.json> -OutputPath <websearch-review-input.json> -RunId <run-id> -TaskId <task-id>
```

  2. 必须让子 agent / Task 读取 `websearch-review-input.json`，按 `prompts/websearch_review_extract.md` 输出 `websearch-review-seed.json`
  3. 必须运行：

```bash
python evidence-collection/scripts/validate_websearch_review_seed.py -WebSearchReviewInputPath <websearch-review-input.json> -ReviewSeedPath <websearch-review-seed.json>
```

  4. 校验通过后再运行：

```bash
python evidence-collection/scripts/write_websearch_review.py -WebSearchRawPath <websearch-raw.json> -ReviewSeedPath <websearch-review-seed.json> -OutputPath <output/runs/{run_id}/process/websearch-reviewed.json> -PoiId <poi-id> -TaskId <task-id> -RunId <run-id>
```

强约束：

- `map-review-seed.json` 与 `websearch-review-seed.json` 不能使用 `auto_generated` 或统一兜底全保留结果
- 图商 review 必须逐条覆盖所有候选，不允许只给 `keep_candidates`
- `websearch-reviewed.json` 必须已经是可直接归并的结构化结果
- `websearch` 相关条目若 `is_relevant=true`，则必须已经有 `extracted.name`
- `websearch` review 必须显式给出 `entity_relation`
- 只有 `entity_relation=poi_body` 的 `websearch` 结果才允许进入 formal evidence
- `mention_only / subordinate_org / same_region` 这类弱相关结果必须在 review 阶段剔除
- `webreader` 只做增强，不是 `websearch-reviewed` 成立的前置条件
- 如果 `webreader` 失败，必须继续使用 `websearch-reviewed` 往后执行

原始和过程文件命名约束：

- 图商原始结果：`map-raw-<branch>-<timestamp>.json`
- 图商初筛结果：`map-reviewed-<branch>-<timestamp>.json`
- `websearch` 原始结果：`websearch-raw-<timestamp>.json`
- `websearch` 调试日志：`websearch-debug-<timestamp>.json` 或 `websearch-debug.json`
- `webreader` 原始结果：`webreader-raw-<timestamp>.json`
- 归并中间结果：`collector-merged-<timestamp>.json`

这些文件都属于过程文件：

- 可以存放在 `output/` 下的过程目录中
- 不能命名为 `evidence_*.json`
- 不能写入最终 `index_*.json`
### 4. 对图商原始结果执行相关性初筛

内部代理结果和每个补采图商结果都必须先由模型完成候选保留/剔除判断，再通过以下脚本写成 reviewed JSON；未被明确保留的候选默认剔除，不允许直接把 query 原始结果送入归并。

```bash
python evidence-collection/scripts/write_map_relevance_review.py -RawMapPath <map-raw.json> -ReviewSeedPath <map-review-seed.json> -OutputPath <output/runs/{run_id}/process/map-reviewed.json> -PoiId <poi-id> -TaskId <task-id> -RunId <run-id>
```

### 5. 补采缺失图商

检查 `internal-proxy.json` 的 `missing_vendors`。只有缺失图商才允许补采，每个缺失图商单独执行一次：

```bash
python evidence-collection/scripts/call_map_vendor.py -PoiName <poi-name> -City <city> -Source <amap|bmap|qmap> -PoiId <poi-id> -TaskId <task-id> -RunId <run-id> -OutputPath <output/runs/{run_id}/process/map-raw-vendor.json>
```

补采返回的每个 `vendor-fallback.json` 也必须重复上一步，先生成对应的 `map-reviewed-<branch>-<timestamp>.json`，再进入归并。

### 6. `webreader` 增强与 fallback

- 若存在 direct_read 来源或 `websearch-reviewed.json` 中有 `should_read=true` 的结果，可运行：

```bash
python evidence-collection/scripts/build_webreader_plan.py -WebPlanPath <web-plan.json> -WebSearchReviewedPath <websearch-reviewed.json> -OutputPath <webreader-plan.json> -PoiId <poi-id> -TaskId <task-id> -RunId <run-id>
python evidence-collection/scripts/webreader_adapter.py -WebReaderPlanPath <webreader-plan.json> -OutputPath <webreader-raw.json> -PoiId <poi-id> -TaskId <task-id> -RunId <run-id>
python evidence-collection/scripts/prepare_webreader_review_input.py -PoiPath <input.json> -WebReaderRawPath <webreader-raw.json> -OutputPath <webreader-review-input.json> -TaskId <task-id> -RunId <run-id>
python evidence-collection/scripts/validate_webreader_review_seed.py -WebReaderReviewInputPath <webreader-review-input.json> -ReviewSeedPath <webreader-review-seed.json>
python evidence-collection/scripts/write_webreader_review.py -WebReaderRawPath <webreader-raw.json> -WebReaderReviewInputPath <webreader-review-input.json> -ReviewSeedPath <webreader-review-seed.json> -OutputPath <webreader-reviewed.json> -PoiId <poi-id> -TaskId <task-id> -RunId <run-id>
```

- `webreader` 默认执行“两阶段并发”：先 `Jina` 全量并发，再仅失败 URL 回退 `Tavily`
- `webreader` 原始结果不能直接归并，必须先经过模型提取 review 落为 `webreader-reviewed.json`
- 若 `webreader` 失败、超时或不可用，不得阻断主流程，必须继续使用 `websearch-reviewed.json` 进入归并

后续替换方向：

- 本段中的 `webfetch` 后续应由 `webreader` 内部代理替换
- 替换的目标是“按 URL 读取页面信息”，不是替换前面的 `websearch`
- 为兼容旧 seed，可同时接受 `should_fetch/fetch_url`；新流程统一使用 `should_read/read_url`

### 7. reviewed-only merge

所有分支完成后，先归并再规范化。归并脚本只接收图商 reviewed 文件，不接收图商 raw 文件：

```bash
python evidence-collection/scripts/merge_evidence_collection_outputs.py -PoiPath <input.json> -InternalProxyPath <map-reviewed-internal-proxy.json> -WebSearchPath <websearch-reviewed.json> [-WebReaderPath <webreader-reviewed.json>] -VendorFallbackPaths <map-reviewed-vendor-a.json> <map-reviewed-vendor-b.json> -OutputPath <output/runs/{run_id}/process/collector-merged.json> -RunId <run-id> -TaskId <task-id>
```

### 8. 写 formal evidence

运行正式写入脚本，把归并结果落成最终证据文件：

```bash
python evidence-collection/scripts/write_evidence_output.py -PoiPath <input.json> -CollectorOutputPath <output/runs/{run_id}/process/collector-merged.json> -OutputDirectory <output/runs/{run_id}/staging> -RunId <run-id> -TaskId <task-id>
```

### 9. 最终只返回 `evidence_path`

只把脚本返回的 `evidence_path` 交给父技能或 `verification` 子技能。

## Raw branch contract

`websearch-reviewed` 和 `webreader-reviewed` 分支必须输出带 `context` 的 JSON 对象，且对象内需包含 `items`、`evidence_list` 或 `records` 之一；不要只落一个裸数组。

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

authority metadata 最小约束（用于后续 `verification` 分类推断）：

- `metadata.signal_origin`：`websearch | webreader | map_vendor`
- `metadata.source_domain`：来源域名
- `metadata.page_title`：页面标题（可空）
- `metadata.text_snippet`：受控摘要（可空）
- `metadata.level_hint`：层级提示（可空）
- `metadata.authority_signals`：机构关键词命中列表（可空）

## Output contract

正式证据文件必须：

- 文件名为 `evidence_<timestamp>.json`
- 文件内容为最终初筛并规范化后的证据数组
- 每个 item 满足 `skills-bigpoi-verification/schema/evidence.schema.json` 的 item 结构
- `poi_id` 必须与输入 `id` 一致

过程文件必须：

- 不使用 `evidence_*.json`、`decision_*.json`、`record_*.json`、`index_*.json` 这类正式命名
- 不作为最终交付物返回给父技能
- 不进入父技能最终索引

## Failure handling

若 `merge_evidence_collection_outputs.py` 失败，说明至少有一个分支结果缺字段、结构不对，或与输入 POI 绑定关系不一致。

此时必须：

1. 回到失败分支重新生成原始 JSON 或 review seed
2. 若是 review seed 问题，必须重新调用子 agent / Task 输出合格 seed，不要手写或沿用 `auto_generated`
3. 重新运行 `write_map_relevance_review.py` 或 `write_websearch_review.py` 产出 reviewed JSON
4. 重新执行归并脚本
5. 重新运行 `write_evidence_output.py`
6. 只返回新的 `evidence_path`

不要：

- 手工拼接证据数组绕过脚本
- 在内部图商已有结果时仍然补采同图商
- 把 `websearch` / `webreader` 的自然语言结论直接交给 `verification`
- 因为 `webreader` 失败就放弃已经完成的 `websearch-reviewed`

## References to load only when needed

仅在需要时读取：

- `skills-bigpoi-verification/schema/input.schema.json`
- `skills-bigpoi-verification/schema/evidence.schema.json`
- `skills-bigpoi-verification/config/poi_type_mapping.yaml`
- `evidence-collection/config/common.yaml`
- `evidence-collection/config/{resolved-category}.yaml`
