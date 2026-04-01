# Product 一期迭代方案：Authority 分类增强与搜索代理接入

## 1. 背景

本轮迭代聚焦 `Product/` 的两条主线：

1. 效果提升：增强政府、公检法类 POI 的 `category` 类型维度核实能力。
2. 可用性与性能提升：将技能中依赖的 `websearch` 能力切换到内部搜索代理接口，适配当前正式模型环境无法直接使用原生 `websearch` 的限制。

### 1.1 效果提升背景

当前权力机关类 POI 的类型判断整体仍偏依赖图商证据，尤其是高德返回的类型码或类型标签。虽然取证层已经具备政府官网、政务平台、司法系统官网、百科等多源证据入口，但核实层尚未形成一套稳定的“综合多源信息 -> 判断具体 6 位内部类型码”的能力。

这会导致系统更擅长回答“它是不是政府/公检法机构”，而不够稳定地回答“它具体应该落成哪个内部类型码”。

### 1.2 搜索能力背景

当前正式使用的模型环境无法直接使用原生 `websearch`，导致现有 `websearch / webfetch` 流程在正式环境中的可执行性受限。为解决这一问题，已经提供了一个内部搜索代理服务，后续 `Product` 相关技能中的 `websearch` 查询应统一切换为调用该服务。

本轮约束如下：

- 搜索优先使用 `baidu`
- 当 `baidu` 无返回时，再回退使用 `tavily`
- 接口说明仅作为开发参考
- 代码与技能文档中不写入接口文档中的示例查询内容

## 2. 本轮目标

### 2.1 效果提升目标

1. 将权力机关类 POI 的 `category` 核实，从“大类匹配”升级为“具体内部类型码判断”。
2. 降低图商证据，尤其是高德类型码，对最终类型结论的单点决定作用。
3. 要求规则模块或模型辅助模块基于综合证据输出明确的内部类型码判断。
4. 当证据充分且与输入 `poi_type` 不一致时，输出结构化 `corrections.category`。
5. 当证据冲突或不足时，通过 `uncertain`、`downgraded`、`manual_review` 等结构化状态表达不确定性，而不是中断产出链路。

本轮覆盖范围包括：

- `government`：`130101` ~ `130106`
- `police`：`130501`
- `procuratorate`：`130502`
- `court`：`130503`

### 2.2 搜索能力目标

1. 将技能流程中使用的 `websearch` 统一切换为内部代理搜索接口。
2. 建立稳定的搜索适配层，屏蔽 `baidu` 与 `tavily` 的返回结构差异。
3. 优先调用 `baidu`，仅在 `baidu` 无结果时回退到 `tavily`。
4. 搜索输出统一转换为当前 `websearch` 分支可消费的 JSON 结构。
5. authority 判断所需的最小高价值信号，以受控方式保留在正式 `evidence` 的 `metadata` 中。

### 2.3 一期边界说明

本轮不以 `evidence-collection`、`opt1`、`opt3` 三版本统一收敛为交付目标，仅记录为后续二期工程演进方向，不影响本轮 authority 效果增强与搜索代理接入落地。

## 3. 范围定义

### 3.1 本轮范围内

- 权力机关类 POI 的 `category` 维度增强
- 官方站点 / 互联网 / 图商证据的综合解释能力
- 机构层级 / 机构类别的结构化推断
- 稳定输出 `corrections.category.suggested`
- 低置信度场景下的正式 `decision` 产出
- `websearch` 到内部搜索代理接口的统一适配
- `baidu -> tavily` 的回退策略
- authority 相关高价值信号在正式 `evidence.metadata` 中的最小保留
- 相关测试、Skill 文档、README、CHANGELOG 同步更新

### 3.2 本轮范围外

- 非权力机关类目的效果改造
- 数据库 schema 变更
- Quality 域规则改造
- 内部代理服务本身的后端实现
- `webfetch` 代理化
- `evidence-collection / opt1 / opt3` 三线合并落地

## 4. 当前现状判断

### 4.1 取证侧现状

当前取证配置已经具备权力机关类 POI 所需的核心证据源：

- [government.yaml](/Users/liubai/Documents/project/ft_project/datamalo/big_poi/Product/evidence-collection/config/government.yaml)
- [police.yaml](/Users/liubai/Documents/project/ft_project/datamalo/big_poi/Product/evidence-collection/config/police.yaml)
- [procuratorate.yaml](/Users/liubai/Documents/project/ft_project/datamalo/big_poi/Product/evidence-collection/config/procuratorate.yaml)
- [court.yaml](/Users/liubai/Documents/project/ft_project/datamalo/big_poi/Product/evidence-collection/config/court.yaml)

说明“证据入口不足”不是当前主要问题，主要问题是如何把多源证据稳定转化为正式核验可消费的结构化信号。

### 4.2 映射侧现状

内部类型码映射已经存在于：

- [poi_type_mapping.yaml](/Users/liubai/Documents/project/ft_project/datamalo/big_poi/Product/skills-bigpoi-verification/config/poi_type_mapping.yaml)

相关编码如下：

- `130101`：国家级机关及事业单位
- `130102`：省/直辖市级政府及事业单位
- `130103`：地市级政府及事业单位
- `130104`：区县级政府及事业单位
- `130105`：乡镇级政府及事业单位
- `130106`：乡镇以下级政府及事业单位
- `130501`：公安警察
- `130502`：检察院
- `130503`：法院

### 4.3 核实侧缺口

当前核实主脚本：

- [write_decision_output.py](/Users/liubai/Documents/project/ft_project/datamalo/big_poi/Product/verification/scripts/write_decision_output.py)

已经具备 `decision` 结构校验与落盘能力，但尚未具备稳定的 authority 类型推断能力，且当前实现存在低置信度直接中断流程的风险点，与本轮需求不一致。

### 4.4 搜索接入侧缺口

当前仓库已存在 `websearch / webfetch` 分支契约，但尚未看到一个正式落地的统一“内部搜索代理适配器”脚本，因此现有流程缺少稳定可执行的搜索实现入口。

## 5. 产品需求定义

### 5.1 authority 分类需求

对于政府、公安、检察院、法院这四类权力机关 POI，核实阶段不应再默认把图商返回的类型信息视为主要真值来源。

理想行为应为：

1. 读取输入 POI 与正式 `evidence_*.json`
2. 从官方站点、互联网文本、图商结果中提取机构类别和层级信号
3. 综合判断最可能的内部类型码
4. 给出该判断成立的原因和证据引用
5. 当推断结果与输入 `poi_type` 不一致且置信度足够高时，写出 `corrections.category`
6. 当证据不足或冲突明显时，输出 `uncertain` 或 `manual_review`，避免强判

### 5.2 低置信度 decision 产出约束

本轮 authority 增强不以“高置信度才允许写 decision”为前提。

即使 authority 类 `category` 维度未达到高置信度，也必须输出正式 `decision_*.json` 文件，并通过 `downgraded`、`manual_review`、`uncertain` 等结构化状态表达不确定性，而不是直接中断产出链路。

约束如下：

- authority 低置信度场景不得仅通过异常中断流程
- `dimensions.category.result` 允许为 `uncertain`
- `overall.status` 应根据具体场景落为 `downgraded` 或 `manual_review`
- 仅在证据充分且推断码与输入码冲突时，才输出 `corrections.category`

迁移原则如下：

- 一期应移除“低置信度直接 hard fail 阻断正式 decision 写出”的主流程行为
- 若当前链路仍需要保留 reroute / fallback 提示信息，应以结构化方式写入正式 `decision`
- 不再以抛异常作为 authority 低置信度场景的默认主路径
- `manual_review` 与 `downgraded` 是合法正式结果，不应被视为失败产物

### 5.3 authority 正式输入边界

authority 类型推断模块的正式输入仅为：

- 输入 POI 文件
- 正式 `evidence_*.json`

不将过程文件作为 authority 正式判断的依赖输入。

若 authority 推断需要更多信号，应通过 evidence 规范化增强，在正式 `evidence` 中保留受控信息，而不是绕过正式产物直接读过程工件。

### 5.4 搜索能力需求

后续技能中的 `websearch` 必须统一通过内部代理服务完成，不再依赖原生 `websearch`。

理想行为应为：

1. 根据 `web-plan.json` 中的 `official_sources` 和 `internet_sources` 逐项执行查询
2. 每个查询默认优先调用 `baidu`
3. 当 `baidu` 返回空结果时，自动回退调用 `tavily`
4. 对不同来源返回结构做统一转换
5. 产出可被现有归并流程消费的 `websearch` 原始 JSON 文件
6. 在过程结果中保留本次查询实际使用的 provider 信息

## 6. 建议方案

### 6.1 新增 authority 类型推断增量模块

建议在 `Product/verification/scripts/` 下新增 authority 类型推断模块。

本轮建议采用增量接入方式，在 `verification` 现有决策生成逻辑中插入 authority 分类推断能力，不建议在本轮重写整个 `verification` skill 的输入输出结构。

该模块只负责：

- `category` 维度增强
- `category.details` 结构化理由补充
- `corrections.category` 生成

不改变其他维度主逻辑。

### 6.2 分家族处理推断逻辑

#### 6.2.1 家族优先级建议

研发落地时，建议优先完成 `police`、`procuratorate`、`court` 的稳定识别与单码判断，再完成 `government` 的 6 级层级细分。

原因是公检法单码判断的规则边界更清晰，适合作为 authority 模块的第一批稳定场景。

#### 6.2.2 政府机关

候选码：

- `130101`
- `130102`
- `130103`
- `130104`
- `130105`
- `130106`

核心判定信号包括：

- `国务院`
- `XX省人民政府`
- `XX市人民政府`
- `XX区人民政府`
- `XX县人民政府`
- `XX乡人民政府`
- `XX镇人民政府`
- `街道办事处`
- `社区居民委员会`
- `村民委员会`
- 官网域名与门户层级
- 页面标题、机构职能、主办单位、行政区划等文本信号
- 名称和地址中的行政层级关键词

#### 6.2.3 公安机关

目标码：

- `130501`

核心信号包括：

- `公安部`
- `公安厅`
- `公安局`
- `派出所`
- 公安系统官网域名，如 `mps.gov.cn`、`gat.*.gov.cn`、`gaj.*.gov.cn`

#### 6.2.4 检察院

目标码：

- `130502`

核心信号包括：

- `人民检察院`
- `检察院`
- 检察系统官网域名，如 `spp.gov.cn`、`*.jcy.gov.cn`

#### 6.2.5 法院

目标码：

- `130503`

核心信号包括：

- `人民法院`
- `高级人民法院`
- `中级人民法院`
- `基层人民法院`
- 法院系统官网域名，如 `court.gov.cn`、`chinacourt.gov.cn`

### 6.3 采用多源加权而不是单源采纳

建议证据优先级如下：

1. `official`
2. `internet`
3. `map_vendor`
4. `other`

建议判定原则如下：

- 官方文本证据可以覆盖图商给出的类型提示
- 图商结果可作为辅证，但不应在存在强官方证据时单独决定最终类型码
- 互联网证据可用于增强或削弱官方判断，但原则上不应单独推翻强官方证据

### 6.4 规则优先、灰区模型裁决

模型不得自由生成类型码。

规则层应先产出：

- 候选码集合
- 候选理由
- 证据引用
- 冲突点摘要

模型输入必须包含以上内容。

模型输出必须返回：

- `selected_code`
- `confidence`
- `reason`
- `evidence_refs`

约束如下：

- 模型不得输出候选集合之外的编码
- 模型不得直接输出中文类别名替代内部类型码
- 若模型仍无法确定，应返回 `uncertain`，而不是强行选择

### 6.5 接入决策输出

authority 推断结果需要接入以下字段：

- `dimensions.category.result`
- `dimensions.category.confidence`
- `dimensions.category.details`
- `corrections.category`

建议映射关系如下：

- `category = pass` 且置信度高：进入正常 `accepted / downgraded` 评估
- `category = uncertain`：建议整体降级，但不阻断 `decision` 产出
- `category = fail` 且证据充分：允许写 `corrections.category`
- `category = fail` 且证据不足：优先 `manual_review`，不强写 `correction`

注意：

- `dimensions.category.result = pass` 不等于 `overall.status = accepted`
- authority 类 `category` 即便为 `uncertain`，只要其他核心维度可用，也应允许整体决策产出 `downgraded` 或 `manual_review`

建议在 `details` 中保留：

- `expected_value`
- `observed_value`
- `institution_family`
- `level_label`
- `reason`
- `evidence_refs`
- `source_breakdown`

### 6.6 新增搜索代理适配层

建议在 `Product/evidence-collection/scripts/` 下新增统一的搜索适配脚本或模块，用于承接 `websearch` 分支。

建议模块职责如下：

- `internal_search_client.py`
  - 封装内部搜索代理接口调用
  - 封装 `baidu` 查询
  - 封装 `tavily` 查询
- `websearch_adapter.py`
  - 编排 provider 优先级与回退逻辑
  - 统一结果结构
  - 输出 `websearch-raw-*.json`

该搜索代理适配层与现有图商内部代理能力属于两套不同能力，不共用职责语义，文档和实现命名应明确区分，避免误读为图商代理扩展。

### 6.7 Provider 调用策略

建议固定以下策略：

1. 先调用 `baidu`
2. 若 `baidu` 返回结构合法但结果为空，则回退调用 `tavily`
3. 若 `baidu` 调用失败，按可恢复错误处理策略回退 `tavily`
4. 若 `tavily` 也失败，则返回标准化错误结果并由上游决定是否降级或重试

“无返回”的判定标准建议为：

- `baidu.references` 不存在
- `baidu.references` 为空数组
- `baidu.references` 经过标准化过滤后无有效结果

### 6.8 搜索结果标准化

建议对 `baidu` 和 `tavily` 做统一转换，至少产出以下字段：

- `url`
- `title`
- `content`
- `published_at`
- `source_name`
- `source_type`
- `provider`
- `rank`

统一后的过程文件结构建议包含：

- `status`
- `provider_attempts`
- `effective_provider`
- `query`
- `result_count`
- `items`
- `context`

### 6.9 正式 evidence 的 authority 信号保留策略

为支持政府 / 公检法类 POI 的层级与机构类型判断，正式 `evidence` 允许在 `metadata` 中保留少量高价值辅助信息。

这些字段仅用于核验推断，不改变 `evidence` 主结构语义。

要求如下：

- 不保留整页原始网页
- 不保留全量搜索原始响应
- 不保留 HTML 全文等高噪音信息
- authority 所需补充信息统一进入 `metadata`
- 不直接扩张 `data.name / data.address / data.category` 等核心业务字段
- metadata 设计应为“分支无关 contract”，而不是仅服务于 `websearch`

建议统一字段如下：

- `metadata.signal_origin`
- `metadata.source_domain`
- `metadata.page_title`
- `metadata.text_snippet`
- `metadata.level_hint`
- `metadata.authority_signals`

### 6.9.1 authority metadata 最小 contract

为避免研发和测试对字段依赖理解不一致，一期建议采用如下最小 contract。

| 字段名 | 可能来源分支 | 是否必填 | 缺失处理 | 字段语义 |
|---|---|---|---|---|
| `metadata.signal_origin` | `websearch` / `webfetch` / `map_vendor` | 是 | 若缺失则该 evidence 不作为 authority 推断主证据，仅可作为弱辅证 | 标记 authority 信号来自哪个分支 |
| `metadata.source_domain` | `websearch` / `webfetch` | 官方源建议必填，其他可选 | 官方源缺失时降低该条 evidence 对 authority 的权重 | 页面或来源域名，如 `gov.cn`、`court.gov.cn` |
| `metadata.page_title` | `websearch` / `webfetch` | 推荐必填 | 缺失时可退化为仅使用 snippet / name / address 信号 | 页面标题或正文主标题 |
| `metadata.text_snippet` | `websearch` / `webfetch` / `map_vendor` | 推荐必填 | 缺失时 authority 模块不得假设正文存在，应降级使用其他信号 | 受控长度的文本摘要，不保留原始全文 |
| `metadata.level_hint` | `websearch` / `webfetch` / 规则归一化 | 可选 | 缺失时由 verification 自行做关键词推断 | 结构化层级提示，如省级、地市级、区县级 |
| `metadata.authority_signals` | `websearch` / `webfetch` / `map_vendor` | 可选 | 缺失时不影响 evidence 合法性，但会降低 authority 推断可解释性 | 命中的机构关键词、层级关键词、组织形态信号 |

补充约束如下：

- `websearch` 分支至少应尽量补齐：`signal_origin`、`source_domain`、`page_title` 或 `text_snippet`
- `webfetch` 分支至少应尽量补齐：`signal_origin`、`source_domain`、`page_title`、`text_snippet`
- `map_vendor` 分支至少应尽量补齐：`signal_origin`，并在可能时补充 `text_snippet` 或 `authority_signals`
- 若单条 evidence 缺少 authority 所需 metadata，不应导致 evidence 失效，但 verification 需降低其权重或仅作为辅证
- verification 不应假设所有分支都能补齐全部 metadata 字段

示例值约束：

- `metadata.signal_origin`: `websearch` / `webfetch` / `map_vendor`
- `metadata.source_domain`: `www.gov.cn`
- `metadata.page_title`: `某某市人民政府`
- `metadata.text_snippet`: `主办单位为某某市人民政府办公室`
- `metadata.level_hint`: `地市级`
- `metadata.authority_signals`: `["人民政府", "主办单位", "地市级"]`

### 6.10 与现有 skill 契约的兼容要求

本轮改造不应破坏现有主流程契约：

- authority 判断只依赖正式 `evidence_*.json`
- `websearch` 仍输出过程 JSON 文件
- `webfetch` 本轮仍由模型处理，不属于本轮代理化范围
- `decision`、`record`、`index` 的正式 schema 不做破坏性改动

### 6.11 从 Skill 视角的改造建议

从 skill 演进的角度看，本轮建议将新增能力内聚回已有 skill 的职责边界中：

- `evidence-collection`
  - 增加内部搜索代理适配能力
  - 增加 authority 高价值信号的 evidence metadata 保留能力
- `verification`
  - 增加 authority 分类推断能力
  - 采用规则优先、灰区模型裁决
  - 低置信度场景也必须产出正式 `decision`
- `skills-bigpoi-verification`
  - 不负责 authority 猜码
  - authority 分类修正以 `verification` 正式输出为准
  - 低置信度 `decision` 依然是合法正式产物，父 skill 不应因 `manual_review` 而判定失败

## 7. 开发计划

### 第一阶段：contract 与规则设计

1. 明确低置信度 authority 场景也必须产出正式 `decision`
2. 明确 authority 规则优先、灰区模型裁决
3. 明确 formal evidence metadata 的最小补充字段
4. 明确 `category -> overall.status` 的映射约束

### 第二阶段：搜索代理适配实现

1. 新增 `internal_search_client.py`
2. 新增 `websearch_adapter.py`
3. 实现 `baidu -> tavily`
4. 标准化 `websearch-raw-*.json`
5. 将 authority 所需的高价值信号受控写入正式 `evidence.metadata`

### 第三阶段：authority 分类能力实现

1. 新增 authority 推断模块
2. 接入 `verification`
3. 补齐 `category.details`
4. 产出 `corrections.category`
5. 去除“低置信度直接中断 decision 产出”的行为

### 第四阶段：测试与文档同步

1. authority 分类规则测试
2. 搜索回退测试
3. decision 降级产出测试
4. evidence metadata 保留策略测试
5. 更新 3 个 `SKILL.md`
6. 更新 [Product/README.md](/Users/liubai/Documents/project/ft_project/datamalo/big_poi/Product/README.md)
7. 更新 [Product/CHANGELOG.md](/Users/liubai/Documents/project/ft_project/datamalo/big_poi/Product/CHANGELOG.md)

## 8. 验收方案

### 8.1 功能验收

满足以下条件方可视为通过：

1. 政府类 POI 能够输出精确码级别判断，而不是仅停留在大类匹配
2. 公安 / 检察院 / 法院不再仅依赖图商类型结果做类别判断
3. 当官方证据明确指向不同类型码时，系统能够输出合法的 `corrections.category`
4. 当证据不足或冲突明显时，系统能输出 `uncertain` 或 `manual_review`，而不是硬判
5. 最终 `decision`、`record` 与结果包结构保持兼容

### 8.2 强约束验收

1. 低置信度 authority 场景必须能生成正式 `decision_*.json`
2. authority 判断所依赖的补充信号必须以受控字段形式进入正式 `evidence.metadata`
3. authority 正式核验不依赖过程文件
4. `webfetch` 本轮仍保持原有方式处理，不混入本轮代理化交付

### 8.3 样本验收

建议至少覆盖以下样本：

- `XX省人民政府` -> `130102`
- `XX市人民政府` -> `130103`
- `XX区人民政府` / `XX县人民政府` -> `130104`
- `XX镇人民政府` -> `130105`
- `XX街道办事处` / `XX社区居民委员会` -> `130106`
- `XX市公安局` -> `130501`
- `XX区人民检察院` -> `130502`
- `XX市中级人民法院` -> `130503`

### 8.4 搜索接入验收

1. `websearch` 已切换为通过内部代理接口执行
2. 查询默认优先使用 `baidu`
3. `baidu` 无结果时能自动回退 `tavily`
4. `baidu` 与 `tavily` 返回内容会被统一转换为当前流程可消费结构
5. 过程结果中能追踪 provider 选择与回退路径
6. provider 选择顺序由 Python 固定逻辑控制，而不是由模型临场决定

### 8.5 回归验收

本轮改造不能出现以下问题：

- 非预期破坏现有输出 schema
- 影响非权力机关类目的处理效果
- 静默移除图商证据，只保留文本证据
- 在要求 6 位码的地方输出中文类别名替代
- `websearch` 过程结果结构发生非预期破坏
- `baidu` 无结果时未触发 `tavily` 回退
- 代码中出现接口文档里的示例查询内容

## 9. 风险与缓解

### 风险 1：authority 规则需要的正式信号不足

缓解方式：

- 优先补正式 `evidence.metadata` 的最小高价值字段
- 不绕过正式 evidence 直接读取过程文件

### 风险 2：低置信度场景继续沿用中断式逻辑

缓解方式：

- 在 contract 和验收中明确“低置信度也必须产出正式 decision”
- 以 `downgraded / manual_review / uncertain` 表达不确定性

### 风险 3：政府层级边界容易混淆

缓解方式：

- 明确区分省级、地市级、区县级、乡镇级、乡镇以下级关键词字典
- 优先落地公检法单码场景，再补政府 6 级细分

## 10. 本轮交付物

本轮最终应交付：

- `Product/verification/` 下 authority 分类增强实现
- `Product/evidence-collection/` 下搜索适配实现
- 正式 `evidence.metadata` 的 authority 高价值信号保留增强
- `Product/tests/` 下规则与适配层测试
- 更新相关 skill 文档与 Product 域文档

二期工程建议单独记录，不混入本轮交付项。
