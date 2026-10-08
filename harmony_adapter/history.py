from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harmony_adapter.utils import append_jsonl, ensure_dir


def default_history_path() -> Path:
    return Path(os.environ.get("HARMONY_HISTORY_PATH", "artifacts/evaluation_history.jsonl"))


def append_evaluation_history(
    summary: dict[str, Any],
    *,
    label: str,
    trigger: str,
    history_path: Path | None = None,
) -> dict[str, Any]:
    path = history_path or default_history_path()
    entry = {
        "history_id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "label": label,
        "trigger": trigger,
        "artifacts_root": summary.get("artifacts_root"),
        "benchmark_root": summary.get("benchmark_root"),
        "case_count": summary.get("case_count"),
        "harnesses": _harness_overview(summary),
        "token_usage": summary.get("token_usage", _aggregate_token_usage(summary)),
        "summary": summary,
    }
    append_jsonl(ensure_dir(path.parent) / path.name, entry)
    return entry


def read_evaluation_history(history_path: Path | None = None, limit: int = 50) -> list[dict[str, Any]]:
    path = history_path or default_history_path()
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            import json

            entries.append(json.loads(line))
        except Exception:
            continue
    return list(reversed(entries[-limit:]))


def _harness_overview(summary: dict[str, Any]) -> dict[str, Any]:
    overview = {}
    for name, result in (summary.get("harnesses") or {}).items():
        overview[name] = {
            "status": result.get("status"),
            "passed": result.get("passed"),
            "total": result.get("total"),
            "pass_rate": result.get("pass_rate"),
            "score": result.get("score"),
            "token_usage": result.get("token_usage"),
        }
    return overview


def _aggregate_token_usage(summary: dict[str, Any]) -> dict[str, Any]:
    total = 0
    known = False
    for harness in (summary.get("harnesses") or {}).values():
        usage = harness.get("token_usage") or {}
        if isinstance(usage.get("total"), int):
            known = True
            total += usage["total"]
    return {"total": total if known else None, "source": "summary"}
