# Product CHANGELOG

## [2.0.5] - 2026-04-08
### Changed
- `call_internal_proxy.py` 的图商内部代理默认超时策略调整为：首轮 10 秒，若命中超时则仅重试 1 次且第二轮超时为 60 秒。
- 图商内部代理在第二轮仍超时时会直接抛出异常，不再把连续超时静默写成普通 `missing_vendors`。
- `evidence-collection/config/common.yaml` 与 `evidence-collection-map/config/common.yaml` 新增 `internal_proxy.retry_timeout: 60`，并将 `internal_proxy.timeout` 默认值改为 10。

### Added
- 新增回归测试覆盖：
  - 首轮超时后 60 秒重试成功
  - 两轮都超时时抛出异常

## [2.0.4] - 2026-04-08
### Changed
- `build_web_source_plan.py` 调整为“配置源默认只做 search discovery”，不再把政府门户、百科等类型配置 URL 自动塞进 `direct_read_sources`；`direct_read` 仅对显式允许的直读来源生效。
- `build_webreader_plan.py` 显式输出 `read_target_count`，并继续优先消费 `websearch-reviewed.json` 中被保留的详情页 `read_url`。
- `validate_websearch_review_seed.py` 放宽 `is_relevant=true` 的约束：不再强制 `entity_relation=poi_body`，避免为通过校验而篡改事实关系；仅 `poi_body` 才允许 `evidence_ready=true` 进入 merge。
- `write_web_branch_result.py` 新增 `webreader_plan/raw` 感知与 `webreader_execution_state`、`attention_required` 字段，可区分“正常 empty”与“详情页未执行完整”；当 `websearch` 已有可归并结果时，不会因为 reader 缺失而误判整条分支失败。
- `merge_evidence_collection_outputs.py` 在 web 证据层增加同源重复页去重，避免同一官方页面不同 URL 重复抬高置信度。
- `write_decision_output.py` 增加地址收敛守卫与运行时序兜底：当证据地址明显比输入地址更具体但未收敛时，地址维度会降为 `uncertain`；同时自动补齐正数 `processing_duration_ms` 并修正 `created_at/seed_created_at` 时序。
- `bundle_common.py` 与 `validate_result_bundle.py` 补齐地址最终值和结果包语义校验，防止 accepted 结果继续保留粗粒度地址。

### Added
- 新增回归测试覆盖：
  - 配置源 search-only 规划
  - `relevant` 但非 `poi_body` 的 review seed 校验
  - `webreader` 正常 empty 与缺失执行的分支状态区分
  - websearch 同页重复 evidence 去重
  - 地址未收敛时的 decision/validator 守卫

## [2.0.3] - 2026-04-08
### Changed
- 删除 `evidence-collection/scripts/orchestrate_collection.py` 旧兼容入口，正式收敛到 `run_evidence_collection.py` 唯一主入口，减少模型误判到过时链路。
- 将对应测试从 `test_evidence_orchestrator.py` 重定向为 `test_run_evidence_collection.py`，改为覆盖当前正式入口的公共行为。
- 移除 `evidence-collection`、`evidence-collection-web`、`evidence-collection-map`、`evidence-collection-merge` 的 `disable-model-invocation: true` 限制，允许父技能按设计直接编排调用。

## [2.0.2] - 2026-04-08
### Changed
- 修正 authority 分类行政层级口径：`街道办事处` 从 `130106` 调整为 `130105`（乡镇/街道同级），`130106` 保留为社区/行政村等乡镇以下级。
- 同步更新 `evidence_collection_common.py` 的 `level_hint` 归一化规则，避免“街道”被归入“乡镇以下级”。
- 更新 `poi_type_mapping.yaml` 注释说明，明确 `130105` 与 `130106` 的边界定义。
- 重写 `evidence-collection-web/SKILL.md` 的执行说明，补齐固定流程、跳过条件、review seed 约定与分支状态规则，避免模型面对脚本列表时自行猜流程。

## [2.0.1] - 2026-04-07
### Added
- 新增 `evidence-collection/scripts/run_evidence_collection.py`，作为主入口一键编排并行 worker、分支结果读取、merge 与 formal evidence 写出。
- 新增分支结果写入脚本：
  - `evidence-collection-web/scripts/write_web_branch_result.py`
  - `evidence-collection-map/scripts/write_map_branch_result.py`

### Changed
- `evidence-collection/scripts/orchestrate_collection.py` 支持自动发现默认 seed 文件（`map-review-seed-internal-proxy.json`、`map-review-seed-fallback-{vendor}.json`、`websearch-review-seed.json`、`webreader-review-seed.json`），降低手动参数依赖。
- `orchestrate_collection.py` 的 seed 缺失报错升级为可执行提示，输出 `expected_seed_path` 与 `review_input_path` 指引后续执行。
- web/map 的 `write_*_review.py` 在写入 context 时显式透传 `created_at`，保证 merge 阶段上下文稳定。
- 两套 merge 脚本（`evidence-collection/scripts` 与 `evidence-collection-merge/scripts`）新增 context 兜底补齐逻辑，避免 `empty/skipped` 分支因 `context.created_at` 缺失直接失败。

### Docs
- 更新 `Product/README.md` 与 `evidence-collection*` 技能文档，补充新主入口、分支结果写入脚本与 review seed 默认路径约定。

## [2.0.0] - 2026-04-07
### Changed
- 完成 Product 域证据收集技能工程化重构，正式收敛为 `evidence-collection` 主入口与 `evidence-collection-web`、`evidence-collection-map`、`evidence-collection-merge` 三个子技能。
- `evidence-collection/scripts/run_parallel_claude_agents.py` 正式迁入主入口目录，继续采用 `claude -p` 双 worker 并发拉起 web 与图商分支。
- 证据收集共享 Python 模块统一归位到 `evidence-collection/scripts/`，避免各子技能重复维护公共逻辑。
- web、map、merge 三类脚本分别归位到对应子技能目录，目录职责边界与脚本职责边界保持一致。
- 图商与 web 分支结果改为由主入口统一汇总，再交由 `evidence-collection-merge` 完成 reviewed-only merge 与 formal evidence 写出。

### Docs
- 重写 `Product/README.md`，按正式技能入口、子技能职责、关键脚本和结果目录重新组织说明。
- 更新 `Product/verification/rules/location/README.md`、`evidence-collection-opt1/SKILL.md` 与 `evidence-collection-opt3/SKILL.md` 的 merge 脚本路径引用，统一指向 `evidence-collection-merge/scripts/merge_evidence_collection_outputs.py`。
- 将旧试运行目录收敛为迁移参考，不再作为 Product 域文档主线。

## [1.10.8] - 2026-04-07
### Added
- 新增 `webreader` 主线脚本：
  - `evidence-collection/scripts/build_webreader_plan.py`
  - `evidence-collection/scripts/webreader_adapter.py`
  - `evidence-collection/scripts/prepare_webreader_review_input.py`
  - `evidence-collection/scripts/validate_webreader_review_seed.py`
  - `evidence-collection/scripts/write_webreader_review.py`
- 新增 `evidence-collection/prompts/webreader_extract.md`，用于 `webreader` review 提取。

### Changed
- `build_web_source_plan.py` 新增 `direct_read_sources` 与 `search_queries` 输出结构；政府机关场景默认 query intent 收敛为 `办公地址` 与 `联系电话`。
- 修正 `direct_read` 行为：可直读来源不再进入 `search_queries`，满足“已知权威 URL 直读优先且不先走 websearch”。
- `websearch_adapter.py` 优先消费 `search_queries`；`websearch` review 元字段升级为 `should_read/read_url`（兼容旧 `should_fetch/fetch_url`）。
- `orchestrate_collection.py` 接入 `webreader` 内置执行链路（`build plan -> adapter -> prepare/validate/write review`），并新增 `-WebReaderPath`、`-WebReaderReviewSeedPath` 参数。
- `orchestrate_collection.py` 在 `search_queries=0` 时跳过 `websearch` 阶段，减少无效调用。
- `merge_evidence_collection_outputs.py` 新增 `-WebReaderPath`，归并分支统一为 `webreader`；保留 `-WebFetchPath` 兼容旧调用。
- `evidence_collection_common.py` 补充 `signal_origin=webreader` 与 `webreader` 分支的 `collection_method`。

### Docs
- `Product/README.md` 与 `evidence-collection/SKILL.md` 更新为 `webreader` 主链路说明，同时保留 `webfetch` 兼容提示。
- [docs/Product_webreader_replacement_plan_20260407.md](/Users/liubai/Documents/project/ft_project/datamalo/big_poi/docs/Product_webreader_replacement_plan_20260407.md) 补充关键节点数据交换规格与参数兼容说明。
