# Product CHANGELOG

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
