# Product 二期工程规划：evidence-collection 三线收敛与主控统一

## 1. 规划背景

当前项目中与证据收集相关的目录有三个：

- [Product/evidence-collection](/Users/liubai/Documents/project/ft_project/datamalo/big_poi/Product/evidence-collection)
- [Product/evidence-collection-opt1](/Users/liubai/Documents/project/ft_project/datamalo/big_poi/Product/evidence-collection-opt1)
- [Product/evidence-collection-opt3](/Users/liubai/Documents/project/ft_project/datamalo/big_poi/Product/evidence-collection-opt3)

从当前仓库实现看，这三者并不是三套完全独立的引擎，而更像是：

- 正式版主线
- 子 Agent 并行执行说明版
- 程序化编排实验版

一期迭代已明确：

- 本轮只做 authority 分类增强
- 本轮只做 `websearch` 搜索代理化
- 不做 evidence-collection 三线收敛落地

因此，本文件用于单独记录二期工程治理方向，避免与一期交付目标混淆。

## 2. 二期目标

二期工程目标如下：

1. 将 `Product/evidence-collection/` 收敛为唯一正式主线目录。
2. 吸收 `opt3` 的程序化 orchestrator 思路进入正式版，但不再以“纯 Python 一把梭”作为正式终态。
3. 将图商、`websearch`、`webfetch`、补采、重试统一纳入“计划驱动的 skill 编排 + Python worker + 模型 review 节点”架构。
4. 逐步淘汰 `opt1` 和 `opt3` 作为长期并行变体的角色。
5. 保持正式 `evidence_*.json` contract 稳定，不因主控统一而破坏下游兼容性。

## 3. 当前判断

### 3.1 三版本差异

当前差异主要体现在：

1. `evidence-collection` 与 `opt1` 的代码实现基本一致，差异主要在 `SKILL.md` 的执行方式描述。
2. `opt3` 在此基础上新增了程序化主控脚本：
   - [orchestrate_collection.py](/Users/liubai/Documents/project/ft_project/datamalo/big_poi/Product/evidence-collection-opt3/scripts/orchestrate_collection.py)
3. 当前 `opt3` 还没有真正把 `websearch` 和 `webfetch` 纳入统一程序调度，Web 分支仍依赖外部 Agent 协同。

### 3.2 工程判断

从长期工程演进角度判断：

- 单纯依赖子 Agent 自由协作，不够稳定
- 单纯由 Python 程序从 raw 直接跑到 formal evidence，也不够正确
- 更合理的方向是：顶层由 skill 按计划编排，Python 负责确定性节点，模型负责 review 节点

原因如下：

1. provider 顺序、回退、重试、本地落盘、上下文绑定，本质上都是确定性工程逻辑。
2. 这些逻辑由 Python 主控统一编排时，更容易保证：
   - 执行顺序稳定
   - 错误处理一致
   - 日志清晰
   - 过程文件完整
   - 回归测试可重复
3. 但 `websearch` 与 `webfetch` 的语义抽取和相关性判断，不应继续由纯规则脚本直接生成 formal evidence，必须显式纳入模型 review 阶段。
4. 因此，二期的核心不是把 Python orchestrator 做得更大，而是把模型 review 阶段变成主流程中的正式节点。

详细设计见：

- [Product_phase2_detailed_design_plan_driven_evidence_collection_20260401.md](/Users/liubai/Documents/project/ft_project/datamalo/big_poi/docs/Product_phase2_detailed_design_plan_driven_evidence_collection_20260401.md)

### 3.3 对 opt3 的现实定位

`opt3` 当前可以作为“主控雏形参考”，但不能视为可直接并入正式版的半成品。

原因如下：

1. 当前 `opt3` 中的 [orchestrate_collection.py](/Users/liubai/Documents/project/ft_project/datamalo/big_poi/Product/evidence-collection-opt3/scripts/orchestrate_collection.py) 实际上只并发拉起了图商内部代理分支。
2. `websearch` 与 `webfetch` 在现有 `opt3` 中仍停留在说明和占位层面，尚未纳入统一程序调度。
3. 因此，`opt3` 目前只能提供“程序化主控形态”的参考，而不能低成本直接升级为正式 orchestrator。

这意味着二期如果推进主控统一，仍需重新设计和补齐：

- `websearch` 接入
- `webfetch` 接入
- 分支上下文统一
- 失败恢复
- 补采控制
- 结果落盘与日志治理

研发排期时应按“重构和补全 orchestrator 能力”估算，而不是按“并入现有 opt3 脚本”估算。

## 4. 是否保证结果一致

这三种方案在“技能契约”层面目标一致，但不天然保证“执行结果完全一致”。

一致的部分：

- 最终都以 `evidence_*.json` 作为正式产物
- 最终都依赖相同的归并与规范化脚本 contract

不一致的部分：

- 并发执行的时机可能不同
- `websearch / webfetch` 分支的执行实现可能不同
- review seed 生成时机和补采时机可能不同
- 过程文件完整性和失败恢复策略可能不同

因此，更准确的判断是：

- 正式输出 contract 一致
- 工程执行过程不一致
- 最终 evidence 结果不保证天然一致

## 5. 二期推荐收敛路线

### 5.1 目录主线收敛

1. 保留 [Product/evidence-collection](/Users/liubai/Documents/project/ft_project/datamalo/big_poi/Product/evidence-collection) 作为唯一正式主线目录。
2. 不再把 `opt1` 作为长期演进目标，仅作为历史并行协作思路参考。
3. 不直接把 `opt3` 目录整体升级为正式版，而是吸收其“程序化 orchestrator”思路进入正式版。

### 5.2 主控统一方向

建议在正式版中采用“计划驱动式统一主控”：

- 顶层 skill 生成 `collection-plan.json`
- Python 脚本负责 raw、reviewed 落盘、merge、formal evidence
- 模型节点负责图商相关性判断、`websearch` 抽取、`webfetch` 页面理解
- merge 只吃 reviewed 文件

### 5.3 搜索与抓取统一方向

二期可继续评估：

- `websearch` 已在一期完成代理化接入后的进一步统一调度方式
- `webfetch` 是否需要代理化或程序化抓取增强
- `websearch + webfetch + map` 三分支的统一重试与回退策略

## 6. 二期实施原则

- 不长期维护三套 evidence-collection 变体
- 对外保持正式产物 contract 不变
- 对内采用计划驱动式 skill 编排
- 让 provider 路由、分支调度、补采和重试落到 Python worker
- 让语义判断、字段抽取、页面理解进入显式 model review 节点

## 7. 二期建议阶段划分

### 第一阶段：主线方案定稿

1. 明确正式版主线目录
2. 明确 `opt1 / opt3` 的保留策略
3. 明确 orchestrator 输入输出 contract

### 第二阶段：计划文件与 reviewed gate 落地

1. 定义 `collection-plan.json`
2. 定义三类 review seed schema
3. 定义 reviewed-only merge 约束

### 第三阶段：模型 review 节点并入正式版

1. 图商线接入相关性 review
2. `websearch` 线接入 review + extract
3. `webfetch` 线接入页面理解节点

### 第四阶段：失败恢复与重试统一

1. 统一补采时机
2. 统一重试机制
3. 统一分支失败回退策略

### 第五阶段：目录与文档治理

1. 调整相关 `SKILL.md`
2. 调整 Product 域文档
3. 明确 `opt1 / opt3` 的历史定位或退役方案

## 8. 二期验收方向

二期完成后，建议满足以下条件：

1. `Product/evidence-collection/` 成为唯一正式演进主线。
2. 正式版吸收程序化 orchestrator 能力。
3. `websearch`、图商、补采、后续 `webfetch` 能纳入统一程序调度框架。
4. 正式 `evidence_*.json` 输出 contract 保持兼容。
5. 不再建议长期维护三套并行 evidence-collection 变体。
