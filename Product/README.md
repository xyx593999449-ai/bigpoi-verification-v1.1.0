# Product 域文档

## 1. 域定位

`Product/` 负责正式 BigPOI 核验链路，把 POI 输入推进为可校验、可追溯、可写库的正式结果包。

## 2. 模块组成

| 模块 | 作用 |
|---|---|
| `skills-bigpoi-verification/` | 主整合技能，负责运行上下文初始化、结果打包、结果校验 |
| `evidence-collection/` | 证据采集、地图结果评审、采集结果合并、evidence 输出 |
| `evidence_collection_v2/` | v2 skill 编排层，负责“主编排 + web/map 双分支 agent + merge skill” 结构试运行 |
| `verification/` | 基于输入与 evidence 生成 decision |
| `write-pg-verified/` | 把正式结果包回写到 PostgreSQL |

## 3. 关键目录

| 路径 | 说明 |
|---|---|
| `skills-bigpoi-verification/config/poi_type_mapping.yaml` | POI 类型映射 |
| `skills-bigpoi-verification/schema/` | input / evidence / decision / record schema |
| `evidence-collection/config/` | 通用采集配置与按类型拆分的证据源配置 |
| `evidence_collection_v2/.claude/skills/` | v2 证据收集 skill 目录，包含 orchestrator / web / map / merge 四个 skill |
| `evidence_collection_v2/.claude/agents/` | v2 证据收集 project subagent 目录，包含 web 与 map 两个并发 agent |
| `verification/config/` | 核验阈值、降级策略、类型映射 |
| `write-pg-verified/config/db_config.yaml` | 正式回库数据库配置 |

## 4. 正式脚本入口

### 4.1 evidence-collection

- `evidence-collection/scripts/build_web_source_plan.py`
- `evidence-collection/scripts/orchestrate_collection.py`
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
- `evidence-collection/scripts/build_webfetch_plan.py`（兼容旧流程）
- `evidence-collection/scripts/merge_evidence_collection_outputs.py`
- `evidence-collection/scripts/write_evidence_output.py`

### 4.2 verification

- `verification/scripts/write_decision_output.py`
- `verification/scripts/authority_category_inference.py`（authority 分类增强模块，供 `write_decision_output.py` 内部调用）

### 4.3 skills-bigpoi-verification

- `skills-bigpoi-verification/scripts/init_run_context.py`
- `skills-bigpoi-verification/scripts/write_result_bundle.py`
- `skills-bigpoi-verification/scripts/validate_result_bundle.py`

### 4.4 write-pg-verified

- `write-pg-verified/SKILL.py`
- `write-pg-verified/scripts/data_converter.py`
- `write-pg-verified/scripts/db_writer.py`
- `write-pg-verified/scripts/file_loader.py`
- `write-pg-verified/SKILL.py` supports CLI table overrides via `--init` and `--verified`.
- 正式结果文件：
  - `evidence_<timestamp>.json`
  - `decision_<timestamp>.json`
  - `record_<timestamp>.json`
  - `index_<timestamp>.json`

## 7. 执行顺序建议

1. 准备输入 POI 与工作目录。
2. 用 `init_run_context.py` 初始化 `run_id` 与运行目录。
3. 执行 `evidence-collection` 生成 `evidence_*.json`。
4. 执行 `verification` 生成 `decision_*.json`。
5. 执行 `write_result_bundle.py` 生成 `record` 与 `index`。
6. 执行 `validate_result_bundle.py` 做结构校验。
7. 需要回库时执行 `write-pg-verified`。

## 8. 维护要求

- Product 域变更优先更新本文件和 `Product/CHANGELOG.md`。
- 涉及 schema、阈值、回库映射变更时，同时更新对应技能 README / SKILL。
- 涉及 `Product/verification/rules/**/README.md` 的规则说明变更时，也应同步回看本文件是否需要更新入口描述。
- 新增文档前先备份旧版本到 `docs/backups/`。

## 9. 一期 authority 与搜索代理策略（2026-04）

- `websearch` 分支统一走 `websearch_adapter.py`，固定 `baidu -> tavily` 回退顺序；当前执行策略为“两阶段并发”：先并发全部 `baidu` 查询，再仅对超时/无返回 query 并发回退 `tavily`。脚本层会做最小必要字段保留、重复结果去重、标题/摘要清洗，并输出可继续 review 的 `items` 结构。
- `websearch_adapter.py` 现在只读取 `internal_search.base_url` 或 `internal_proxy.search_base_url`，不再回退到图商 `mapapi` 地址；运行时会额外产出 `websearch-debug.json` 便于排查代理无结果问题。
- `websearch` review 已拆成独立阶段：先运行 `prepare_websearch_review_input.py` 生成模型输入，再由模型产出 review seed，最后通过 `write_websearch_review.py` 落成 `websearch-reviewed.json`。
- `websearch` review 现在必须显式输出 `entity_relation`，只有页面主体为目标 POI 本体的结果才允许进入 `websearch-reviewed.json`；正文顺带提到、导航列出、下属机构或同辖区页面会在 review 阶段剔除。
- 图商 review 也已拆成独立阶段：先运行 `prepare_map_review_input.py` 生成精简候选卡片，再由子 agent / Task 逐条判断相关性，校验通过后写成 `map-reviewed-*.json`。
- `validate_map_review_seed.py` 与 `validate_websearch_review_seed.py` 已成为正式 gate：`auto_generated`、全量放行、缺少结构化字段、未逐条覆盖等 seed 不允许继续进入 merge。
- 证据收集主控与关键分支脚本会在 stderr 输出阶段性中文描述，并在 stdout JSON 中补充 `summary_text`，便于在 skill 日志中快速判断执行情况。
- 上述白盒输出已覆盖 `build_web_source_plan.py`、`call_internal_proxy.py`、`websearch_adapter.py`、`call_map_vendor.py`、`write_map_relevance_review.py`、`merge_evidence_collection_outputs.py`、`write_evidence_output.py`。
- 正式 evidence 在 `metadata` 最小保留 authority 高价值字段：`signal_origin`、`source_domain`、`page_title`、`text_snippet`、`level_hint`、`authority_signals`。
- authority 类目（政府、公检法）在 `verification` 阶段进行 6 位码推断增强，低置信度场景也必须产出正式 `decision`，不再因为置信度阈值中断。

## 10. 二期主控收敛（2026-04）

- `evidence-collection` 已新增统一主控入口 `orchestrate_collection.py`，主线目录可直接程序化编排图商、`websearch`、补采、归并和 evidence 写出。
- 若图商候选需要先做相关性过滤，主控可通过 `-InternalReviewSeedPath` 与 `-VendorReviewSeedPaths vendor=path` 在归并前生成 `map-reviewed-*.json`，避免“先核实、后过滤”。
- 页面增强层当前主线已切到 `webreader`：`build_webreader_plan.py -> webreader_adapter.py -> prepare/validate/write_webreader_review.py`；失败不阻断，允许继续使用 `websearch-reviewed.json` 进入 merge。
- `orchestrate_collection.py` 现支持 `-WebReaderPath`（兼容 `-WebFetchPath`）透传外部 reviewed 结果，也支持内置执行 `webreader` 全链路。
- 主控与归并脚本现在都要求 reviewed-only 输入：图商和 `websearch` 若存在候选，必须先经过模型 review 和 seed 校验，raw 结果不能直接并入 formal evidence。
- Product 域正式执行脚本已完成 Python 3.9 兼容处理，避免 `X | None` 这类 3.10+ 注解语法在正式环境报错。
- `evidence_*.json` 输出 contract 保持不变，下游 `verification` 与父 skill 无需改协议。
- 二期详细架构已补充为“计划驱动的 skill 编排 + Python worker + model review 节点”，详见 [docs/Product_phase2_detailed_design_plan_driven_evidence_collection_20260401.md](/Users/liubai/Documents/project/ft_project/datamalo/big_poi/docs/Product_phase2_detailed_design_plan_driven_evidence_collection_20260401.md)。

## 11. `websearch` / `webreader` 职责边界（2026-04-07）

- `websearch` 内部代理负责按 `query` 收集候选网站、标题、摘要与候选 URL，仍属于“搜索发现层”。
- 当前 `webfetch` 只作为兼容旧流程保留；页面增强主语义改为 `webreader`，并从 `websearch-reviewed.json` 中 `should_read=true` 的 URL 做进一步页面读取。
- 后续 web 计划层应显式拆成 `direct_read` 与 `search_discovery` 两类来源：配置中已知的权威 URL 应优先 direct read，未知页面再交给 `websearch`。
- 后续替换方向应为“保留 `websearch`，用 `webreader` 替换 `webfetch`”，而不是把 `websearch` 改造成 URL 读取器。
- 框架设计上要适配所有 POI 类型，但首批精细化策略先聚焦政府机关；政府机关 query 首批只聚焦 `办公地址` 与 `联系电话`。
- `webreader` 执行层已明确接入内部网关 `botshop/proxy/webfetch`，当前采用“两阶段并发”：先全部 URL 通过 `Jina-Reader` 并行抓取，再仅对失败 URL 通过 `Tavily-Extract` 并行回退。
- 当前主线已落地替换节点：
  - `build_webreader_plan.py`
  - `webreader_adapter.py`
  - `webreader-reviewed.json`
  - `merge_evidence_collection_outputs.py` 中的 `-WebReaderPath`（兼容 `-WebFetchPath`）
  - `orchestrate_collection.py` 中 `-WebReaderPath` / `-WebReaderReviewSeedPath`
- 本轮需求说明与改造建议详见 [docs/Product_webreader_replacement_plan_20260407.md](/Users/liubai/Documents/project/ft_project/datamalo/big_poi/docs/Product_webreader_replacement_plan_20260407.md)。

## 12. `evidence_collection_v2` skill 拆分（2026-04-07）

- `Product/evidence_collection_v2/` 新增一套面向 Claude Code skill 运行时的 v2 结构，不替换现有正式 Python 脚本，只拆分 skill 编排职责。
- v2 当前拆为 4 个 skill：
  - `product-evidence-intel-v2`
  - `product-evidence-web-v2`
  - `product-evidence-map-v2`
  - `product-evidence-merge-v2`
- v2 同时新增 2 个 project subagent：
  - `product-web-researcher-v2`
  - `product-map-researcher-v2`
- 推荐执行流为“主 skill 初始化 run context -> 并发启动 web/map 两个 agent -> 读取 `web-branch-result.json` 与 `map-branch-result.json` -> merge skill 写出正式 `evidence_path`”。
- 该目录下 skill 默认通过 `Product/evidence_collection_v2/.claude/` 发现，适合在该目录内运行，或通过 `--add-dir Product/evidence_collection_v2` 加入发现范围。
