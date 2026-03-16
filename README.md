# BigPOI Verification Skills

本仓库用于维护大 POI 核实技能及其父子技能脚本，覆盖证据收集、核实决策、结果成包与最终规格校验。

官方 Claude Code Skills 文档：<https://code.claude.com/docs/zh-CN/skills>

## 仓库内容

当前仓库包含三层技能：

- `skills-bigpoi-verification/`：父技能，负责编排证据收集、核实决策、结果成包、最终验收
- `evidence-collection/`：证据收集子技能，负责图商代理、图商补采、websearch/webfetch 归并与 evidence 文件输出
- `verification/`：核实子技能，负责维度判断与 decision 文件输出

正式脚本入口均已统一为 Python：

- `evidence-collection/scripts/*.py`
- `verification/scripts/write_decision_output.py`
- `skills-bigpoi-verification/scripts/write_result_bundle.py`
- `skills-bigpoi-verification/scripts/validate_result_bundle.py`
- `skills-bigpoi-verification/scripts/init_run_context.py`
- `skills-bigpoi-verification/scripts/runtime_paths.py`
- `skills-bigpoi-verification/scripts/run_context.py`
- `evidence-collection/scripts/run_context.py`
- `verification/scripts/run_context.py`

## Claude Code 技能配置方式

按照 Claude Code 官方规范，一个技能至少需要：

- 一个技能目录
- 一个 `SKILL.md`
- `SKILL.md` 顶部 YAML frontmatter 中的 `name` 和 `description`
- 可选的 `scripts/`、`references/`、`assets/`

推荐目录结构：

```text
<skill-name>/
├─ SKILL.md
├─ scripts/
├─ references/
└─ assets/
```

Claude Code 常见的两种技能放置方式：

1. 用户级技能目录：`~/.claude/skills/<skill-name>/SKILL.md`
2. 项目级技能目录：`<repo>/.claude/skills/<skill-name>/SKILL.md`

### 当前仓库与官方规范的对应关系

当前仓库保留的是技能源码目录，而不是已经放入 `.claude/skills/` 的安装态目录。

如果要让 Claude Code 直接发现并加载这些技能，建议按下面方式整理：

1. 为每个技能目录补齐或重命名为大写 `SKILL.md`
2. 将技能目录复制或链接到 `.claude/skills/` 下
3. 保持技能目录名与 frontmatter 中的 `name` 一致或可对应
4. 将脚本继续放在各自技能目录的 `scripts/` 下，避免跨技能相对路径失效

示例：

```text
.claude/
└─ skills/
   ├─ bigpoi-verification/
   │  ├─ SKILL.md
   │  ├─ scripts/
   │  ├─ config/
   │  └─ schema/
   ├─ evidence-collection/
   │  ├─ SKILL.md
   │  ├─ scripts/
   │  └─ config/
   └─ verification/
      ├─ SKILL.md
      ├─ scripts/
      └─ config/
```

### SKILL.md 编写要点

根据 Claude Code 官方规范，`SKILL.md` 应尽量保持精简，重点写：

- 这个技能做什么
- 什么时候触发使用
- 必须遵守的工作流约束
- 何时调用 `scripts/` 中的脚本
- 哪些 `references/` 需要按需读取

不建议把大段实现细节堆进 `SKILL.md`。格式稳定性要求高的部分，应下沉到脚本中。

这也是本仓库当前采用的做法：

- 输出格式敏感部分由 Python 脚本生成
- `skill.md` 只保留流程约束、输入输出契约、失败重试规则

## 本仓库的配置说明

### 1. 类型映射配置

父技能维护主类型映射：

- `skills-bigpoi-verification/config/poi_type_mapping.yaml`

用途：

- 将内部 6 位 `poi_type` 映射到白名单类目
- 供 `evidence-collection/scripts/build_web_source_plan.py` 解析类目配置
- 供 `verification` 在分类核对时保持内部类型码输出

### 2. 证据收集配置

证据收集按类目拆分配置：

- `evidence-collection/config/common.yaml`
- `evidence-collection/config/{category}.yaml`

用途：

- 定义权威网站来源
- 定义互联网来源
- 控制某类 POI 是否需要图商采集

当前 `build_web_source_plan.py` 会先读取 `poi_type_mapping.yaml`，再加载对应类目配置文件。

### 3. Schema 配置

父技能目录维护正式 schema：

- `skills-bigpoi-verification/schema/input.schema.json`
- `skills-bigpoi-verification/schema/evidence.schema.json`
- `skills-bigpoi-verification/schema/decision.schema.json`
- `skills-bigpoi-verification/schema/record.schema.json`

用途：

- 约束输入 POI 文件格式
- 约束 evidence / decision / record 正式产物格式
- 作为父子技能之间的交接契约

### 4. 结果输出目录

父技能正式输出目录：

```text
output/results/{task_id}/
```

正式文件命名：

- `decision_<timestamp>.json`
- `evidence_<timestamp>.json`
- `record_<timestamp>.json`
- `index_<timestamp>.json`

其中：

- `timestamp` 格式固定为 `yyyyMMddTHHmmssZ`
- 只有最终初筛并规范化后的正式证据文件才能命名为 `evidence_<timestamp>.json`
- 原始检索结果、抓取结果、图商原始结果、图商 review 结果和归并中间结果都属于过程文件，必须使用过程命名，例如 `websearch-raw-<timestamp>.json`、`webfetch-raw-<timestamp>.json`、`map-raw-<branch>-<timestamp>.json`、`map-reviewed-<branch>-<timestamp>.json`、`collector-merged-<timestamp>.json`
- 过程文件可以放在 `output/` 下，但不能进入最终 `index`，也不能冒用正式结果文件名
- `index` 为最终对外交付入口
- 最终必须通过 `validate_result_bundle.py` 校验

## 运行隔离

- 每条 POI 的一次 skill 执行都应生成独立 `run_id`
- 所有过程文件统一落在 `output/runs/{run_id}/process/` 与 `output/runs/{run_id}/staging/`
- `decision seed`、图商 raw/review、collector 中间结果都必须携带 `run_id`、`poi_id`、`created_at`

## 工作区路径推演

父技能结果落盘优先使用显式传入的 `WorkspaceRoot`；如果未传，则从 `workspace` 提示、输入文件路径和当前工作目录出发，向上逐级查找 `.claude`、`.openclaw`、`.git`，以最近命中的目录作为 `workspace_root`。最终结果固定落到 `workspace_root/output/results/{task_id}`。

当前正式结果合同保持不变：

- `index.task_dir` 仍为 `output/results/{task_id}`
- `index.files.*` 仍为绝对路径
- `validate_result_bundle.py` 会额外校验这些绝对路径必须位于探测到的 `workspace_root/output/results/{task_id}` 下

## 环境要求

### 必需环境

- Windows 或可运行等价 Python 3 命令的环境
- Python 3.10 及以上
- UTF-8 文件编码支持

当前仓库已按 Python 正式链路验证通过，验证环境示例：

- Python 3.14.2

### 网络要求

如果要跑真实采集链路，而不是 mock 数据，需要具备：

- 内部图商代理访问能力
- 外部地图服务 API 访问能力
- websearch / webfetch 所需的联网能力

如果只是本地验证 JSON 处理与结果成包，使用 mock 输入即可，无需真实联网。

### 凭证要求

图商补采脚本需要显式传入凭证：

- 高德：`key`
- 百度：`ak`
- 腾讯：`key`

当前正式脚本约束如下：

- `call_internal_proxy.py`：只接收 `city + poi name`
- `call_map_vendor.py`：只接收 `city + poi name + source + credential`

## 依赖说明

### 正式工作流依赖

当前正式工作流脚本仅依赖 Python 标准库，不依赖第三方包。

涉及模块主要包括：

- `argparse`
- `json`
- `pathlib`
- `datetime`
- `hashlib`
- `subprocess`
- `urllib`
- `re`
- `math`

因此在标准 Python 环境下即可运行以下正式脚本：

- `evidence-collection/scripts/build_web_source_plan.py`
- `evidence-collection/scripts/call_internal_proxy.py`
- `evidence-collection/scripts/call_map_vendor.py`
- `evidence-collection/scripts/write_map_relevance_review.py`
- `evidence-collection/scripts/merge_evidence_collection_outputs.py`
- `evidence-collection/scripts/write_evidence_output.py`
- `verification/scripts/write_decision_output.py`
- `skills-bigpoi-verification/scripts/write_result_bundle.py`
- `skills-bigpoi-verification/scripts/validate_result_bundle.py`

### 仓库内其他历史脚本依赖

仓库中仍有部分历史或辅助 Python 文件，可能使用额外依赖，例如：

- `requests`
- `PyYAML`

这些并不是当前正式产物链路的必需依赖；只有在继续使用历史脚本时才需要额外安装。

## 推荐执行顺序

### 证据收集

```bash
python evidence-collection/scripts/build_web_source_plan.py -PoiPath <input.json> -OutputPath <web-plan.json>
python skills-bigpoi-verification/scripts/init_run_context.py -InputPath <input.json> -WorkspaceRoot <repo-root>
python evidence-collection/scripts/call_internal_proxy.py -PoiName <poi-name> -City <city> -PoiId <poi-id> -TaskId <task-id> -RunId <run-id> -OutputPath <output/runs/{run_id}/process/map-raw-internal-proxy.json>
python evidence-collection/scripts/write_map_relevance_review.py -RawMapPath <map-raw.json> -ReviewSeedPath <map-review-seed.json> -OutputPath <output/runs/{run_id}/process/map-reviewed.json> -PoiId <poi-id> -TaskId <task-id> -RunId <run-id>
python evidence-collection/scripts/call_map_vendor.py -PoiName <poi-name> -City <city> -Source <amap|bmap|qmap> -PoiId <poi-id> -TaskId <task-id> -RunId <run-id> -OutputPath <output/runs/{run_id}/process/map-raw-vendor.json>
python evidence-collection/scripts/write_map_relevance_review.py -RawMapPath <vendor-fallback.json> -ReviewSeedPath <vendor-review-seed.json> -OutputPath <output/runs/{run_id}/process/map-reviewed-vendor.json> -PoiId <poi-id> -TaskId <task-id> -RunId <run-id>
python evidence-collection/scripts/merge_evidence_collection_outputs.py -PoiPath <input.json> -InternalProxyPath <map-reviewed-internal-proxy.json> -WebSearchPath <websearch.json> -WebFetchPath <webfetch.json> -VendorFallbackPaths <map-reviewed-vendor-a.json> <map-reviewed-vendor-b.json> -OutputPath <output/runs/{run_id}/process/collector-merged.json> -RunId <run-id> -TaskId <task-id>
python evidence-collection/scripts/write_evidence_output.py -PoiPath <input.json> -CollectorOutputPath <output/runs/{run_id}/process/collector-merged.json> -OutputDirectory <output/runs/{run_id}/staging> -RunId <run-id> -TaskId <task-id>
```

### 核实决策

```bash
python verification/scripts/write_decision_output.py -PoiPath <input.json> -EvidencePath <evidence-file.json> -DecisionSeedPath <output/runs/{run_id}/process/decision-seed.json> -OutputDirectory <output/runs/{run_id}/staging> -RunId <run-id> -TaskId <task-id>
```

### 结果成包与终检

```bash
python skills-bigpoi-verification/scripts/write_result_bundle.py -InputPath <input.json> -EvidencePath <evidence-file.json> -DecisionPath <decision.json> -WorkspaceRoot <repo-root>
python skills-bigpoi-verification/scripts/validate_result_bundle.py -TaskDir <output/results/{task_id}> -WorkspaceRoot <repo-root>
```

## 当前建议

如果后续要完全按 Claude Code 官方发现规则接入，建议继续做两件事：

1. 把三个技能目录中的 `skill.md` 统一重命名为 `SKILL.md`
2. 将技能目录整理到项目级 `.claude/skills/` 或用户级 `~/.claude/skills/` 下

## 回库稳定性约束

为了保证 `write-pg-verified` 能稳定写入正确成果，正式链路需要满足以下约束：

- `decision.overall.summary` 必须输出为稳定中文摘要，直接用于成果表 `verification_notes`。
- 只要核实结果包含建议修改，就必须在 `decision.corrections` 中提供对应的结构化修正，不能只写“建议修改 xxx”这类自然语言。
- 父技能生成 `record` 时，`record.verification_result.final_values` 必须严格反映 `decision.corrections` 中的最终建议值。
- `write-pg-verified` 使用 `record.verification_result.changes` 生成 `changes_made`，并使用 `record.verification_result.final_values` 写入成果字段。
## 地址与坐标维度拆分

从 `1.6.8` 开始，`verification` 子技能需要将地址和坐标分开判断：

- `decision.dimensions.address` 用于表达地址文本与行政区信息是否可信
- `decision.dimensions.coordinates` 用于表达坐标合法性、偏差距离与坐标系是否可信
- `decision seed.dimensions` 必须显式提供 `address` 和 `coordinates`，不允许只提供 `location` 由脚本自动拆解。
- `decision.dimensions.location` 如仍保留，仅作为兼容聚合维度，不再单独作为地址与坐标的唯一判断依据。

