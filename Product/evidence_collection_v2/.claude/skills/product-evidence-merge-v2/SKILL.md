---
name: product-evidence-merge-v2
description: 面向 BigPOI 证据收集 v2 的 merge skill。用于读取 web 与 map 两个分支结果文件，执行 reviewed-only merge，并调用正式脚本写出 evidence 文件。
argument-hint: [input-poi-json-path] [run-id] [task-id] [workspace-root]
disable-model-invocation: true
---

# Product Evidence Merge V2

## Goal

本 skill 只负责两件事：

1. 读取两个分支的标准结果文件并执行 reviewed-only merge。
2. 调用正式 evidence 写出脚本，生成唯一正式产物 `evidence_*.json`。

## Runtime assets

使用以下正式脚本：

- `Product/evidence-collection/scripts/merge_evidence_collection_outputs.py`
- `Product/evidence-collection/scripts/write_evidence_output.py`

依赖以下标准输入文件：

- `output/runs/{run_id}/process/web-branch-result.json`
- `output/runs/{run_id}/process/map-branch-result.json`

## Input

参数顺序固定为：

1. `$0` = `input_poi_path`
2. `$1` = `run_id`
3. `$2` = `task_id`
4. `$3` = `workspace_root`

缺任何一个必要参数都直接报错。

## Execution steps

1. 解析：
   - `REPO_ROOT=$3`
   - `PROCESS_DIR=$REPO_ROOT/output/runs/$1/process`
   - `STAGING_DIR=$REPO_ROOT/output/runs/$1/staging`
2. 读取并校验：
   - `web-branch-result.json`
   - `map-branch-result.json`
3. 从 `map-branch-result.json` 提取：
   - `internal_proxy_merge_input_path`
   - `vendor_merge_input_paths`
4. 从 `web-branch-result.json` 提取：
   - `websearch_merge_input_path`
   - `webreader_merge_input_path`
5. 构造 merge 命令：

```bash
python "$REPO_ROOT/Product/evidence-collection/scripts/merge_evidence_collection_outputs.py" \
  -PoiPath "$0" \
  -InternalProxyPath "<internal_proxy_merge_input_path>" \
  -OutputPath "$PROCESS_DIR/collector-merged.json" \
  -RunId "$1" \
  -TaskId "$2"
```

6. 如果 `websearch_merge_input_path` 非空，则附加：
   - `-WebSearchPath <path>`
7. 如果 `webreader_merge_input_path` 非空，则附加：
   - `-WebReaderPath <path>`
8. 如果存在 `vendor_merge_input_paths`，则附加：
   - `-VendorFallbackPaths <path1> <path2> ...`
9. merge 成功后，再运行：

```bash
python "$REPO_ROOT/Product/evidence-collection/scripts/write_evidence_output.py" \
  -PoiPath "$0" \
  -CollectorOutputPath "$PROCESS_DIR/collector-merged.json" \
  -OutputDirectory "$STAGING_DIR" \
  -RunId "$1" \
  -TaskId "$2"
```

10. 把 merge 结果落盘到：
   - `output/runs/{run_id}/process/evidence-merge-result.json`
11. 该文件至少包含：

```json
{
  "status": "ok",
  "run_id": "<run_id>",
  "task_id": "<task_id>",
  "collector_merged_path": "<abs path>",
  "evidence_path": "<abs path>"
}
```

12. 最终只返回 `evidence_path`。

## Never do

- 不要绕过 `merge_evidence_collection_outputs.py` 手工拼 evidence
- 不要让 merge skill 自己重新执行 web 或 map 采集
- 不要把 `collector-merged.json` 当成正式 evidence 对外返回
