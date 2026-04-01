# Product 域文档

## 1. 域定位

`Product/` 负责正式 BigPOI 核验链路，把 POI 输入推进为可校验、可追溯、可写库的正式结果包。

## 2. 模块组成

| 模块 | 作用 |
|---|---|
| `skills-bigpoi-verification/` | 主整合技能，负责运行上下文初始化、结果打包、结果校验 |
| `evidence-collection/` | 证据采集、地图结果评审、采集结果合并、evidence 输出 |
| `verification/` | 基于输入与 evidence 生成 decision |
| `write-pg-verified/` | 把正式结果包回写到 PostgreSQL |

## 3. 关键目录

| 路径 | 说明 |
|---|---|
| `skills-bigpoi-verification/config/poi_type_mapping.yaml` | POI 类型映射 |
| `skills-bigpoi-verification/schema/` | input / evidence / decision / record schema |
| `evidence-collection/config/` | 通用采集配置与按类型拆分的证据源配置 |
| `verification/config/` | 核验阈值、降级策略、类型映射 |
| `write-pg-verified/config/db_config.yaml` | 正式回库数据库配置 |

## 4. 正式脚本入口

### 4.1 evidence-collection

- `evidence-collection/scripts/build_web_source_plan.py`
- `evidence-collection/scripts/orchestrate_collection.py`
- `evidence-collection/scripts/websearch_adapter.py`
- `evidence-collection/scripts/call_internal_proxy.py`
- `evidence-collection/scripts/call_map_vendor.py`
- `evidence-collection/scripts/write_map_relevance_review.py`
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

- `websearch` 分支统一走 `websearch_adapter.py`，固定 `baidu -> tavily` 回退顺序，输出可直接归并的 `items` 结构。
- 正式 evidence 在 `metadata` 最小保留 authority 高价值字段：`signal_origin`、`source_domain`、`page_title`、`text_snippet`、`level_hint`、`authority_signals`。
- authority 类目（政府、公检法）在 `verification` 阶段进行 6 位码推断增强，低置信度场景也必须产出正式 `decision`，不再因为置信度阈值中断。

## 10. 二期主控收敛（2026-04）

- `evidence-collection` 已新增统一主控入口 `orchestrate_collection.py`，主线目录可直接程序化编排图商、`websearch`、补采、归并和 evidence 写出。
- `webfetch` 仍可通过参数接入主控（`-WebFetchPath`），保留与现有流程兼容。
- `evidence_*.json` 输出 contract 保持不变，下游 `verification` 与父 skill 无需改协议。
