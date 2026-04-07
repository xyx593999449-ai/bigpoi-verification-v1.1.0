# Evidence Collection V2

## 1. 目标

`evidence_collection_v2/` 用于把现有 `Product/evidence-collection/` 的大一统证据收集 skill 拆成“主编排 + 双分支并发 + merge 收口”的 skill 结构。

本目录本身不替换既有 Python 脚本，而是复用现有正式脚本，把 skill 层拆成 4 个职责明确的运行单元：

- `product-evidence-intel-v2`：主编排 skill，负责初始化 run context、并发拉起两个 agent、等待结果并触发 merge。
- `product-evidence-web-v2`：`websearch + webreader` 分支 skill。
- `product-evidence-map-v2`：内部图商代理 + 缺失图商补采 + map review 分支 skill。
- `product-evidence-merge-v2`：汇总两条 reviewed 分支并写出正式 `evidence_*.json` 的 merge skill。

## 2. 目录结构

```text
Product/evidence_collection_v2/
├── README.md
└── .claude/
    ├── agents/
    │   ├── product-map-researcher-v2.md
    │   └── product-web-researcher-v2.md
    └── skills/
        ├── product-evidence-intel-v2/
        │   └── SKILL.md
        ├── product-evidence-map-v2/
        │   └── SKILL.md
        ├── product-evidence-merge-v2/
        │   └── SKILL.md
        └── product-evidence-web-v2/
            └── SKILL.md
```

## 3. 运行方式

这些 skill 放在 `Product/evidence_collection_v2/.claude/` 下，适合在以下两种方式中使用：

1. 把当前工作目录切到 `Product/evidence_collection_v2/` 再运行 Claude Code。
2. 或在主工作区运行时，通过 `--add-dir Product/evidence_collection_v2` 把该目录加入 skill / agent 发现范围。

推荐主入口：

```text
/product-evidence-intel-v2 <input-poi-json-path>
```

## 4. 运行契约

### 4.1 主编排输入

主 skill 只接收 1 个正式输入：

- `input-poi-json-path`

主 skill 通过 `Product/skills-bigpoi-verification/scripts/init_run_context.py` 初始化：

- `run_id`
- `task_id`
- `workspace_root`
- `output/runs/{run_id}/process/`
- `output/runs/{run_id}/staging/`

### 4.2 分支结果文件

两个分支 agent 完成后，必须分别落盘：

- `output/runs/{run_id}/process/web-branch-result.json`
- `output/runs/{run_id}/process/map-branch-result.json`

其中只记录：

- 当前分支状态
- reviewed 结果路径
- merge 应消费的标准输入路径
- 关键 debug / review 中间文件路径

### 4.3 merge 结果文件

merge skill 完成后，必须落盘：

- `output/runs/{run_id}/process/evidence-merge-result.json`

其中至少包含：

- `collector_merged_path`
- `evidence_path`
- `run_id`
- `task_id`

## 5. 推荐执行流

1. 主 skill 初始化 run context。
2. 主 skill 同时启动：
   - `product-web-researcher-v2`
   - `product-map-researcher-v2`
3. 两个 agent 各自落 reviewed 结果和分支结果文件。
4. 主 skill 读取两个分支结果文件。
5. 主 skill 触发 `product-evidence-merge-v2`。
6. merge skill 调用现有正式脚本，输出唯一正式产物 `evidence_path`。

## 6. 边界约束

- 本目录不直接产出 `decision_*.json`、`record_*.json`、`index_*.json`。
- merge 之前只允许消费 reviewed 结果或“无候选场景的空 raw 输入”，不允许把有候选的 raw 结果直接并入 formal evidence。
- `webreader` 失败时不阻断主流程，允许仅依赖 `websearch-reviewed.json` 进入 merge。
- 图商补采只允许针对 `missing_vendors` 中的 vendor 执行。
