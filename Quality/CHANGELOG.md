# Quality CHANGELOG

## [1.2.0] - 2026-03-23

### Added
- 为质检域的执行器打入零开销拦截层。在 `BigPoi-verification-qc` 内新增纯代码接管及按置信度的动态抽检跳过逻辑，极大程度阻断上游输入进入全量大模型查验。

## [1.1.0]
- 初始化 `Quality/README.md`，补齐 QC 域职责、模块关系与主流程。
- 初始化 `Quality/CHANGELOG.md`，作为 QC 域统一变更入口。
- 初始化 `BigPoi-verification-qc/README.md`，补齐 QC 主技能说明。
- 初始化 `qc-write-pg-qc/CHANGELOG.md`，补齐 QC 回库技能变更入口。

### Changed
- 更新 `qc-write-pg-qc/README.md`，按当前输入模式、索引发现和回库映射重新整理说明。
- 更新 `BigPoi-verification-qc/CHANGELOG.md` 顶部记录，纳入本轮文档初始化。
- 补充 Quality 域 README 的规则级文档维护要求。
