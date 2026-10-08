from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harmony_adapter.adapter import HarmonyAdapter
from harmony_adapter.config import HarmonyConfig
from harmony_adapter.evaluation import EvaluationOptions, evaluate_case
from harmony_adapter.history import append_evaluation_history
from harmony_adapter.models import TaskSpec
from harmony_adapter.utils import ensure_dir, write_json


@dataclass(frozen=True)
class FileSpec:
    path: str
    content: str


@dataclass(frozen=True)
class OracleRule:
    path: str
    contains: list[str] = field(default_factory=list)
    not_contains: list[str] = field(default_factory=list)
    weight: float = 1.0


@dataclass(frozen=True)
class BenchmarkCase:
    instance_id: str
    title: str
    instruction: str
    files: list[FileSpec]
    oracle: list[OracleRule]


CASES = [
    BenchmarkCase(
        instance_id="harmony-counter-state",
        title="Fix ArkTS counter state update",
        instruction=(
            "Index.ets 中按钮点击后计数一次只能加 1。请修复当前每次点击加 2 的问题，"
            "保持组件结构不变。"
        ),
        files=[
            FileSpec(
                "entry/src/main/ets/pages/Index.ets",
                """@Entry
@Component
struct Index {
  @State count: number = 0

  build() {
    Column() {
      Text(`Count: ${this.count}`)
      Button('Add')
        .onClick(() => {
          this.count += 2
        })
    }
  }
}
""",
            )
        ],
        oracle=[
            OracleRule(
                path="entry/src/main/ets/pages/Index.ets",
                contains=["this.count += 1"],
                not_contains=["this.count += 2"],
            )
        ],
    ),
    BenchmarkCase(
        instance_id="harmony-router-target",
        title="Fix router target page",
        instruction=(
            "LoginButton.ets 登录成功后应该跳转到 pages/Home，而不是 pages/Login。"
            "请只修复跳转目标。"
        ),
        files=[
            FileSpec(
                "entry/src/main/ets/components/LoginButton.ets",
                """import router from '@ohos.router'

@Component
export struct LoginButton {
  build() {
    Button('Login')
      .onClick(() => {
        router.pushUrl({ url: 'pages/Login' })
      })
  }
}
""",
            )
        ],
        oracle=[
            OracleRule(
                path="entry/src/main/ets/components/LoginButton.ets",
                contains=["url: 'pages/Home'"],
                not_contains=["url: 'pages/Login'"],
            )
        ],
    ),
    BenchmarkCase(
        instance_id="harmony-module-install",
        title="Enable feature module install with app",
        instruction=(
            "feature 模块需要随应用一起安装。请把 module.json5 中 deliveryWithInstall "
            "从 false 改成 true，其他字段不要改。"
        ),
        files=[
            FileSpec(
                "feature/src/main/module.json5",
                """{
  module: {
    name: 'feature',
    type: 'feature',
    deliveryWithInstall: false,
    installationFree: false
  }
}
""",
            )
        ],
        oracle=[
            OracleRule(
                path="feature/src/main/module.json5",
                contains=["deliveryWithInstall: true"],
                not_contains=["deliveryWithInstall: false"],
            )
        ],
    ),
    BenchmarkCase(
        instance_id="harmony-hilog-domain",
        title="Use stable hilog domain",
        instruction=(
            "EntryAbility.ets 的日志 domain 必须统一为 0x0001，tag 保持 EntryAbility。"
            "请修复错误的 domain。"
        ),
        files=[
            FileSpec(
                "entry/src/main/ets/entryability/EntryAbility.ets",
                """import hilog from '@ohos.hilog'
import UIAbility from '@ohos.app.ability.UIAbility'

export default class EntryAbility extends UIAbility {
  onCreate() {
    hilog.info(0x0000, 'EntryAbility', 'Ability created')
  }
}
""",
            )
        ],
        oracle=[
            OracleRule(
                path="entry/src/main/ets/entryability/EntryAbility.ets",
                contains=["hilog.info(0x0001, 'EntryAbility'"],
                not_contains=["hilog.info(0x0000, 'EntryAbility'"],
            )
        ],
    ),
]


def run_benchmark(
    harnesses: dict[str, str],
    artifacts_root: Path,
    timeout_sec: int = 120,
    max_tokens: int | None = 200000,
    required_model: str | None = None,
    required_variant: str | None = None,
    require_model_lock: bool = False,
    selected_model: str | None = None,
    evaluation_options: EvaluationOptions | None = None,
) -> dict[str, Any]:
    benchmark_root = Path(tempfile.mkdtemp(prefix="harmony-benchmark-"))
    case_repos = _create_case_repos(benchmark_root)
    options = evaluation_options or EvaluationOptions()
    summary: dict[str, Any] = {
        "benchmark_root": str(benchmark_root),
        "artifacts_root": str(artifacts_root),
        "case_count": len(CASES),
        "evaluation_mode": {
            "oracle": "case-specific contains/not_contains checks",
            "patch_scope": "changed files must stay within case fixture files",
            "build": {
                "enabled": options.run_build,
                "target": options.build_target,
                "timeout_sec": options.build_timeout_sec,
            },
            "model_lock": {
                "required_model": required_model,
                "required_variant": required_variant,
                "require_model_lock": require_model_lock,
                "selected_model": selected_model,
            },
        },
        "harnesses": {},
    }

    for harness_name, harness_command in harnesses.items():
        rows = []
        passed = 0
        total_score = 0.0
        run_id = f"benchmark-{harness_name}"
        config = HarmonyConfig.from_env()
        config = HarmonyConfig(
            dev_eco_home=config.dev_eco_home,
            sdk_home=config.sdk_home,
            node_home=config.node_home,
            ohpm_bin=config.ohpm_bin,
            hvigor_bin=config.hvigor_bin,
            hdc_bin=config.hdc_bin,
            device_id=config.device_id,
            harness_command=harness_command,
            timeout_sec=timeout_sec,
            max_tokens=max_tokens,
            required_model=required_model,
            required_variant=required_variant,
            require_model_lock=require_model_lock,
            evaluation_criteria=(
                "Score each task with the adapter oracle. Full credit requires satisfying all "
                "case-specific file checks, avoiding unrelated file edits, and passing Harmony "
                "build validation when the workspace contains build metadata."
            ),
            model_name=selected_model or harness_name,
            actual_model=selected_model,
            artifacts_root=artifacts_root,
        )
        adapter = HarmonyAdapter(config)
        for case in CASES:
            task = TaskSpec(instance_id=case.instance_id, repo=case_repos[case.instance_id], instruction=case.instruction)
            record = adapter.run_task(task, run_id=run_id)
            artifact_dir = Path(str(record.metadata["artifact_dir"]))
            probe = _read_first_probe(artifact_dir)
            if probe.get("status") == "ran" and record.metadata["exit_code"] == 77:
                probe["status"] = "auth_required"
            token_usage = _extract_token_usage(artifact_dir)
            score = evaluate_case(case, artifact_dir / "workspace", config, options)
            passed += 1 if score["passed"] else 0
            total_score += float(score["score"])
            rows.append(
                {
                    "instance_id": case.instance_id,
                    "title": case.title,
                    "status": str(probe.get("status") or "scored") if probe else "scored",
                    "passed": score["passed"],
                    "score": score["score"],
                    "exit_code": record.metadata["exit_code"],
                    "patch_bytes": len(record.model_patch.encode("utf-8")),
                    "artifact_dir": str(artifact_dir),
                    "token_usage": token_usage,
                    "probe": probe,
                    "details": score["details"],
                    "patch_scope": score["patch_scope"],
                    "build": score["build"],
                }
            )
        unsupported = rows and all(row["status"] == "unsupported" for row in rows)
        auth_required = rows and all(row["status"] == "auth_required" for row in rows)
        config_error = rows and all(row["status"] in ("config_error", "model_unlocked") for row in rows)
        setup_issue = unsupported or auth_required or config_error
        token_usage = _aggregate_rows_token_usage(rows)
        summary["harnesses"][harness_name] = {
            "status": (
                "unsupported"
                if unsupported
                else "auth_required"
                if auth_required
                else "config_error"
                if config_error
                else "scored"
            ),
            "passed": passed,
            "total": len(CASES),
            "pass_rate": None if setup_issue else round(passed / len(CASES), 3),
            "score": None if setup_issue else round(total_score / len(CASES), 3),
            "token_usage": token_usage,
            "rows": rows,
        }

    summary["token_usage"] = _aggregate_harness_token_usage(summary)
    write_json(ensure_dir(artifacts_root) / "benchmark_summary.json", summary)
    return summary


def score_case(case: BenchmarkCase, workspace: Path) -> dict[str, Any]:
    config = HarmonyConfig.from_env()
    return evaluate_case(case, workspace, config, EvaluationOptions(run_build=False))


def default_harnesses() -> dict[str, str]:
    harnesses = codex_harness()
    harnesses.update(bitfun_harness())
    return harnesses


def bitfun_harness() -> dict[str, str]:
    harness_dir = Path(__file__).resolve().parent / "builtin_harnesses"
    return {
        "bitfun": f"python3 {harness_dir / 'bitfun_exec.py'} --prompt {{prompt}} --workspace {{workspace}} --artifacts {{artifacts}} --instance-id {{instance_id}}"
    }


def codex_harness() -> dict[str, str]:
    harness_dir = Path(__file__).resolve().parent / "builtin_harnesses"
    return {
        "codex": f"python3 {harness_dir / 'codex_exec.py'} --prompt {{prompt}} --workspace {{workspace}} --artifacts {{artifacts}} --instance-id {{instance_id}}"
    }


def _create_case_repos(root: Path) -> dict[str, Path]:
    repos: dict[str, Path] = {}
    for case in CASES:
        repo = root / "repos" / case.instance_id
        for file_spec in case.files:
            path = repo / file_spec.path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(file_spec.content, encoding="utf-8")
        _run_cmd(["git", "init"], repo)
        _run_cmd(["git", "config", "user.email", "benchmark@example.test"], repo)
        _run_cmd(["git", "config", "user.name", "Harmony Benchmark"], repo)
        _run_cmd(["git", "add", "."], repo)
        _run_cmd(["git", "commit", "-m", f"initial {case.instance_id}"], repo)
        repos[case.instance_id] = repo
    return repos


def _run_cmd(args: list[str], cwd: Path) -> None:
    result = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"{args[0]} failed")


def _read_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _read_first_probe(artifact_dir: Path) -> dict[str, Any]:
    for name in ("bitfun_probe.json", "codex_probe.json"):
        probe = _read_optional_json(artifact_dir / name)
        if probe:
            if probe.get("status") == "ran" and probe.get("exit_code") == 77:
                probe["status"] = "auth_required"
            return probe
    return {}


def _extract_token_usage(artifact_dir: Path) -> dict[str, Any]:
    for name in ("codex_probe.json", "bitfun_probe.json", "harness_report.txt"):
        usage = _token_usage_from_json(_read_optional_json(artifact_dir / name))
        if usage.get("total") is not None:
            usage["source"] = name
            return usage
    for path in sorted(artifact_dir.glob("*_stderr.log")) + sorted(artifact_dir.glob("*_stdout.log")):
        usage = _token_usage_from_text(_read_text(path))
        if usage.get("total") is not None:
            usage["source"] = path.name
            return usage
    return {"total": None, "input": None, "output": None, "source": "unavailable"}


def _token_usage_from_json(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"total": None, "input": None, "output": None}
    candidates = [value]
    for key in ("usage", "token_usage", "tokens"):
        if isinstance(value.get(key), dict):
            candidates.append(value[key])
    for candidate in candidates:
        input_tokens = _first_int(candidate, ["input_tokens", "prompt_tokens", "input", "prompt"])
        output_tokens = _first_int(candidate, ["output_tokens", "completion_tokens", "output", "completion"])
        total_tokens = _first_int(candidate, ["total_tokens", "total", "tokens_used", "token_count"])
        if total_tokens is None and (input_tokens is not None or output_tokens is not None):
            total_tokens = (input_tokens or 0) + (output_tokens or 0)
        if total_tokens is not None:
            return {"total": total_tokens, "input": input_tokens, "output": output_tokens}
    return {"total": None, "input": None, "output": None}


def _first_int(value: dict[str, Any], keys: list[str]) -> int | None:
    for key in keys:
        raw = value.get(key)
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str):
            normalized = raw.replace(",", "").strip()
            if normalized.isdigit():
                return int(normalized)
    return None


def _token_usage_from_text(text: str) -> dict[str, Any]:
    patterns = [
        r"tokens used\s*\n\s*([0-9][0-9,]*)",
        r"total tokens?\s*[:=]\s*([0-9][0-9,]*)",
        r"tokens used\s*[:=]\s*([0-9][0-9,]*)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return {"total": int(match.group(1).replace(",", "")), "input": None, "output": None}
    return {"total": None, "input": None, "output": None}


def _aggregate_rows_token_usage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = 0
    known = False
    for row in rows:
        usage = row.get("token_usage") or {}
        if isinstance(usage.get("total"), int):
            known = True
            total += usage["total"]
    return {"total": total if known else None, "source": "case_sum"}


def _aggregate_harness_token_usage(summary: dict[str, Any]) -> dict[str, Any]:
    total = 0
    known = False
    for harness in (summary.get("harnesses") or {}).values():
        usage = harness.get("token_usage") or {}
        if isinstance(usage.get("total"), int):
            known = True
            total += usage["total"]
    return {"total": total if known else None, "source": "harness_sum"}


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harmony-benchmark")
    parser.add_argument("--artifacts-root", type=Path, default=Path("artifacts") / "benchmark-demo")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--max-tokens", type=int, default=200000)
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--build-target", default="assembleHap")
    parser.add_argument("--build-timeout", type=int, default=300)
    parser.add_argument("--required-model")
    parser.add_argument("--model", help="Selected model id to pass to harness wrappers.")
    parser.add_argument("--required-variant")
    parser.add_argument("--require-model-lock", action="store_true")
    parser.add_argument(
        "--harness",
        action="append",
        help="Custom harness in name=command format. May be repeated. Defaults to Codex and BitFun CLI.",
    )
    args = parser.parse_args(argv)
    harnesses = _parse_harnesses(args.harness) if args.harness else default_harnesses()
    summary = run_benchmark(
        harnesses,
        artifacts_root=args.artifacts_root,
        timeout_sec=args.timeout,
        max_tokens=args.max_tokens,
        required_model=args.required_model,
        required_variant=args.required_variant,
        require_model_lock=args.require_model_lock,
        selected_model=args.model,
        evaluation_options=EvaluationOptions(
            run_build=not args.no_build,
            build_target=args.build_target,
            build_timeout_sec=args.build_timeout,
        ),
    )
    append_evaluation_history(summary, label="cli-benchmark", trigger="cli")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _parse_harnesses(values: list[str]) -> dict[str, str]:
    harnesses = {}
    for value in values:
        name, sep, command = value.partition("=")
        if not sep or not name.strip() or not command.strip():
            raise SystemExit("--harness must use name=command")
        harnesses[name.strip()] = command.strip()
    return harnesses


if __name__ == "__main__":
    raise SystemExit(main())
