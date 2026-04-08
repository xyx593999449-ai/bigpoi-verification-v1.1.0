# Changelog

## [2.0.2] - 2026-04-08

### Changed
- Product authority 分类规则修正：`街道办事处` 归入 `130105`（乡镇/街道同级），`130106` 仅用于社区/行政村等乡镇以下级。
- 同步修正证据链路中的行政层级提示归一化，避免街道被降到 `130106`。
- `evidence-collection-web` skill 补齐显式执行流程、review gate 和状态规则，降低模型执行歧义。

## [2.0.1] - 2026-04-07

### Added
- Product 新增 `evidence-collection/scripts/run_evidence_collection.py` 作为证据收集主脚本，统一编排并行 worker、merge 与 formal evidence 落盘。
- 新增分支结果写入脚本：`evidence-collection-web/scripts/write_web_branch_result.py`、`evidence-collection-map/scripts/write_map_branch_result.py`。

### Changed
- `orchestrate_collection.py` 支持自动发现默认 review seed 路径，并增强 seed 缺失报错提示（包含 expected seed 路径与对应 review input 路径）。
- web/map review 写出链路与 merge 链路补充 `context.created_at` 稳定兜底，减少 `empty/skipped` 分支的 merge 失败。
- 仓库级与 Product 域文档补充新主入口、分支结果脚本与 seed 路径约定。

## [2.0.0] - 2026-04-07

### Changed
- Product 域完成证据收集技能工程化重构，正式收敛为 `evidence-collection` 主入口与 `evidence-collection-web`、`evidence-collection-map`、`evidence-collection-merge` 三个子技能。
- `evidence-collection/scripts/run_parallel_claude_agents.py` 正式迁入主入口目录，统一通过两个 `claude -p` worker 并发执行 web 与图商分支。
- Product 侧证据收集共享模块归位到 `evidence-collection/scripts/`，web、map、merge 三类脚本归位到各自技能目录，目录职责边界与文档入口完成收口。

### Docs
- 重写仓库级 `README.md` 与 Product 域 `README.md / CHANGELOG.md`，统一到 `2.0.0` 工程化后的技能结构与运行入口。

## [1.4.6] - 2026-04-07

### Added
- Product `evidence-collection` 新增 `webreader` 主链路脚本：`build_webreader_plan.py`、`webreader_adapter.py`、`prepare_webreader_review_input.py`、`validate_webreader_review_seed.py`、`write_webreader_review.py`。
- 新增 `Product/evidence-collection/prompts/webreader_extract.md`，用于 `webreader` 结果提取与结构化 review。

### Changed
- `build_web_source_plan.py` 升级为双通道输出：新增 `direct_read_sources` 与 `search_queries`，并在政府机关场景默认细化为 `办公地址` / `联系电话` 两类 query intent。
- 修正 `direct_read` 约束：可直读权威 URL 不再进入 `search_queries`，避免“先 search 再 read”的冗余开销。
- `websearch_adapter.py` 优先消费 `search_queries`；`websearch` review 信号字段升级为 `should_read/read_url`（兼容旧 `should_fetch/fetch_url`）。
- `orchestrate_collection.py` 接入内置 `webreader` 执行与 review 链路，并新增 `-WebReaderPath`、`-WebReaderReviewSeedPath`（兼容 `-WebFetchPath`）。
- `orchestrate_collection.py` 在 `search_queries=0` 时自动跳过 `websearch` 执行。
- `merge_evidence_collection_outputs.py` 新增 `-WebReaderPath` 并统一按 `webreader` 分支归并，保留 `-WebFetchPath` 过渡兼容。
- `evidence_collection_common.py` 增加 `signal_origin=webreader` 与 `webreader` 分支 `collection_method` 处理。

### Docs
- `docs/Product_webreader_replacement_plan_20260407.md` 补充“已落地的数据交换规格”，明确 plan/raw/reviewed 关键字段与主控/归并参数兼容策略。
