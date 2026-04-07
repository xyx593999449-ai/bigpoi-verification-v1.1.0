#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

MAX_TIMEOUT = 1200
DEFAULT_ALLOWED_TOOLS = "Bash,Read,Write,Edit,Glob,Grep,LS,Skill"
WEB_ALLOWED_TOOLS = "Bash,Read,Write,Edit,Glob,Grep,LS,Skill,WebSearch,WebFetch"
MAP_SYSTEM_PROMPT = (
    "你是 BigPOI 证据收集并行 worker 中的图商分支执行器。"
    "必须严格按指定 skill 执行；"
    "所有 python 脚本都要直接用 python 或 python3 解释器 + .py 文件执行；"
    "最终以落盘文件为准，不要只输出自然语言结论。"
)
WEB_SYSTEM_PROMPT = (
    "你是 BigPOI 证据收集并行 worker 中的联网分支执行器。"
    "必须严格按指定 skill 执行；"
    "在 skill 执行过程中优先使用模型自带的 WebSearch 与 WebFetch 完成联网搜索和网页读取；"
    "只有在当前运行环境无内置 WebSearch/WebFetch 或内置能力不可用时，才回退到内部代理 Python 脚本；"
    "所有 python 脚本都要直接用 python 或 python3 解释器 + .py 文件执行；"
    "最终以落盘文件为准，不要只输出自然语言结论。"
)


def utc_now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_json_text(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def build_prompt(skill_name: str, payload: Dict[str, object]) -> str:
    payload_text = ensure_json_text(payload)
    return f"调用技能 {skill_name}，输入数据为：{payload_text}。"


def build_command(prompt: str, *, allowed_tools: str, system_prompt: str) -> List[str]:
    return [
        "claude",
        "-p",
        prompt,
        "--allowedTools",
        allowed_tools,
        "--append-system-prompt",
        system_prompt,
        "--output-format",
        "stream-json",
        "--verbose",
    ]


def start_worker(
    *,
    worker_name: str,
    skill_name: str,
    payload: Dict[str, object],
    log_path: Path,
    timeout_seconds: int,
) -> subprocess.Popen[str]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    prompt = build_prompt(skill_name, payload)
    if worker_name == "web":
        command = build_command(prompt, allowed_tools=WEB_ALLOWED_TOOLS, system_prompt=WEB_SYSTEM_PROMPT)
    else:
        command = build_command(prompt, allowed_tools=DEFAULT_ALLOWED_TOOLS, system_prompt=MAP_SYSTEM_PROMPT)

    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env.pop("CLAUDE_CODE", None)

    log_file = open(log_path, "a", encoding="utf-8")
    log_file.write(f"\n{'=' * 80}\n")
    log_file.write(f"时间: {utc_now_text()}\n")
    log_file.write(f"worker: {worker_name}\n")
    log_file.write(f"技能: {skill_name}\n")
    log_file.write(f"输入: {ensure_json_text(payload)}\n")
    log_file.write(f"命令: {' '.join(command)}\n")
    log_file.write(f"{'=' * 80}\n\n")
    log_file.flush()

    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        env=env,
        shell=True,
    )
    process._codex_log_file = log_file  # type: ignore[attr-defined]
    process._codex_timeout_seconds = timeout_seconds  # type: ignore[attr-defined]
    return process


def wait_worker(name: str, process: subprocess.Popen[str]) -> Dict[str, object]:
    timeout_seconds = int(getattr(process, "_codex_timeout_seconds", MAX_TIMEOUT))
    try:
        return_code = process.wait(timeout=timeout_seconds)
        status = "ok" if return_code == 0 else "error"
        return {"worker": name, "status": status, "return_code": return_code}
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        return {"worker": name, "status": "timeout", "return_code": None}
    finally:
        log_file = getattr(process, "_codex_log_file", None)
        if log_file is not None:
            log_file.flush()
            log_file.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("-InputPath", required=True)
    parser.add_argument("-RunId", required=True)
    parser.add_argument("-TaskId", required=True)
    parser.add_argument("-WorkspaceRoot", required=True)
    parser.add_argument("-OutputPath", required=True)
    parser.add_argument("-LogDirectory", required=True)
    parser.add_argument("-TimeoutSeconds", type=int, default=MAX_TIMEOUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    workspace_root = Path(args.WorkspaceRoot).resolve()
    output_path = Path(args.OutputPath).resolve()
    log_directory = Path(args.LogDirectory).resolve()
    result_task_dir = workspace_root / "output" / "results" / str(args.TaskId)
    process_dir = workspace_root / "output" / "runs" / str(args.RunId) / "process"
    if not log_directory.is_absolute():
        log_directory = (workspace_root / log_directory).resolve()
    if str(log_directory).startswith(str(output_path.parent)):
        log_directory = (result_task_dir / log_directory.name).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result_task_dir.mkdir(parents=True, exist_ok=True)
    log_directory.mkdir(parents=True, exist_ok=True)
    process_dir.mkdir(parents=True, exist_ok=True)

    runtime_payload = {
        "input_poi_path": str(Path(args.InputPath).resolve()),
        "run_id": str(args.RunId),
        "task_id": str(args.TaskId),
        "workspace_root": str(workspace_root),
        "process_dir": str(process_dir),
        "branch_result_paths": {
            "web": str(process_dir / "web-branch-result.json"),
            "map": str(process_dir / "map-branch-result.json"),
        },
        "review_seed_paths": {
            "websearch": str(process_dir / "websearch-review-seed.json"),
            "webreader": str(process_dir / "webreader-review-seed.json"),
            "map_internal": str(process_dir / "map-review-seed-internal-proxy.json"),
            "map_fallback_amap": str(process_dir / "map-review-seed-fallback-amap.json"),
            "map_fallback_bmap": str(process_dir / "map-review-seed-fallback-bmap.json"),
            "map_fallback_qmap": str(process_dir / "map-review-seed-fallback-qmap.json"),
        },
    }

    web_log_path = log_directory / "claude_web_worker.log"
    map_log_path = log_directory / "claude_map_worker.log"

    web_process = start_worker(
        worker_name="web",
        skill_name="evidence-collection-web",
        payload=runtime_payload,
        log_path=web_log_path,
        timeout_seconds=max(int(args.TimeoutSeconds), 1),
    )
    map_process = start_worker(
        worker_name="map",
        skill_name="evidence-collection-map",
        payload=runtime_payload,
        log_path=map_log_path,
        timeout_seconds=max(int(args.TimeoutSeconds), 1),
    )

    web_result = wait_worker("web", web_process)
    map_result = wait_worker("map", map_process)

    result = {
        "status": "ok" if web_result["status"] == "ok" and map_result["status"] == "ok" else "error",
        "run_id": str(args.RunId),
        "task_id": str(args.TaskId),
        "workspace_root": str(workspace_root),
        "workers": [
            {
                **web_result,
                "skill_name": "evidence-collection-web",
                "log_path": str(web_log_path),
            },
            {
                **map_result,
                "skill_name": "evidence-collection-map",
                "log_path": str(map_log_path),
            },
        ],
    }

    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
