#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


WORKSPACE_MARKERS: tuple[tuple[str, ...], ...] = (
    (".claude", "skills"),
    (".claude",),
    (".openclaw", "skills"),
    (".openclaw",),
    (".git",),
)


@dataclass(frozen=True)
class WorkspaceDetection:
    workspace_root: Path
    matched_marker: str
    start_path: Path
    strategy: str


def _normalize_path(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    text = str(path).strip()
    if not text:
        return None
    return Path(text).resolve()


def _iter_candidate_starts(paths: Iterable[str | Path | None]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for item in paths:
        normalized = _normalize_path(item)
        if normalized is None:
            continue
        candidate = normalized if normalized.is_dir() else normalized.parent
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def _iter_parents_inclusive(start: Path) -> Iterable[Path]:
    current = start
    while True:
        yield current
        if current.parent == current:
            break
        current = current.parent


def _marker_exists(root: Path, marker_parts: tuple[str, ...]) -> bool:
    return root.joinpath(*marker_parts).exists()


def _is_home_level_app_marker(root: Path, marker_parts: tuple[str, ...]) -> bool:
    if len(marker_parts) != 1:
        return False
    if marker_parts[0] not in {".claude", ".openclaw"}:
        return False
    return root == Path.home()


def find_workspace_root_from_start(start: str | Path | None) -> WorkspaceDetection | None:
    normalized_start = _normalize_path(start)
    if normalized_start is None:
        return None
    start_dir = normalized_start if normalized_start.is_dir() else normalized_start.parent
    for current in _iter_parents_inclusive(start_dir):
        for marker_parts in WORKSPACE_MARKERS:
            if not _marker_exists(current, marker_parts):
                continue
            if _is_home_level_app_marker(current, marker_parts):
                continue
            return WorkspaceDetection(
                workspace_root=current,
                matched_marker="/".join(marker_parts),
                start_path=start_dir,
                strategy="marker_scan",
            )
    return None


def detect_workspace_root(
    workspace_hint: str | Path | None = None,
    related_paths: Iterable[str | Path | None] = (),
    cwd: str | Path | None = None,
) -> WorkspaceDetection:
    candidates = _iter_candidate_starts((workspace_hint, *tuple(related_paths), cwd))
    for candidate in candidates:
        found = find_workspace_root_from_start(candidate)
        if found is not None:
            return found

    fallback = _normalize_path(workspace_hint) or _normalize_path(cwd)
    if fallback is None:
        related_candidates = _iter_candidate_starts(related_paths)
        if related_candidates:
            fallback = related_candidates[0]
    if fallback is None:
        fallback = Path.cwd().resolve()

    fallback_dir = fallback if fallback.is_dir() else fallback.parent
    return WorkspaceDetection(
        workspace_root=fallback_dir,
        matched_marker="",
        start_path=fallback_dir,
        strategy="fallback",
    )


def build_task_dir(workspace_root: str | Path, task_id: str) -> Path:
    return Path(workspace_root).resolve() / "output" / "results" / str(task_id)
