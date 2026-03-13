#!/usr/bin/env python3
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

UTC_ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
UTC_STAMP_FORMAT = "%Y%m%dT%H%M%SZ"


def utc_iso_now() -> str:
    return datetime.now(timezone.utc).strftime(UTC_ISO_FORMAT)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime(UTC_STAMP_FORMAT)


def is_iso_time(value: str) -> bool:
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def build_run_id(task_id: str, poi_id: str, created_at: str | None = None) -> str:
    stamp = created_at or utc_timestamp()
    digest = hashlib.sha256(f"{task_id}|{poi_id}|{stamp}".encode("utf-8")).hexdigest()[:8]
    return f"{task_id}-{poi_id}-{stamp}-{digest}"


def build_run_directories(workspace_root: str | Path, run_id: str) -> dict[str, Path]:
    root = Path(workspace_root).resolve() / "output" / "runs" / str(run_id)
    return {
        "run_root": root,
        "process_dir": root / "process",
        "staging_dir": root / "staging",
    }


def make_context(run_id: str, poi_id: str, task_id: str | None = None, created_at: str | None = None) -> dict[str, str]:
    context = {
        "run_id": str(run_id),
        "poi_id": str(poi_id),
        "created_at": created_at or utc_iso_now(),
    }
    if task_id:
        context["task_id"] = str(task_id)
    return context


def attach_context(payload: dict[str, Any], run_id: str, poi_id: str, task_id: str | None = None, created_at: str | None = None) -> dict[str, Any]:
    output = dict(payload)
    output["context"] = make_context(run_id, poi_id, task_id=task_id, created_at=created_at)
    return output


def get_context(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict) and isinstance(payload.get("context"), dict):
        return dict(payload["context"])
    return None


def require_context(
    payload: Any,
    *,
    label: str,
    expected_poi_id: str | None = None,
    expected_run_id: str | None = None,
    allow_missing: bool = False,
) -> dict[str, Any] | None:
    context = get_context(payload)
    if context is None:
        if allow_missing:
            return None
        raise ValueError(f"{label}.context is required")
    poi_id = str(context.get("poi_id") or "").strip()
    if not poi_id:
        raise ValueError(f"{label}.context.poi_id is required")
    created_at = str(context.get("created_at") or "").strip()
    if not created_at:
        raise ValueError(f"{label}.context.created_at is required")
    if not is_iso_time(created_at):
        raise ValueError(f"{label}.context.created_at must be ISO datetime")
    if expected_poi_id is not None and poi_id != str(expected_poi_id):
        raise ValueError(f"{label}.context.poi_id must match input id")
    run_id = str(context.get("run_id") or "").strip()
    if expected_run_id is not None:
        if not run_id:
            raise ValueError(f"{label}.context.run_id is required")
        if run_id != str(expected_run_id):
            raise ValueError(f"{label}.context.run_id must match the current run")
    return context


def set_item_run_context(item: dict[str, Any], run_id: str | None, task_id: str | None = None) -> dict[str, Any]:
    if not run_id:
        return item
    output = dict(item)
    metadata = dict(output.get("metadata") if isinstance(output.get("metadata"), dict) else {})
    metadata["run_id"] = str(run_id)
    if task_id:
        metadata["task_id"] = str(task_id)
    output["metadata"] = metadata
    return output


def collect_item_run_ids(items: Iterable[Any]) -> set[str]:
    run_ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        run_id = str(metadata.get("run_id") or "").strip()
        if run_id:
            run_ids.add(run_id)
    return run_ids
