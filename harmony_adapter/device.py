from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ToolCheck:
    name: str
    path: Path
    exists: bool
    version: str | None = None
    error: str | None = None


class HarmonyToolchain:
    def __init__(
        self,
        hdc_bin: Path,
        hvigor_bin: Path,
        ohpm_bin: Path,
        device_id: str | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.hdc_bin = hdc_bin
        self.hvigor_bin = hvigor_bin
        self.ohpm_bin = ohpm_bin
        self.device_id = device_id
        self.env = env or {}

    def checks(self) -> list[ToolCheck]:
        return [
            self._check("hdc", self.hdc_bin, ["-v"]),
            self._check("hvigorw", self.hvigor_bin, ["--version"]),
            self._check("ohpm", self.ohpm_bin, ["--version"]),
        ]

    def list_devices(self) -> subprocess.CompletedProcess[str]:
        cmd = [str(self.hdc_bin), "list", "targets"]
        if self.device_id:
            cmd = [str(self.hdc_bin), "-t", self.device_id, "list", "targets"]
        return subprocess.run(
            cmd,
            env=self._merged_env(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def _check(self, name: str, path: Path, args: list[str]) -> ToolCheck:
        if not path.exists():
            return ToolCheck(name=name, path=path, exists=False)
        try:
            result = subprocess.run(
                [str(path), *args],
                env=self._merged_env(),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=15,
                check=False,
            )
        except OSError as exc:
            return ToolCheck(name=name, path=path, exists=True, error=str(exc))
        except subprocess.TimeoutExpired:
            return ToolCheck(name=name, path=path, exists=True, error="version command timed out")

        output = (result.stdout or result.stderr).strip()
        if result.returncode != 0:
            return ToolCheck(name=name, path=path, exists=True, error=output or "version command failed")
        return ToolCheck(name=name, path=path, exists=True, version=output.splitlines()[0] if output else None)

    def _merged_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(self.env)
        return env
