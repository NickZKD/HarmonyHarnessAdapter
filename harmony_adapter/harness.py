from __future__ import annotations

import os
import shlex
import subprocess
import time
from pathlib import Path

from harmony_adapter.errors import HarnessExecutionError
from harmony_adapter.models import AgentResult, TaskSpec


class HarnessRunner:
    def __init__(self, command_template: str, timeout_sec: int, env: dict[str, str] | None = None) -> None:
        self.command_template = command_template
        self.timeout_sec = timeout_sec
        self.env = env or {}

    def run(self, task: TaskSpec, workspace: Path, prompt_path: Path, artifact_dir: Path) -> AgentResult:
        stdout_path = artifact_dir / "agent_stdout.log"
        stderr_path = artifact_dir / "agent_stderr.log"
        command = self._render_command(task, workspace, prompt_path, artifact_dir)
        env = os.environ.copy()
        env.update(self.env)

        started = time.monotonic()
        timed_out = False
        try:
            with stdout_path.open("w", encoding="utf-8") as stdout_fh, stderr_path.open(
                "w", encoding="utf-8"
            ) as stderr_fh:
                process = subprocess.run(
                    command,
                    cwd=workspace,
                    env=env,
                    text=True,
                    stdout=stdout_fh,
                    stderr=stderr_fh,
                    timeout=self.timeout_sec,
                    check=False,
                )
                exit_code = process.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = 124
            with stderr_path.open("a", encoding="utf-8") as stderr_fh:
                stderr_fh.write(f"\nTimed out after {self.timeout_sec} seconds.\n")
        except OSError as exc:
            raise HarnessExecutionError(f"Could not start harness command: {exc}") from exc

        return AgentResult(
            exit_code=exit_code,
            duration_sec=round(time.monotonic() - started, 3),
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            timed_out=timed_out,
            metadata={"command": command},
        )

    def _render_command(self, task: TaskSpec, workspace: Path, prompt_path: Path, artifact_dir: Path) -> list[str]:
        rendered = self.command_template.format(
            workspace=str(workspace),
            prompt=str(prompt_path),
            instance_id=task.instance_id,
            artifacts=str(artifact_dir),
        )
        return shlex.split(rendered)

