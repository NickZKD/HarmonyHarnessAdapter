from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path


DEFAULT_CODEX_BIN = Path("/Applications/ChatGPT.app/Contents/Resources/codex")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--artifacts", required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()

    artifacts = Path(args.artifacts)
    prompt = Path(args.prompt).read_text(encoding="utf-8")
    executable = _find_codex_exec()
    if executable is None:
        _write_probe(
            artifacts,
            {
                "status": "unsupported",
                "reason": "Codex CLI was not found. Expected CODEX_EXEC_BIN, `codex` on PATH, or the ChatGPT.app bundled codex binary.",
                "default_executable": str(DEFAULT_CODEX_BIN),
            },
        )
        print("Codex CLI was not found.")
        return 78

    model = os.environ.get("CODEX_MODEL") or os.environ.get("HARMONY_ACTUAL_MODEL") or os.environ.get("HARMONY_REQUIRED_MODEL")
    lock_error = _model_lock_error(model)
    if lock_error:
        _write_probe(artifacts, lock_error)
        print(lock_error["reason"])
        return 76

    help_text = _codex_exec_help(executable)
    command = _build_codex_command(executable, Path(args.workspace), model, help_text)
    command_shape = _command_shape(command, executable, Path(args.workspace), model)

    env = os.environ.copy()
    env["HARMONY_INSTANCE_ID"] = args.instance_id
    if model:
        env["HARMONY_ACTUAL_MODEL"] = model

    try:
        result = subprocess.run(
            command,
            cwd=args.workspace,
            env=env,
            input=prompt,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=args.timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        _write_probe(artifacts, {"status": "timeout", "timeout_sec": args.timeout, "model": model})
        return 124

    (artifacts / "codex_stdout.log").write_text(result.stdout, encoding="utf-8")
    (artifacts / "codex_stderr.log").write_text(result.stderr, encoding="utf-8")
    status = "auth_required" if result.returncode != 0 and _looks_like_auth_failure(result.stdout + result.stderr) else "ran"
    _write_probe(
        artifacts,
        {
            "status": status,
            "executable": executable,
            "exit_code": result.returncode,
            "command_shape": command_shape,
            "model": model,
            "unsupported_options": _unsupported_options(help_text),
        },
    )
    print(result.stdout)
    if status == "auth_required":
        return 77
    return result.returncode


def _find_codex_exec() -> str | None:
    override = os.environ.get("CODEX_EXEC_BIN")
    if override:
        return override
    found = shutil.which("codex")
    if found:
        return found
    if DEFAULT_CODEX_BIN.exists():
        return str(DEFAULT_CODEX_BIN)
    return None


def _codex_exec_help(executable: str) -> str:
    try:
        result = subprocess.run(
            [executable, "exec", "--help"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout + result.stderr


def _build_codex_command(executable: str, workspace: Path, model: str | None, help_text: str) -> list[str]:
    command = [executable, "exec"]
    if _supports(help_text, "-C, --cd") or _supports(help_text, "--cd"):
        command.extend(["-C", str(workspace)])
    command.extend(["--sandbox", "workspace-write"])
    if _supports(help_text, "--ask-for-approval"):
        command.extend(["--ask-for-approval", "never"])
    for flag in ["--skip-git-repo-check", "--ephemeral", "--ignore-rules"]:
        if _supports(help_text, flag):
            command.append(flag)
    if model:
        command.extend(["--model", model])
    command.append("-")
    return command


def _supports(help_text: str, flag: str) -> bool:
    return not help_text or flag in help_text


def _unsupported_options(help_text: str) -> list[str]:
    expected = ["--ask-for-approval", "--skip-git-repo-check", "--ephemeral", "--ignore-rules"]
    if not help_text:
        return []
    return [flag for flag in expected if flag not in help_text]


def _command_shape(command: list[str], executable: str, workspace: Path, model: str | None) -> str:
    parts = command.copy()
    parts[0] = "codex"
    workspace_text = str(workspace)
    parts = ["<workspace>" if part == workspace_text else part for part in parts]
    if model:
        parts = ["<model>" if part == model else part for part in parts]
    return " ".join(parts)


def _model_lock_error(model: str | None) -> dict[str, object] | None:
    required_model = os.environ.get("HARMONY_REQUIRED_MODEL")
    require_lock = os.environ.get("HARMONY_REQUIRE_MODEL_LOCK", "").lower() in {"1", "true", "yes", "on"}
    if required_model and model != required_model:
        return {
            "status": "config_error",
            "reason": f"Codex model mismatch: required {required_model!r}, got {model!r}.",
            "required_model": required_model,
            "actual_model": model,
        }
    if require_lock and not model:
        return {
            "status": "model_unlocked",
            "reason": "Codex model lock is required, but CODEX_MODEL/HARMONY_REQUIRED_MODEL is not set.",
            "required_model": required_model,
            "actual_model": model,
        }
    return None


def _looks_like_auth_failure(output: str) -> bool:
    lowered = output.lower()
    needles = [
        "not logged in",
        "please log in",
        "login required",
        "authentication failed",
        "unauthorized",
        "invalid api key",
        "missing api key",
    ]
    return any(needle in lowered for needle in needles)


def _write_probe(artifacts: Path, data: dict[str, object]) -> None:
    (artifacts / "codex_probe.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (artifacts / "harness_report.txt").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
