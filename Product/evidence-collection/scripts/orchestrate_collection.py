#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from evidence_collection_common import ensure_stdout_utf8, normalize_input_poi, read_json_file


def log_progress(message: str) -> None:
    sys.stderr.write(f"[evidence-collection] {message}\n")
    sys.stderr.flush()


def load_json(path: Union[str, Path]) -> Any:
    return read_json_file(path)


def run_json_command(command: List[str], *, label: str, retries: int = 0) -> Dict[str, Any]:
    last_error = ""
    for attempt in range(retries + 1):
        if attempt == 0:
            log_progress(f"执行 {label}")
        else:
            log_progress(f"重试 {label}，第 {attempt} 次")
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        stderr_text = (completed.stderr or "").strip()
        if stderr_text:
            sys.stderr.write(stderr_text + ("\n" if not stderr_text.endswith("\n") else ""))
            sys.stderr.flush()
        if completed.returncode == 0:
            stdout = completed.stdout.strip() or "{}"
            try:
                return json.loads(stdout)
            except json.JSONDecodeError:
                raise ValueError(f"{label} returned non-JSON output: {stdout}")
        last_error = (completed.stderr or completed.stdout or "").strip()
    raise RuntimeError(f"{label} failed after retries. error={last_error}")


def collect_missing_vendors(internal_proxy_path: Union[str, Path]) -> List[str]:
    payload = load_json(internal_proxy_path)
    if not isinstance(payload, dict):
        return []
    vendors = payload.get("vendors") if isinstance(payload.get("vendors"), dict) else {}
    if vendors:
        result: List[str] = []
        for vendor in ("amap", "bmap", "qmap"):
            vendor_payload = vendors.get(vendor)
            items = vendor_payload.get("items") if isinstance(vendor_payload, dict) and isinstance(vendor_payload.get("items"), list) else []
            if not items:
                result.append(vendor)
        return result
    missing = payload.get("missing_vendors")
    if isinstance(missing, list):
        return [str(v) for v in missing if str(v).strip()]
    return []


def count_map_candidates(payload: Dict[str, Any]) -> int:
    if not isinstance(payload, dict):
        return 0
    vendors = payload.get("vendors") if isinstance(payload.get("vendors"), dict) else None
    if vendors is not None:
        return sum(
            len(vendor_payload.get("items") or [])
            for vendor_payload in vendors.values()
            if isinstance(vendor_payload, dict) and isinstance(vendor_payload.get("items"), list)
        )
    items = payload.get("items")
    if isinstance(items, list):
        return len([item for item in items if isinstance(item, dict)])
    return 0


def should_fail_websearch_branch(returncode: int, result_payload: Dict[str, Any]) -> bool:
    if returncode == 0:
        return False
    status = str(result_payload.get("status") or "").strip()
    return status not in {"empty", "partial", "ok"}


def parse_vendor_review_seed_paths(values: Optional[List[str]]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for value in values or []:
        text = str(value or "").strip()
        if not text:
            continue
        if "=" not in text:
            raise ValueError("vendor review seed path must use vendor=path format")
        vendor, path = text.split("=", 1)
        vendor = vendor.strip()
        path = path.strip()
        if not vendor or not path:
            raise ValueError("vendor review seed path must use vendor=path format")
        result[vendor] = path
    return result


def apply_map_review(
    *,
    py: str,
    raw_map_path: Union[str, Path],
    review_seed_path: str,
    output_path: Union[str, Path],
    poi_id: str,
    run_id: str,
    task_id: Optional[str],
    retry_count: int,
) -> Dict[str, Any]:
    review_cmd = [
        py,
        str(SCRIPT_DIR / "write_map_relevance_review.py"),
        "-RawMapPath",
        str(raw_map_path),
        "-ReviewSeedPath",
        review_seed_path,
        "-OutputPath",
        str(output_path),
        "-PoiId",
        poi_id,
        "-RunId",
        run_id,
    ]
    if task_id:
        review_cmd.extend(["-TaskId", task_id])
    return run_json_command(review_cmd, label="write_map_relevance_review", retries=retry_count)


def apply_websearch_review(
    *,
    py: str,
    raw_websearch_path: Union[str, Path],
    review_seed_path: str,
    output_path: Union[str, Path],
    poi_id: str,
    run_id: str,
    task_id: Optional[str],
    retry_count: int,
) -> Dict[str, Any]:
    review_cmd = [
        py,
        str(SCRIPT_DIR / "write_websearch_review.py"),
        "-WebSearchRawPath",
        str(raw_websearch_path),
        "-ReviewSeedPath",
        review_seed_path,
        "-OutputPath",
        str(output_path),
        "-PoiId",
        poi_id,
        "-RunId",
        run_id,
    ]
    if task_id:
        review_cmd.extend(["-TaskId", task_id])
    return run_json_command(review_cmd, label="write_websearch_review", retries=retry_count)


def main() -> int:
    ensure_stdout_utf8()
    parser = argparse.ArgumentParser()
    parser.add_argument("-PoiPath", required=True)
    parser.add_argument("-OutputRoot", required=True)
    parser.add_argument("-RunId", required=True)
    parser.add_argument("-TaskId")
    parser.add_argument("-WebFetchPath")
    parser.add_argument("-CommonConfigPath")
    parser.add_argument("-RetryCount", type=int, default=1)
    parser.add_argument("-InternalReviewSeedPath")
    parser.add_argument("-WebSearchReviewSeedPath")
    parser.add_argument("-VendorReviewSeedPaths", nargs="*")
    args = parser.parse_args()

    poi = normalize_input_poi(load_json(args.PoiPath))
    for field in ("id", "name", "city"):
        if not str(poi.get(field) or "").strip():
            raise ValueError(f"input.{field} is required")

    output_root = Path(args.OutputRoot).resolve()
    process_dir = output_root / "runs" / str(args.RunId) / "process"
    staging_dir = output_root / "runs" / str(args.RunId) / "staging"
    process_dir.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir(parents=True, exist_ok=True)

    web_plan_path = process_dir / "web-plan.json"
    internal_proxy_path = process_dir / "map-raw-internal-proxy.json"
    internal_review_input_path = process_dir / "map-review-input-internal-proxy.json"
    internal_reviewed_path = process_dir / "map-reviewed-internal-proxy.json"
    websearch_path = process_dir / "websearch-raw.json"
    websearch_debug_path = process_dir / "websearch-debug.json"
    websearch_review_input_path = process_dir / "websearch-review-input.json"
    websearch_reviewed_path = process_dir / "websearch-reviewed.json"
    collector_merged_path = process_dir / "collector-merged.json"

    py = sys.executable
    retry_count = max(int(args.RetryCount), 0)
    vendor_review_seed_paths = parse_vendor_review_seed_paths(args.VendorReviewSeedPaths)
    log_progress(f"开始收集证据: poi_id={poi['id']} name={poi['name']} city={poi['city']} run_id={args.RunId}")

    plan_cmd = [py, str(SCRIPT_DIR / "build_web_source_plan.py"), "-PoiPath", str(args.PoiPath), "-OutputPath", str(web_plan_path)]
    plan_result = run_json_command(plan_cmd, label="build_web_source_plan", retries=retry_count)
    log_progress(
        f"检索计划已生成: official={plan_result.get('official_count', 0)} internet={plan_result.get('internet_count', 0)} category={plan_result.get('config_category')}"
    )

    internal_cmd = [
        py,
        str(SCRIPT_DIR / "call_internal_proxy.py"),
        "-PoiName",
        str(poi["name"]),
        "-City",
        str(poi["city"]),
        "-PoiId",
        str(poi["id"]),
        "-RunId",
        str(args.RunId),
        "-OutputPath",
        str(internal_proxy_path),
    ]
    websearch_cmd = [
        py,
        str(SCRIPT_DIR / "websearch_adapter.py"),
        "-WebPlanPath",
        str(web_plan_path),
        "-OutputPath",
        str(websearch_path),
        "-DebugLogPath",
        str(websearch_debug_path),
        "-PoiId",
        str(poi["id"]),
        "-RunId",
        str(args.RunId),
    ]
    if args.TaskId:
        internal_cmd.extend(["-TaskId", str(args.TaskId)])
        websearch_cmd.extend(["-TaskId", str(args.TaskId)])
    if args.CommonConfigPath:
        internal_cmd.extend(["-CommonConfigPath", str(args.CommonConfigPath)])
        websearch_cmd.extend(["-CommonConfigPath", str(args.CommonConfigPath)])

    internal_proc = subprocess.Popen(internal_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    websearch_proc = subprocess.Popen(websearch_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    log_progress("并发执行图商代理与 websearch")

    internal_stdout, internal_stderr = internal_proc.communicate()
    websearch_stdout, websearch_stderr = websearch_proc.communicate()
    if internal_stderr.strip():
        sys.stderr.write(internal_stderr.strip() + "\n")
        sys.stderr.flush()
    if websearch_stderr.strip():
        sys.stderr.write(websearch_stderr.strip() + "\n")
        sys.stderr.flush()
    if internal_proc.returncode != 0:
        raise RuntimeError(f"call_internal_proxy failed: {(internal_stderr or internal_stdout).strip()}")
    internal_result = json.loads(internal_stdout.strip() or "{}")
    websearch_result = json.loads(websearch_stdout.strip() or "{}")
    if should_fail_websearch_branch(websearch_proc.returncode, websearch_result):
        raise RuntimeError(f"websearch_adapter failed: {(websearch_stderr or websearch_stdout).strip()}")
    if str(internal_result.get("status") or "").strip() == "error":
        raise RuntimeError(f"call_internal_proxy returned error status: {(internal_stderr or internal_stdout).strip()}")
    log_progress(
        "图商代理完成: amap={amap} bmap={bmap} qmap={qmap} missing={missing}".format(
            amap=((internal_result.get("vendor_counts") or {}).get("amap", 0)),
            bmap=((internal_result.get("vendor_counts") or {}).get("bmap", 0)),
            qmap=((internal_result.get("vendor_counts") or {}).get("qmap", 0)),
            missing=",".join(internal_result.get("missing_vendors") or []) or "none",
        )
    )
    log_progress(
        "websearch 完成: status={status} query_count={query_count} result_count={result_count} provider={provider}".format(
            status=websearch_result.get("status"),
            query_count=websearch_result.get("query_count", 0),
            result_count=websearch_result.get("result_count", 0),
            provider=websearch_result.get("effective_provider") or "none",
        )
    )

    review_outputs: Dict[str, str] = {}
    internal_merge_input_path = str(internal_proxy_path)
    internal_review_input_cmd = [
        py,
        str(SCRIPT_DIR / "prepare_map_review_input.py"),
        "-PoiPath",
        str(args.PoiPath),
        "-RawMapPath",
        str(internal_proxy_path),
        "-OutputPath",
        str(internal_review_input_path),
        "-RunId",
        str(args.RunId),
    ]
    if args.TaskId:
        internal_review_input_cmd.extend(["-TaskId", str(args.TaskId)])
    run_json_command(internal_review_input_cmd, label="prepare_map_review_input[internal]", retries=retry_count)
    internal_payload = load_json(internal_proxy_path)
    if count_map_candidates(internal_payload) > 0:
        if not args.InternalReviewSeedPath:
            raise RuntimeError(
                "internal map review seed is required before merge. "
                f"review_input_path={internal_review_input_path}"
            )
        validate_internal_review_cmd = [
            py,
            str(SCRIPT_DIR / "validate_map_review_seed.py"),
            "-MapReviewInputPath",
            str(internal_review_input_path),
            "-ReviewSeedPath",
            str(args.InternalReviewSeedPath),
        ]
        run_json_command(validate_internal_review_cmd, label="validate_map_review_seed[internal]", retries=retry_count)
        apply_map_review(
            py=py,
            raw_map_path=internal_proxy_path,
            review_seed_path=str(args.InternalReviewSeedPath),
            output_path=internal_reviewed_path,
            poi_id=str(poi["id"]),
            run_id=str(args.RunId),
            task_id=str(args.TaskId) if args.TaskId else None,
            retry_count=retry_count,
        )
        internal_merge_input_path = str(internal_reviewed_path)
        review_outputs["internal_proxy"] = str(internal_reviewed_path)
        log_progress("内部图商候选已完成相关性过滤")

    vendor_fallback_paths: List[str] = []
    missing_vendors = collect_missing_vendors(internal_proxy_path)
    for vendor in missing_vendors:
        log_progress(f"图商缺失补采: {vendor}")
        fallback_path = process_dir / f"map-raw-fallback-{vendor}.json"
        fallback_review_input_path = process_dir / f"map-review-input-fallback-{vendor}.json"
        reviewed_fallback_path = process_dir / f"map-reviewed-fallback-{vendor}.json"
        fallback_cmd = [
            py,
            str(SCRIPT_DIR / "call_map_vendor.py"),
            "-PoiName",
            str(poi["name"]),
            "-City",
            str(poi["city"]),
            "-Source",
            vendor,
            "-PoiId",
            str(poi["id"]),
            "-RunId",
            str(args.RunId),
            "-OutputPath",
            str(fallback_path),
        ]
        if args.TaskId:
            fallback_cmd.extend(["-TaskId", str(args.TaskId)])
        if args.CommonConfigPath:
            fallback_cmd.extend(["-CommonConfigPath", str(args.CommonConfigPath)])
        run_json_command(fallback_cmd, label=f"call_map_vendor[{vendor}]", retries=retry_count)
        fallback_payload = load_json(fallback_path)
        if count_map_candidates(fallback_payload) <= 0:
            continue

        prepare_fallback_review_cmd = [
            py,
            str(SCRIPT_DIR / "prepare_map_review_input.py"),
            "-PoiPath",
            str(args.PoiPath),
            "-RawMapPath",
            str(fallback_path),
            "-OutputPath",
            str(fallback_review_input_path),
            "-RunId",
            str(args.RunId),
        ]
        if args.TaskId:
            prepare_fallback_review_cmd.extend(["-TaskId", str(args.TaskId)])
        run_json_command(prepare_fallback_review_cmd, label=f"prepare_map_review_input[{vendor}]", retries=retry_count)

        review_seed_path = vendor_review_seed_paths.get(vendor)
        if not review_seed_path:
            raise RuntimeError(
                f"vendor fallback review seed is required before merge: vendor={vendor} "
                f"review_input_path={fallback_review_input_path}"
            )

        validate_fallback_review_cmd = [
            py,
            str(SCRIPT_DIR / "validate_map_review_seed.py"),
            "-MapReviewInputPath",
            str(fallback_review_input_path),
            "-ReviewSeedPath",
            str(review_seed_path),
        ]
        run_json_command(validate_fallback_review_cmd, label=f"validate_map_review_seed[{vendor}]", retries=retry_count)

        merge_input_path = str(fallback_path)
        if review_seed_path:
            apply_map_review(
                py=py,
                raw_map_path=fallback_path,
                review_seed_path=review_seed_path,
                output_path=reviewed_fallback_path,
                poi_id=str(poi["id"]),
                run_id=str(args.RunId),
                task_id=str(args.TaskId) if args.TaskId else None,
                retry_count=retry_count,
            )
            merge_input_path = str(reviewed_fallback_path)
            review_outputs[vendor] = str(reviewed_fallback_path)
            log_progress(f"补采图商 {vendor} 已完成相关性过滤")
        vendor_fallback_paths.append(merge_input_path)

    websearch_merge_input_path: Optional[str] = None
    if int(websearch_result.get("result_count") or 0) > 0:
        prepare_websearch_cmd = [
            py,
            str(SCRIPT_DIR / "prepare_websearch_review_input.py"),
            "-PoiPath",
            str(args.PoiPath),
            "-WebSearchRawPath",
            str(websearch_path),
            "-OutputPath",
            str(websearch_review_input_path),
            "-RunId",
            str(args.RunId),
        ]
        if args.TaskId:
            prepare_websearch_cmd.extend(["-TaskId", str(args.TaskId)])
        run_json_command(prepare_websearch_cmd, label="prepare_websearch_review_input", retries=retry_count)
        if not args.WebSearchReviewSeedPath:
            raise RuntimeError(
                "websearch review seed is required before merge. "
                f"review_input_path={websearch_review_input_path}"
            )
        validate_websearch_cmd = [
            py,
            str(SCRIPT_DIR / "validate_websearch_review_seed.py"),
            "-WebSearchReviewInputPath",
            str(websearch_review_input_path),
            "-ReviewSeedPath",
            str(args.WebSearchReviewSeedPath),
        ]
        run_json_command(validate_websearch_cmd, label="validate_websearch_review_seed", retries=retry_count)
        apply_websearch_review(
            py=py,
            raw_websearch_path=websearch_path,
            review_seed_path=str(args.WebSearchReviewSeedPath),
            output_path=websearch_reviewed_path,
            poi_id=str(poi["id"]),
            run_id=str(args.RunId),
            task_id=str(args.TaskId) if args.TaskId else None,
            retry_count=retry_count,
        )
        websearch_merge_input_path = str(websearch_reviewed_path)
        review_outputs["websearch"] = str(websearch_reviewed_path)
        log_progress("websearch 候选已完成结构化 review")

    merge_cmd = [
        py,
        str(SCRIPT_DIR / "merge_evidence_collection_outputs.py"),
        "-PoiPath",
        str(args.PoiPath),
        "-InternalProxyPath",
        internal_merge_input_path,
        "-OutputPath",
        str(collector_merged_path),
        "-RunId",
        str(args.RunId),
    ]
    if args.TaskId:
        merge_cmd.extend(["-TaskId", str(args.TaskId)])
    if websearch_merge_input_path:
        merge_cmd.extend(["-WebSearchPath", websearch_merge_input_path])
    if args.WebFetchPath:
        merge_cmd.extend(["-WebFetchPath", str(args.WebFetchPath)])
    if vendor_fallback_paths:
        merge_cmd.extend(["-VendorFallbackPaths", *vendor_fallback_paths])
    merge_result = run_json_command(merge_cmd, label="merge_evidence_collection_outputs", retries=retry_count)
    log_progress(
        "证据归并完成: evidence_count={count} final_missing_vendors={missing}".format(
            count=merge_result.get("evidence_count", 0),
            missing=",".join(merge_result.get("final_missing_vendors") or []) or "none",
        )
    )

    write_cmd = [
        py,
        str(SCRIPT_DIR / "write_evidence_output.py"),
        "-PoiPath",
        str(args.PoiPath),
        "-CollectorOutputPath",
        str(collector_merged_path),
        "-OutputDirectory",
        str(staging_dir),
        "-RunId",
        str(args.RunId),
    ]
    if args.TaskId:
        write_cmd.extend(["-TaskId", str(args.TaskId)])
    write_result = run_json_command(write_cmd, label="write_evidence_output", retries=retry_count)
    log_progress(
        f"正式 evidence 已写出: count={write_result.get('evidence_count', 0)} path={write_result.get('evidence_path')}"
    )

    result = {
        "status": "ok",
        "run_id": str(args.RunId),
        "poi_id": str(poi["id"]),
        "web_plan_path": str(web_plan_path),
        "internal_proxy_path": str(internal_proxy_path),
        "internal_review_input_path": str(internal_review_input_path),
        "internal_reviewed_path": review_outputs.get("internal_proxy"),
        "websearch_path": str(websearch_path),
        "websearch_review_input_path": str(websearch_review_input_path) if websearch_merge_input_path else None,
        "websearch_reviewed_path": review_outputs.get("websearch"),
        "websearch_debug_path": str(websearch_debug_path),
        "vendor_fallback_paths": vendor_fallback_paths,
        "review_outputs": review_outputs,
        "collector_merged_path": str(collector_merged_path),
        "evidence_path": write_result.get("evidence_path"),
        "summary_text": (
            "证据收集完成："
            f"图商缺失补采 {len(missing_vendors)} 个，"
            f"websearch 状态 {websearch_result.get('status') or 'unknown'}，"
            f"归并证据 {merge_result.get('evidence_count', 0)} 条，"
            f"正式 evidence {write_result.get('evidence_count', 0)} 条。"
        ),
    }
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
