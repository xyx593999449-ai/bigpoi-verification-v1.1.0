# Changelog

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

## [1.4.5] - 2026-04-07

### Docs
- 新增 `docs/Product_webreader_replacement_plan_20260407.md`，正式沉淀 `websearch`、`webfetch` 与后续 `webreader` 的职责边界、替换范围与分阶段改造方案。
- 仓库级 `README.md` 补充当前改造共识，明确本轮不是替换 `websearch`，而是将页面增强层从 `webfetch` 迁移到 `webreader`。
- 继续补充改造方案：明确 web 侧后续采用 `direct_read + search_discovery` 双通道，并约束框架适配所有类型、首批重点先做政府机关，政府 query 首批只聚焦 `办公地址` 与 `联系电话`。
- 补充 `webreader` 内部接口协议，纳入 `Jina-Reader` 与 `Tavily-Extract` 的网关地址、参数差异、输出差异与推荐接入策略。
- 收紧 `webreader` provider 调度策略：默认先用 `Jina` 对全部 URL 并行抓取，仅对失败 URL 再通过 `Tavily-Extract` 并行回退，以兼顾国内政府机关站点可达性与整体效率。

## [1.4.4] - 2026-04-03

### Changed
- Product `websearch_adapter.py` 调整为“两阶段并发”执行：先并行执行全部 `baidu` 查询，再仅对超时/无返回 query 并行回退 `tavily`，降低正式环境总等待时长。

## [1.4.3] - 2026-04-02

### Fixed
- Product `evidence-collection` 新增 reviewed gate 强约束，图商与 `websearch` 分支不再允许通过 `auto_generated` 或 raw 结果直接进入 formal evidence。
- Product `websearch` review 新增 `entity_relation` 收口规则，明确拦截“仅正文提到/站点导航命中/下属机构”这类弱相关页面。
- 修正 Product 成包脚本在 Python 3.9 下对 `Path.write_text(..., newline=...)` 的不兼容调用。

## [1.4.2] - 2026-04-01

### Added
- Product authority 分类灰区增加“规则候选 + 模型裁决”二阶段路径。
- Product 搜索代理参数新增 `count/time_range`，并支持计划层透传。

## [1.4.1] - 2026-04-01

### Fixed
- 修正 Product 内部搜索代理调用参数与协议不一致问题。
- 修正 websearch 全空结果在主控链路中的误失败判定，保持 evidence 可降级产出。
- 修正 authority metadata 缺失时的降权闭环，增强强主证据与弱辅证据区分。

## [1.4.0] - 2026-04-01

### Added
- Product 二期工程启动：`evidence-collection` 新增统一主控脚本，开始从三线并行演进到正式主线程序化编排。

### Changed
- Product 域文档与技能文档同步二期收敛路径，明确 `evidence_*.json` 对外 contract 不变。

## [1.3.0] - 2026-04-01

### Added
- Product 域新增 authority 分类推断模块与内部搜索代理适配模块（`websearch_adapter` / `internal_search_client`）。

### Changed
- Product 核验链路移除“低置信度即中断”的默认行为，改为结构化降级并持续产出正式 `decision`。
- Product 证据规范化补齐 authority 相关 metadata 最小 contract，支持后续码级分类判断。
- 同步更新 Product 域技能文档与仓库级 README/CHANGELOG 的流程描述。

## [1.2.0] - 2026-03-23

### Added
- 新增 `Develop/` 规划域，引入基于 Python Celery 的 `generate_batch` 与并发 `celery_worker`，实现异步抢占式并发调度下挂。
- 新增质检本地运行通道：向 `Quality/BigPoi-verification-qc` 注入 `LocalQCEngine`，完全接管 DSL 规则的计算，实现 0 令牌消耗。
- 在 `evidence-collection` 模型数据打发前增加地理坐标的 Haversine 算法预偏置及超长冗繁字段剔除脱水逻辑。

### Changed
- 重构 `evidence-collection` 底层基建，切换至 `aiohttp` 和 `asyncio` 并发框架，解决多图商串行高延迟阻塞痛点。
- 修改 `verification` 的写入落地脚本 `write_decision_output.py`，加入置信度熔断网关（总体置信度 < 0.85 抛错），从而触发后续大模型的重新深思回滚。
- 修改 `result_persister.py` 补充业务侧置信度的“动态拦截门禁”，对高分结果启动最高仅 5-20% 的抽检几率放行机制。

## [1.1.0]
- 初始化工作区级 `README.md`，明确 `Product / Quality` 双域结构、主流程和文档维护约定。
- 初始化工作区级 `CHANGELOG.md`，作为后续跨域文档与流程变更的统一入口。
- 初始化 `Quality/README.md` 与 `Quality/CHANGELOG.md`，补齐质量复核域入口文档。
- 初始化 `Quality/BigPoi-verification-qc/README.md`，补齐 QC 主技能说明。
- 初始化 `Quality/qc-write-pg-qc/CHANGELOG.md`，补齐 QC 回库技能变更记录入口。

### Changed
- 重写 `Product/README.md`，按当前 `Product/` 目录结构梳理四个核心技能、主流程、产物目录和回库链路。
- 重写 `Product/CHANGELOG.md` 顶部结构，使其能继续承接 Product 域后续迭代。
- 更新 `Quality/BigPoi-verification-qc/CHANGELOG.md` 顶部记录，补充本轮 README 初始化。
- 更新 `Quality/qc-write-pg-qc/README.md`，按当前目录与输入方式重写说明。

### Process
- 按文档维护约定先备份现有 README / CHANGELOG 到 `docs/backups/20260317-161404/`。
- 新增一份全量文档备份到 `docs/backups/20260317-175130-147/`，覆盖当前仓库内所有 `README.md / CHANGELOG.md`。

### Docs
- 在工作区级 README 中补充规则级文档层级说明，明确各规则目录下 `README.md` 的定位。
