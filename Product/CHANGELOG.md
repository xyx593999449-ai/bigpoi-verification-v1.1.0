# Product CHANGELOG

## [1.10.9] - 2026-04-07
### Added
- 新增 `Product/evidence_collection_v2/`，作为证据收集 skill 拆分试运行目录。
- 新增 v2 skills：
  - `product-evidence-intel-v2`
  - `product-evidence-web-v2`
  - `product-evidence-map-v2`
  - `product-evidence-merge-v2`
- 新增 v2 project subagents：
  - `product-web-researcher-v2`
  - `product-map-researcher-v2`
- 新增 `Product/evidence_collection_v2/README.md`，说明 v2 目录目标、运行方式、输出契约与推荐执行流。

### Docs
- `Product/README.md` 增补 `evidence_collection_v2` 入口、目录说明与 v2 skill 拆分章节，明确当前采用“主编排 + 双分支 agent + merge skill” 的运行结构。

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

## [1.10.7] - 2026-04-07
### Docs
- 新增 [docs/Product_webreader_replacement_plan_20260407.md](/Users/liubai/Documents/project/ft_project/datamalo/big_poi/docs/Product_webreader_replacement_plan_20260407.md)，明确 `websearch` 保留、`webfetch` 替换为 `webreader` 的需求背景、职责边界与推荐改造方案。
- `Product/README.md` 补充 `websearch` / `webreader` 职责边界章节，明确当前应替换的是页面增强层而不是搜索发现层。
- 继续补充方案：明确 web 计划层后续采用 `direct_read + search_discovery` 双通道，并规定框架适配所有类型、首批重点先做政府机关，政府 query 首批只聚焦 `办公地址` 与 `联系电话`。
- 继续补充 `webreader` 内部接口协议，明确 `Jina-Reader` 与 `Tavily-Extract` 共用内部网关、参数差异、输出差异与推荐接入策略。
- 收紧 `webreader` provider 调度策略：先由 `Jina-Reader` 对全部 URL 并行抓取，仅对失败 URL 再由 `Tavily-Extract` 并行回退，以兼顾国内政府机关站点可达性与整体效率。

## [1.10.6] - 2026-04-03
### Changed
- `evidence-collection/scripts/websearch_adapter.py` 的 provider 调度改为“两阶段并发”：先并行执行所有 `baidu` query，再仅对超时/空结果 query 并行回退 `tavily`。

### Tests
- `Product/tests/test_evidence_collection.py` 新增 `test_websearch_adapter_two_phase_parallel_fallback_scope`，覆盖“仅超时/空结果触发二阶段回退”的行为约束。

## [1.10.5] - 2026-04-02
### Fixed
- 修正 `skills-bigpoi-verification/scripts/bundle_common.py` 在 Python 3.9 下对 `Path.write_text(..., newline=...)` 的不兼容调用，避免 `write_result_bundle.py` 成包阶段因 `unexpected keyword argument 'newline'` 失败。
- 新增图商 review 预处理与 `map/websearch review seed` 校验脚本，禁止 `auto_generated`、全量放行或缺少结构化字段的 seed 继续进入 merge。
- 收紧 `merge_evidence_collection_outputs.py` 与 `orchestrate_collection.py`，要求图商和 `websearch` 分支在有候选时必须先经过 reviewed gate，raw 结果不能直接并入 formal evidence。
- 调整 `websearch_adapter.py` 的名称启发式，避免把输入 POI 名称盲目回填给无关搜索结果。
- 收紧 `websearch` review contract，新增 `entity_relation` 枚举并要求 `is_relevant=true` 时必须为 `poi_body`，进一步压缩“正文提到/导航命中/下属机构”类噪音。

## [1.10.4] - 2026-04-01
### Added
- 新增 `prepare_websearch_review_input.py`、`write_websearch_review.py`、`build_webfetch_plan.py`，把 `websearch reviewed` 与 `webfetch fallback` 正式拆成独立可落盘阶段。
- 新增 `Product/evidence-collection/prompts/` 下的计划生成、图商 review、`websearch` review、`webfetch` extract 提示词支持文件。

### Changed
- `evidence-collection/SKILL.md` 改为以“plan -> raw -> review -> reviewed -> merge -> formal evidence”为主线，并明确 `webfetch` 失败时继续使用 `websearch-reviewed`。
- `websearch_adapter.py` 现在只保留最小必要字段，并在脚本层完成标题/摘要清洗、地址电话提取与重复结果去重。

## [1.10.3] - 2026-04-01
### Fixed
- 为 `internal_search` 补齐正式配置段与 `search_base_url`，并限制 `websearch_adapter.py` 不再回退误用图商 `mapapi` 地址。
- `websearch_adapter.py` 新增运行时调试日志输出，主控默认落盘 `websearch-debug.json`，便于排查 provider、query、time_range 与返回状态。
- `orchestrate_collection.py` 新增图商 review 接入能力，可在归并前消费 `map review seed` 生成 `map-reviewed-*.json`，修正“过滤晚于核实且未生效”的流程问题。
- Product 主线与 phase2 相关脚本完成 Python 3.9 注解兼容处理，避免正式环境因 `X | None` 语法报错。
- `orchestrate_collection.py`、`websearch_adapter.py`、`call_internal_proxy.py`、`merge_evidence_collection_outputs.py` 新增阶段性 stderr 日志与 `summary_text` 输出，降低 skill 执行黑盒感。
- `build_web_source_plan.py`、`call_map_vendor.py`、`write_map_relevance_review.py`、`write_evidence_output.py` 也补齐了同样的白盒输出，确保单步执行时日志同样可读。

### Docs
- 新增二期详细设计文档，明确证据收集正式架构应演进为“计划驱动的 skill 编排 + Python worker + model review 节点”，不再以纯 Python 从 raw 直出 formal evidence 作为终态。

## [1.10.2] - 2026-04-01
### Added
- authority 灰区新增二阶段模型裁决入口：`decision seed.authority_model_judgment`，并对候选码集合做强约束校验。
- `websearch` 代理调用新增 `count/time_range` 参数透传能力，支持计划层搜索控制项向下传递。

### Fixed
- authority 规则层在 uncertain 场景输出候选码集合与冲突摘要，补齐“规则优先、灰区裁决”闭环。

## [1.10.1] - 2026-04-01
### Fixed
- 修正 `internal_search_client.py` 的代理请求参数协议，改为 `source/query` 并补齐 `use_site/usesite`、`block_site/blocksite` 站点过滤字段。
- 修正 `websearch_adapter.py` 在 `status=empty` 时的退出码，避免把可降级场景误判为失败。
- 修正 `orchestrate_collection.py` 对 websearch 分支失败判定，`empty/partial/ok` 不再阻断 evidence 主流程。
- 补全 `authority_category_inference.py` 中 metadata 最小 contract 缺失时的显式降权策略（`signal_origin/source_domain/page_title/text_snippet`）。

## [1.10.0] - 2026-04-01
### Added
- 新增 `evidence-collection/scripts/orchestrate_collection.py`，作为二期主控统一入口，串联 `build plan -> internal proxy + websearch -> fallback -> merge -> write evidence`。
- 新增 `Product/tests/test_evidence_orchestrator.py`，覆盖主控关键能力的单测。

### Changed
- `evidence-collection/SKILL.md` 新增 phase2 推荐执行方式，优先使用统一主控脚本，保留分步流程兼容。
- `run_context.py` 的入口提示更新，纳入 `orchestrate_collection.py`。
- `Product/README.md` 新增二期主控收敛章节，明确正式主线能力与兼容边界。

## [1.9.0] - 2026-04-01
### Added
- 新增 `verification/scripts/authority_category_inference.py`，实现政府/公检法 authority 分类推断与 6 位码级别修正建议生成。
- 新增 `evidence-collection/scripts/internal_search_client.py` 与 `evidence-collection/scripts/websearch_adapter.py`，统一内部搜索代理调用与 `baidu -> tavily` 回退。

### Changed
- `verification/scripts/write_decision_output.py` 接入 authority 分类增强，自动补齐 `dimensions.category.details` 并在证据充分时写出 `corrections.category`。
- 移除 `write_decision_output.py` 中“整体置信度 < 0.85 直接抛错中断”的主流程逻辑，低置信度场景改为正式输出 `downgraded / manual_review` 决策。
- `evidence-collection/scripts/evidence_collection_common.py` 增强 evidence metadata，按最小 contract 保留 authority 高价值信号字段。
- 同步更新 `Product` 域三个 SKILL 文档与域 README，明确 authority 与搜索代理一期约束。

### Tests
- 重写 `Product/tests/test_write_decision.py`，覆盖“低置信度仍输出 decision”与“authority 自动 category 修正”场景。
- 重写 `Product/tests/test_evidence_collection.py`，覆盖 authority metadata contract 与 `baidu -> tavily` 回退行为。

## [1.8.0] - 2026-03-23
### Added
- 为 `verification` 提供大模型熔断前置距离注入能力（在落数据前剔除 raw_data 并置入直实地理距离）。
### Changed
- `evidence-collection` 中的 `call_map_vendor` 全面 AsyncIO 化，消除同步请求的堆叠损耗。
- `write_decision_output.py` 下放 0.85 置信度网卡拦截限制，向流控制器发起降级退回换模指令。

## [1.7.1] - 2026-03-23
- write-pg-verified增加主入口参数，支持配置写入的表名
### Docs
- 按当前 `Product/` 目录结构重写域级 README，补齐四个核心技能、正式脚本入口、输出目录和推荐流程。
- 重建 Product 域 changelog 顶部结构，便于后续继续按域记录 Added / Changed / Fixed。

### Process
- 保留历史版本记录作为 Product 域演进背景，后续新增变更继续追加到 `Unreleased`。

## [1.6.10] - 2026-03-17

### Fixed
- 区分可直接执行的入口脚本与仅供内部 import 的 helper module，避免把 `run_context.py` 误当成 CLI 脚本。

## [1.6.9] - 2026-03-16

### Fixed
- 统一 `run_context` 的定位与调用方式，修正多处脚本对运行上下文辅助模块的引用。

## [1.6.8] - 2026-03-16

### Changed
- 将 `location` 拆分为 `address` 与 `coordinates` 两个核验维度，并同步更新 schema、阈值和回库映射。

## [1.6.7] - 2026-03-13

### Fixed
- 补强 `decision.corrections`、`final_values` 与 `changes` 的联动写出逻辑。

## [1.6.6] - 2026-03-13

### Changed
- 引入 `run_id` 隔离机制，明确 `output/runs/{run_id}` 过程目录和 staging 目录。

## [1.6.5] - 2026-03-10

### Changed
- 统一 `WorkspaceRoot` 与结果目录解析逻辑，增强跨目录执行的稳定性。

## [1.6.4] - 2026-03-10

### Fixed
- 修正 `write-pg-verified` 在索引发现与结果回写中的路径问题。

## [1.6.3] - 2026-03-10

### Changed
- 增强 `write-pg-verified` 的回库映射与索引解析能力。

## [1.6.2] - 2026-03-10

### Fixed
- 修正基于 `task_id + search_directory` 的 `index` 查找逻辑。

## [1.1.1] - 2026-02-12

### Optimized
- 优化 evidence source 配置组织与 Token 消耗控制。

## [1.1.0] - 2026-02-10

### Breaking Change
- 形成 `skills-bigpoi-verification / evidence-collection / verification` 的技能拆分结构。

## [1.0.2] - 2026-02-04

### Fixed
- 修复多源证据采集链路中的调用与异常处理问题。

## [1.0.1] - 2026-02-03

### Fixed
- 修复早期配置文件命名与引用问题。
