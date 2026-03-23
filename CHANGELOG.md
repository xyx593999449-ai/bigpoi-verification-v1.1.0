# Changelog

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
