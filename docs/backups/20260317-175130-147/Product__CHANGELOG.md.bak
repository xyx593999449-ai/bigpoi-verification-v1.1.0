# Product CHANGELOG

## [Unreleased]

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

