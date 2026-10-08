from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path


APP_BINARY = Path("/Applications/BitFun.app/Contents/MacOS/bitfun-desktop")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_CLI_BINARY = PROJECT_ROOT / ".tools" / "BitFun" / "target" / "release" / "bitfun"


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
    model = os.environ.get("BITFUN_MODEL") or os.environ.get("HARMONY_ACTUAL_MODEL")
    lock_error = _model_lock_error(model)
    if lock_error:
        _write_probe(artifacts, lock_error)
        print(lock_error["reason"])
        return 76

    executable = _find_bitfun_exec()
    if executable is None:
        _write_probe(
            artifacts,
            {
                "status": "unsupported",
                "reason": "No headless BitFun CLI was found. Expected BITFUN_EXEC_BIN, `.tools/BitFun/target/release/bitfun`, or `bitfun` on PATH.",
                "desktop_app_found": APP_BINARY.exists(),
                "desktop_app_binary": str(APP_BINARY),
                "source_cli_binary": str(SOURCE_CLI_BINARY),
                "hint": "Build the source CLI with `cd .tools/BitFun/src/apps/cli && cargo build --release`, then rerun the benchmark.",
            },
        )
        print("BitFun desktop app/source tree found, but no built headless `bitfun` CLI is available.")
        return 78

    if model:
        switch_error = _set_default_model(executable, model, args.workspace, artifacts)
        if switch_error:
            _write_probe(artifacts, switch_error)
            print(switch_error["reason"])
            return 76

    command = [
        executable,
        "exec",
        "--auto",
        "--output-format",
        "json",
        prompt,
    ]
    env = os.environ.copy()
    env["HARMONY_INSTANCE_ID"] = args.instance_id
    result = subprocess.run(
        command,
        cwd=args.workspace,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=args.timeout,
        check=False,
    )
    (artifacts / "bitfun_stdout.log").write_text(result.stdout, encoding="utf-8")
    (artifacts / "bitfun_stderr.log").write_text(result.stderr, encoding="utf-8")
    output = result.stdout + "\n" + result.stderr
    config_error = _config_error(output)
    auth_error = _auth_error(output)
    status = "config_error" if config_error else "auth_required" if auth_error else "ran"
    _write_probe(
        artifacts,
        {
            "status": status,
            "executable": executable,
            "exit_code": result.returncode,
            "command_shape": "bitfun exec --auto --output-format json <prompt>",
            "model": model,
            **({"reason": config_error} if config_error else {}),
            **({"reason": auth_error} if auth_error else {}),
        },
    )
    print(result.stdout)
    if config_error:
        return 76
    if auth_error:
        return 77
    return result.returncode


def _find_bitfun_exec() -> str | None:
    override = os.environ.get("BITFUN_EXEC_BIN")
    if override:
        return override
    source_cli = Path(os.environ.get("BITFUN_SOURCE_CLI_BIN", str(SOURCE_CLI_BINARY)))
    if source_cli.exists():
        return str(source_cli)
    found = shutil.which("bitfun")
    if found:
        return found
    return None


def _set_default_model(executable: str, model: str, workspace: str, artifacts: Path) -> dict[str, object] | None:
    result = subprocess.run(
        [executable, "models", "set-default", model],
        cwd=workspace,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    (artifacts / "bitfun_model_select_stdout.log").write_text(result.stdout, encoding="utf-8")
    (artifacts / "bitfun_model_select_stderr.log").write_text(result.stderr, encoding="utf-8")
    if result.returncode == 0:
        return None
    return {
        "status": "config_error",
        "reason": f"BitFun failed to select model {model!r}: {(result.stderr or result.stdout).strip()}",
        "model": model,
        "exit_code": result.returncode,
    }


def _model_lock_error(model: str | None) -> dict[str, object] | None:
    required_model = os.environ.get("HARMONY_REQUIRED_MODEL")
    require_lock = os.environ.get("HARMONY_REQUIRE_MODEL_LOCK", "").lower() in {"1", "true", "yes", "on"}
    if required_model and model != required_model:
        return {
            "status": "config_error",
            "reason": f"BitFun model mismatch: required {required_model!r}, got {model!r}.",
            "required_model": required_model,
            "actual_model": model,
        }
    if require_lock and not model:
        return {
            "status": "model_unlocked",
            "reason": "BitFun model lock is required, but BITFUN_MODEL/HARMONY_ACTUAL_MODEL is not set.",
            "required_model": required_model,
            "actual_model": model,
        }
    return None


def _config_error(output: str) -> str | None:
    lowered = output.lower()
    if "primary model not configured or invalid" in lowered:
        return "BitFun primary model is not configured or invalid. Configure an enabled AI model and set it as the primary model."
    if "no ai models configured" in lowered:
        return "BitFun has no configured AI models."
    if "ai provider error" in lowered and any(
        marker in lowered
        for marker in (
            "400 bad request",
            "404 not found",
            "model not found",
            "model_not_found",
            "invalid model",
            "invalid request",
        )
    ):
        return "BitFun model endpoint/model configuration failed. Check the selected model id, provider protocol, and base URL."
    return None


def _auth_error(output: str) -> str | None:
    lowered = output.lower()
    auth_markers = [
        "401 unauthorized",
        "403 forbidden",
        "authorized_error",
        "authorization",
        "api secret key",
        "api key",
        "authentication",
        "unauthorized",
    ]
    if "ai provider error" in lowered and any(marker in lowered for marker in auth_markers):
        return "BitFun model authentication failed. Check the selected model endpoint and API key/header configuration."
    return None


def _write_probe(artifacts: Path, data: dict[str, object]) -> None:
    (artifacts / "bitfun_probe.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (artifacts / "harness_report.txt").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
