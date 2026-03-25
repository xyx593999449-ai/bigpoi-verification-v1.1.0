#!/usr/bin/env python3
import asyncio
import sys
import argparse
import json
from pathlib import Path

# 设置脚本路径以支持导入
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent.parent

async def run_command(cmd, label):
    print(f"[{label}] Starting...")
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if process.returncode == 0:
        print(f"[{label}] Finished successfully.")
        return json.loads(stdout.decode())
    else:
        print(f"[{label}] Failed with exit code {process.returncode}")
        print(f"[{label}] Error: {stderr.decode()}")
        return {"status": "error", "error": stderr.decode()}

async def main():
    parser = argparse.ArgumentParser(description="Parallel Orchestrator for Evidence Collection (Option 3)")
    parser.add_argument("-PoiPath", required=True)
    parser.add_argument("-RunId", required=True)
    parser.add_argument("-TaskId", required=True)
    args = parser.parse_args()

    # 1. 加载 POI 信息
    with open(args.PoiPath, 'r', encoding='utf-8') as f:
        poi = json.load(f)
    
    poi_name = poi.get("name")
    city = poi.get("city")
    poi_id = poi.get("id")

    # 2. 定义并行任务
    # 注意：WebSearch 和 WebFetch 在此方案中仅为占位，因为它们通常需要 Agent 权限
    # 但我们可以并行拉起图商代理
    proxy_output = f"output/runs/{args.RunId}/process/map-raw-internal-proxy.json"
    
    tasks = [
        run_command([
            sys.executable, 
            str(SCRIPT_DIR / "call_internal_proxy.py"),
            "-PoiName", poi_name,
            "-City", city,
            "-PoiId", str(poi_id),
            "-TaskId", args.TaskId,
            "-RunId", args.RunId,
            "-OutputPath", proxy_output
        ], "Map-Branch")
    ]

    print(">>> Starting Parallel Execution of Branches...")
    results = await asyncio.gather(*tasks)
    
    # 3. 输出汇总
    print(">>> All Parallel Branches Finished.")
    final_status = "ok" if all(r.get("status") == "ok" for r in results) else "partial_error"
    
    summary = {
        "status": final_status,
        "run_id": args.RunId,
        "branch_results": results
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(main())
