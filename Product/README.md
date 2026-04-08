# Product 域文档

## 1. 域定位

`Product/` 负责正式 BigPOI 核验链路，把输入 POI 推进为可校验、可追溯、可回库的正式结果包。

## 2. 正式技能组成

| 模块 | 作用 |
|---|---|
| `skills-bigpoi-verification/` | 父技能，负责运行上下文初始化、证据与决策子技能串联、结果成包与最终校验 |
| `evidence-collection/` | 证据收集主入口，负责任务调度、共享脚本宿主、并发 worker 启动与 formal evidence 写出 |
| `evidence-collection-web/` | 证据收集 web 子技能，负责 `websearch + webreader` 计划、采集、review 与分支落盘 |
| `evidence-collection-map/` | 证据收集图商子技能，负责内部代理、缺失图商补采、map review 与分支落盘 |
| `evidence-collection-merge/` | 证据收集合并子技能，负责 reviewed-only merge 与正式 `evidence_*.json` 写出 |
| `verification/` | 基于输入 POI 与 formal evidence 生成正式 `decision_*.json` |
| `write-pg-verified/` | 把正式结果包回写到 PostgreSQL |

## 3. 关键目录

| 路径 | 说明 |
|---|---|
| `skills-bigpoi-verification/config/poi_type_mapping.yaml` | POI 类型映射 |
| `skills-bigpoi-verification/schema/` | input / evidence / decision / record schema |
| `evidence-collection/config/` | 通用采集配置与按类型拆分的证据源配置 |
| `evidence-collection/scripts/` | 证据收集主调度脚本与共享 Python 模块 |
| `evidence-collection-web/scripts/` | web 分支脚本 |
| `evidence-collection-map/scripts/` | 图商分支脚本 |
| `evidence-collection-merge/scripts/` | 归并与正式 evidence 写入脚本 |
| `verification/config/` | 核验阈值、降级策略、类型映射 |
| `write-pg-verified/config/db_config.yaml` | 正式回库数据库配置 |

## 4. 正式脚本入口

### 4.1 `evidence-collection`

- `evidence-collection/scripts/run_evidence_collection.py`
- `evidence-collection/scripts/run_parallel_claude_agents.py`
- `evidence-collection/scripts/evidence_collection_common.py`
- `evidence-collection/scripts/run_context.py`

### 4.2 `evidence-collection-web`

- `evidence-collection-web/scripts/build_web_source_plan.py`
- `evidence-collection-web/scripts/websearch_adapter.py`
- `evidence-collection-web/scripts/build_webreader_plan.py`
- `evidence-collection-web/scripts/webreader_adapter.py`
- `evidence-collection-web/scripts/prepare_websearch_review_input.py`
- `evidence-collection-web/scripts/validate_websearch_review_seed.py`
- `evidence-collection-web/scripts/write_websearch_review.py`
- `evidence-collection-web/scripts/prepare_webreader_review_input.py`
- `evidence-collection-web/scripts/validate_webreader_review_seed.py`
- `evidence-collection-web/scripts/write_webreader_review.py`
- `evidence-collection-web/scripts/write_web_branch_result.py`
- `evidence-collection-web/scripts/internal_search_client.py`

### 4.3 `evidence-collection-map`

- `evidence-collection-map/scripts/call_internal_proxy.py`
- `evidence-collection-map/scripts/call_map_vendor.py`
- `evidence-collection-map/scripts/prepare_map_review_input.py`
- `evidence-collection-map/scripts/validate_map_review_seed.py`
- `evidence-collection-map/scripts/write_map_relevance_review.py`
- `evidence-collection-map/scripts/write_map_branch_result.py`

### 4.4 `evidence-collection-merge`

- `evidence-collection-merge/scripts/merge_evidence_collection_outputs.py`
- `evidence-collection-merge/scripts/write_evidence_output.py`

### 4.5 `verification`

- `verification/scripts/write_decision_output.py`
- `verification/scripts/authority_category_inference.py`

### 4.6 `skills-bigpoi-verification`

- `skills-bigpoi-verification/scripts/init_run_context.py`
- `skills-bigpoi-verification/scripts/write_result_bundle.py`
- `skills-bigpoi-verification/scripts/validate_result_bundle.py`

### 4.7 `write-pg-verified`

- `write-pg-verified/SKILL.py`
- `write-pg-verified/scripts/data_converter.py`
- `write-pg-verified/scripts/db_writer.py`
- `write-pg-verified/scripts/file_loader.py`

## 5. 证据收集主线结构

`evidence-collection` 是父技能对接的唯一证据收集入口，内部再编排三个子技能：

1. `evidence-collection-web`
2. `evidence-collection-map`
3. `evidence-collection-merge`

推荐执行流：

1. `skills-bigpoi-verification/scripts/init_run_context.py` 初始化 `run_id` 与 `task_id`。
2. `evidence-collection/scripts/run_evidence_collection.py` 作为主脚本，内部调用 `run_parallel_claude_agents.py` 并发拉起 `evidence-collection-web` 与 `evidence-collection-map`。
3. 两个分支分别落盘 `web-branch-result.json` 与 `map-branch-result.json`。
4. `evidence-collection-merge` 读取 reviewed-only 输入，生成 `collector-merged.json` 与正式 `evidence_*.json`。
5. `verification` 读取 `evidence_path` 生成正式 `decision_*.json`。
6. `skills-bigpoi-verification` 负责结果成包与最终校验。

`claude -p` worker 的调用日志统一落到：

- `output/results/{task_id}/claude-agent-logs/`

review seed 默认路径（由并行 worker 生成，legacy 编排自动发现）：

- `output/runs/{run_id}/process/map-review-seed-internal-proxy.json`
- `output/runs/{run_id}/process/map-review-seed-fallback-{vendor}.json`
- `output/runs/{run_id}/process/websearch-review-seed.json`
- `output/runs/{run_id}/process/webreader-review-seed.json`

图商内部代理超时策略（2026-04-08）：

- `call_internal_proxy.py` 默认首轮请求超时为 10 秒。
- 若首轮命中超时，会仅重试 1 次，第二轮超时为 60 秒。
- 若第二轮仍超时，脚本会直接抛出超时异常，不再把该异常静默降级为普通 `missing_vendors` 结果。

web 分支补充约束（2026-04-08）：

- 类型配置里的 `sources` 默认只参与 `search_queries` 生成，不再因为 URL 可访问就自动进入 `direct_read_sources`。
- `direct_read_sources` 只保留显式允许直读的来源，例如输入 POI 自带官网，或后续明确加上 `allow_direct_read: true` 的来源。
- `webreader` 的正式读取目标优先来自 `websearch-reviewed.json` 中被 review 保留的详情页 `read_url`，而不是门户首页。
- `webreader-reviewed.json.status=empty` 表示“详情页已读取并完成 review，但没有形成可归并结果”，不等价于“没有执行到详情页”。
- `web-branch-result.json` 会额外输出 `webreader_execution_state` 与 `attention_required`，用于区分“正常 empty”与“链路未执行完整”。

## 6. 输出结果约束

正式结果目录固定为：

- `output/results/{task_id}/`

正式结果文件包括：

- `evidence_<timestamp>.json`
- `decision_<timestamp>.json`
- `record_<timestamp>.json`
- `index_<timestamp>.json`

过程文件应位于：

- `output/runs/{run_id}/process/`
- `output/runs/{run_id}/staging/`

过程文件不得伪装成正式结果文件，也不得进入最终 `index.files`。

authority 行政层级口径（政府机关）：
- `130105`：乡镇级（含街道办事处）
- `130106`：乡镇以下级（社区居民委员会、村民委员会等）

结果质量补充约束（2026-04-08）：

- merge 阶段会对同一 `signal_origin` 下的重复网页证据做去重，优先保留权重更高、字段更完整的那条。
- `verification` 不再允许“输入地址很粗、证据地址明显更具体，但地址维度仍直接 pass/accepted”的结果穿透到正式决策。
- 父技能 bundle validator 会额外拦截 `decision.processing_duration_ms <= 0`、`seed_created_at > decision.created_at`，以及 accepted 结果仍保留粗粒度地址的异常包。

## 7. 维护要求

- Product 域每次结构调整后优先更新本文件与 `Product/CHANGELOG.md`。
- 证据收集子技能目录、脚本入口和引用路径变更时，同时回看 `skills-bigpoi-verification/SKILL.md`、`verification/rules/**/README.md` 与根目录文档。
- 长篇方案、迁移计划与对比说明优先沉淀到 `docs/`，主 README 只保留稳定入口与主流程。

## 8. 工程化定稿参考

本轮目录重构和技能工程化定稿方案见：

- [docs/Product_skill_engineering_finalization_plan_20260407.md](/Users/liubai/Documents/project/ft_project/datamalo/big_poi/docs/Product_skill_engineering_finalization_plan_20260407.md)

## 9. 兼容说明

- 历史试运行目录与方案目录已清理，当前仅保留 `2.0.0` 正式主线结构。
