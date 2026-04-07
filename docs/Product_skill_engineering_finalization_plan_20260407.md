# Product 技能工程化收尾方案（2026-04-07 定稿）

## 1. 文档目标

本文档用于确认 `Product/` 目录后续工程化重构的最终方案，目标是把 Product 域内容收敛为符合 Claude Code 官方规范、可持续维护、可逐步迁移的技能包结构。

本次定稿遵循以下约束：

- 父技能 `skills-bigpoi-verification` 名称不变。
- 证据收集主调度 skill 保持 `evidence-collection`。
- 证据收集拆成 4 个正式 skill，并统一使用连字符 `-` 命名。
- 共享 Python 公共模块不单独拆出新顶级目录，统一放在 `evidence-collection/scripts/` 下。
- 最终方案以工程可迁移、调用改动最小、文档引用可校验为优先，而不是做抽象最彻底的理论分层。

## 2. 命名定稿

### 2.1 保持不变的技能

- `skills-bigpoi-verification`
- `verification`
- `write-pg-verified`

### 2.2 证据收集技能命名

- `evidence-collection`
- `evidence-collection-web`
- `evidence-collection-map`
- `evidence-collection-merge`

说明：

- `evidence-collection` 仍作为父技能感知的唯一证据收集入口。
- 父技能不直接调用 `web` / `map` / `merge` 三个子技能。
- 子技能仅作为 `evidence-collection` 的内部编排单元存在。

## 3. 最终推荐目录结构

```text
Product/
├── README.md
├── CHANGELOG.md
├── skills-bigpoi-verification/
│   ├── SKILL.md
│   ├── scripts/
│   ├── schema/
│   └── config/
├── evidence-collection/
│   ├── SKILL.md
│   ├── scripts/
│   │   ├── run_parallel_claude_agents.py
│   │   ├── evidence_collection_common.py
│   │   └── run_context.py
│   ├── references/
│   └── examples/
├── evidence-collection-web/
│   ├── SKILL.md
│   ├── scripts/
│   ├── prompts/
│   ├── config/
│   └── references/
├── evidence-collection-map/
│   ├── SKILL.md
│   ├── scripts/
│   ├── prompts/
│   ├── config/
│   └── references/
├── evidence-collection-merge/
│   ├── SKILL.md
│   ├── scripts/
│   └── references/
├── verification/
│   ├── SKILL.md
│   ├── scripts/
│   ├── config/
│   └── rules/
└── write-pg-verified/
    ├── SKILL.md
    ├── scripts/
    └── config/
```

## 4. 四个证据收集 skill 的职责边界

### 4.1 `evidence-collection`

职责：

- 初始化 `run_id` / `task_id` / 运行目录。
- 调用 `run_parallel_claude_agents.py`。
- 并发拉起：
  - `evidence-collection-web`
  - `evidence-collection-map`
- 等待两个分支结果落盘：
  - `web-branch-result.json`
  - `map-branch-result.json`
- 调用 `evidence-collection-merge`。
- 最终只返回正式 `evidence_path`。

额外约束：

- 主调度仍然是父技能对接的唯一入口。
- `evidence-collection` 不直接做原始 web/map 采集细节。

### 4.2 `evidence-collection-web`

职责：

- 生成 web 计划。
- 优先使用 Claude 内置 `WebSearch` 做候选页面发现。
- 若当前运行环境无内置 `WebSearch`，再回退内部代理 Python 脚本。
- 优先使用 Claude 内置 `WebFetch` 做页面读取。
- 若当前运行环境无内置 `WebFetch`，再回退内部代理 Python 脚本。
- 执行 `websearch-reviewed` 与 `webreader-reviewed` 的 review / validate / write 流程。
- 输出 `web-branch-result.json`。

### 4.3 `evidence-collection-map`

职责：

- 调用内部图商代理。
- 仅对 `missing_vendors` 执行缺失图商补采。
- 执行 map review seed 准备、校验与 reviewed 写出。
- 输出 `map-branch-result.json`。

### 4.4 `evidence-collection-merge`

职责：

- 读取 `web-branch-result.json` 与 `map-branch-result.json`。
- 执行 reviewed-only merge。
- 调用正式 evidence 写出脚本。
- 输出：
  - `collector-merged.json`
  - `evidence_*.json`
  - `evidence-merge-result.json`

## 5. 脚本归位方案

### 5.1 放入 `evidence-collection/scripts/`

- `run_parallel_claude_agents.py`
- `evidence_collection_common.py`
- `run_context.py`

说明：

- `evidence_collection_common.py` 与 `run_context.py` 作为证据收集链路的共享 Python 公共模块，不单独拆顶级 `shared-*` 目录。
- 其角色属于“主调度 skill 的共享支持文件”。
- `web` / `map` / `merge` 三个子技能允许通过显式路径注入方式复用它们。

### 5.2 放入 `evidence-collection-web/scripts/`

- `build_web_source_plan.py`
- `websearch_adapter.py`
- `build_webreader_plan.py`
- `webreader_adapter.py`
- `prepare_websearch_review_input.py`
- `validate_websearch_review_seed.py`
- `write_websearch_review.py`
- `prepare_webreader_review_input.py`
- `validate_webreader_review_seed.py`
- `write_webreader_review.py`
- `internal_search_client.py`

### 5.3 放入 `evidence-collection-map/scripts/`

- `call_internal_proxy.py`
- `call_map_vendor.py`
- `prepare_map_review_input.py`
- `validate_map_review_seed.py`
- `write_map_relevance_review.py`

### 5.4 放入 `evidence-collection-merge/scripts/`

- `merge_evidence_collection_outputs.py`
- `write_evidence_output.py`

## 6. 共享模块放在 `evidence-collection` 的原因

本次定稿明确：

- 不单独再建 `shared-evidence-lib/`。
- 共享 Python 公共代码统一放在 `evidence-collection/scripts/` 中。

原因如下：

1. 当前阶段目标是工程化收尾，而不是平台级抽象。
2. `evidence-collection` 本身就是证据收集主入口，把共用代码放在其下更符合团队直觉。
3. 可以减少顶级目录数量，降低重构后的认知成本。
4. 对现有文档、脚本和调用链的改动更小。

风险控制要求：

- 所有子技能脚本如果依赖共享模块，必须统一采用稳定的 `sys.path` 注入方式，不允许散乱复制公共代码。

## 7. Claude Code 规范对齐要求

本次重构需要遵循 Claude Code 官方 skill 规范：

- 每个 skill 目录必须有 `SKILL.md`。
- 任务型 skill 统一使用 `disable-model-invocation: true`。
- `SKILL.md` 保持聚焦，长说明移入 `references/`。
- 对工具权限要求明确的 skill，尽量在 frontmatter 中增加 `allowed-tools`。
- 复杂主控 skill 可以使用 `context: fork`，但本次主线优先走 Python worker + `claude -p` 编排，不依赖运行时 subagent 自动编排。

参考：

- Claude Code Skills 文档：<https://code.claude.com/docs/zh-CN/skills>

## 8. 文档工程化要求

### 8.1 Product 域 README

`Product/README.md` 应只保留：

- Product 域正式技能列表
- `skills-bigpoi-verification` 与 `evidence-collection` 的对接关系
- 证据收集四个 skill 的职责概览
- 结果目录与正式输出规范
- 指向本文档的入口链接

### 8.2 各 skill 的 `SKILL.md`

每个 `SKILL.md` 只保留：

- 目标
- 输入
- 输出
- 可执行脚本
- 不允许做的事
- 支持文件位置

### 8.3 references

长说明移入各 skill 的 `references/`，例如：

- `evidence-collection/references/runtime-contract.md`
- `evidence-collection-web/references/web-raw-reviewed-contract.md`
- `evidence-collection-map/references/vendor-fallback-rules.md`
- `evidence-collection-merge/references/merge-contract.md`

## 9. 文档引用与路径校验方案

建议新增校验脚本：

- `Product/scripts/check-product-skill-refs.py`

校验范围：

1. 所有 `Product/**/*.md` 中的相对路径引用是否存在。
2. 所有 `SKILL.md` 中提到的脚本、prompt、config、schema 路径是否存在。
3. 是否残留旧目录引用：
   - `evidence_collection_v2`
   - 下划线命名子技能
   - 旧试验命名
4. 是否残留文档与真实目录不一致的路径。

推荐输出字段：

- `missing_paths`
- `stale_skill_names`
- `old_dir_references`
- `wrong_script_paths`

## 10. 迁移步骤

### 第 1 步：建正式目录骨架

新建：

- `evidence-collection-web/`
- `evidence-collection-map/`
- `evidence-collection-merge/`

保留并升级：

- `evidence-collection/`

### 第 2 步：迁移脚本、prompt、config

按第 5 章职责划分迁移到对应目录。

### 第 3 步：修复 import

统一把共享模块依赖收敛到：

- `Product/evidence-collection/scripts/evidence_collection_common.py`
- `Product/evidence-collection/scripts/run_context.py`

### 第 4 步：更新文档与 skill frontmatter

统一更新：

- `Product/README.md`
- `Product/CHANGELOG.md`
- `skills-bigpoi-verification/SKILL.md`
- 四个证据收集 skill 的 `SKILL.md`

### 第 5 步：处理旧试验目录

- `evidence_collection_v2/` 不再作为正式主线目录。
- 可短期保留为迁移说明目录，最终删除。

### 第 6 步：验收

执行：

- 文档引用检查脚本
- Python import smoke test
- 证据收集主链路 dry-run

## 11. 验收标准

本方案落地后，至少满足：

1. 父技能 `skills-bigpoi-verification` 名称不变。
2. 父技能继续调用 `evidence-collection`。
3. `evidence-collection` 作为证据收集正式主入口保留。
4. 子技能正式拆为：
   - `evidence-collection-web`
   - `evidence-collection-map`
   - `evidence-collection-merge`
5. 业务脚本已经归位到对应技能目录。
6. 公共 Python 模块统一放在 `evidence-collection/scripts/`。
7. 文档中不再残留 `evidence_collection_v2` 作为正式主线目录的引用。
8. 文档引用检查脚本可通过。
9. 主链路 dry-run 可以打通：
   - `evidence-collection`
   - `evidence-collection-web`
   - `evidence-collection-map`
   - `evidence-collection-merge`

## 12. 结论

本次定稿方案的核心取舍是：

- 父技能不动。
- 主证据收集入口不动。
- 子技能按 Claude Code 规范拆分。
- 统一使用连字符命名。
- 公共代码不再单独建新顶级目录，而是收敛到 `evidence-collection/scripts/`。

该方案兼顾了：

- 最小调用改动
- 最低迁移风险
- 最清晰目录边界
- 最可控的工程化收尾成本
