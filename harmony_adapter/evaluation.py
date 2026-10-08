from __future__ import annotations

import subprocess
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from harmony_adapter.config import HarmonyConfig


class CaseLike(Protocol):
    files: list[Any]
    oracle: list[Any]


@dataclass(frozen=True)
class EvaluationOptions:
    run_build: bool = True
    build_target: str = "assembleHap"
    build_timeout_sec: int = 300


def evaluate_case(case: CaseLike, workspace: Path, config: HarmonyConfig, options: EvaluationOptions) -> dict[str, Any]:
    oracle = _score_oracle(case, workspace)
    patch_scope = _check_patch_scope(case, workspace)
    build = _run_harmony_build(workspace, config, options) if options.run_build else _skipped_build("disabled")

    checks = {
        "oracle": oracle["passed"],
        "patch_scope": patch_scope["passed"],
        "build": build["passed"] if build["status"] != "skipped" else True,
    }
    passed = all(checks.values())
    score = oracle["score"]
    if not patch_scope["passed"]:
        score = 0.0
    if build["status"] != "skipped":
        score = score if build["passed"] else 0.0
    return {
        "passed": passed,
        "score": round(score, 3),
        "checks": checks,
        "details": oracle["details"],
        "patch_scope": patch_scope,
        "build": build,
    }


def _score_oracle(case: CaseLike, workspace: Path) -> dict[str, Any]:
    earned = 0.0
    possible = sum(rule.weight for rule in case.oracle)
    details = []
    for rule in case.oracle:
        path = workspace / rule.path
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        missing = [needle for needle in rule.contains if needle not in text]
        forbidden = [needle for needle in rule.not_contains if needle in text]
        ok = path.exists() and not missing and not forbidden
        if ok:
            earned += rule.weight
        details.append(
            {
                "path": rule.path,
                "passed": ok,
                "missing": missing,
                "forbidden_present": forbidden,
                "weight": rule.weight,
            }
        )
    score = earned / possible if possible else 0.0
    return {"passed": score == 1.0, "score": round(score, 3), "details": details}


def _check_patch_scope(case: CaseLike, workspace: Path) -> dict[str, Any]:
    result = subprocess.run(
        ["git", "diff", "--name-only"],
        cwd=workspace,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode not in (0, 1):
        return {
            "passed": False,
            "status": "error",
            "reason": result.stderr.strip() or "git diff --name-only failed",
            "changed_files": [],
            "unexpected_files": [],
        }

    changed = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    allowed = {file_spec.path for file_spec in case.files}
    unexpected = [path for path in changed if path not in allowed]
    return {
        "passed": not unexpected,
        "status": "checked",
        "changed_files": changed,
        "allowed_files": sorted(allowed),
        "unexpected_files": unexpected,
    }


def _run_harmony_build(workspace: Path, config: HarmonyConfig, options: EvaluationOptions) -> dict[str, Any]:
    if not _looks_like_harmony_project(workspace):
        return _skipped_build("workspace has no Harmony build metadata")
    if not config.hvigor_bin.exists():
        return {
            "passed": False,
            "status": "missing_tool",
            "tool": str(config.hvigor_bin),
            "target": options.build_target,
        }

    try:
        result = subprocess.run(
            [str(config.hvigor_bin), options.build_target],
            cwd=workspace,
            env={**os.environ.copy(), **config.command_env()},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=options.build_timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "passed": False,
            "status": "timeout",
            "target": options.build_target,
            "timeout_sec": options.build_timeout_sec,
        }

    return {
        "passed": result.returncode == 0,
        "status": "ran",
        "target": options.build_target,
        "exit_code": result.returncode,
        "stdout_tail": result.stdout[-4000:],
        "stderr_tail": result.stderr[-4000:],
    }


def _looks_like_harmony_project(workspace: Path) -> bool:
    markers = [
        "build-profile.json5",
        "hvigorfile.ts",
        "hvigorfile.js",
        "oh-package.json5",
        "AppScope/app.json5",
    ]
    return any((workspace / marker).exists() for marker in markers)


def _skipped_build(reason: str) -> dict[str, Any]:
    return {"passed": True, "status": "skipped", "reason": reason}
