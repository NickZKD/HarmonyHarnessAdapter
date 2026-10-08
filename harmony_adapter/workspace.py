from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from harmony_adapter.errors import WorkspaceError
from harmony_adapter.models import TaskSpec
from harmony_adapter.utils import ensure_dir


class WorkspaceManager:
    def __init__(self, run_root: Path) -> None:
        self.run_root = run_root

    def prepare(self, task: TaskSpec) -> Path:
        if not task.repo.exists():
            raise WorkspaceError(f"Repository does not exist: {task.repo}")
        if not task.repo.is_dir():
            raise WorkspaceError(f"Repository is not a directory: {task.repo}")

        workspace = self.run_root / task.instance_id / "workspace"
        if workspace.exists():
            shutil.rmtree(workspace)
        ensure_dir(workspace.parent)
        shutil.copytree(
            task.repo,
            workspace,
            ignore=shutil.ignore_patterns(".git", "oh_modules", "build", ".hvigor"),
        )

        source_git = task.repo / ".git"
        if source_git.exists():
            shutil.copytree(source_git, workspace / ".git")

        if task.base_commit:
            self._run_git(["checkout", "--detach", task.base_commit], workspace)
        return workspace

    def collect_patch(self, workspace: Path) -> str:
        self._ensure_git_repo(workspace)
        result = self._run_git(["diff", "--binary"], workspace, check=False)
        if result.returncode not in (0, 1):
            raise WorkspaceError(result.stderr.strip() or "git diff failed")
        return result.stdout

    def current_commit(self, workspace: Path) -> str | None:
        result = self._run_git(["rev-parse", "HEAD"], workspace, check=False)
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    def _ensure_git_repo(self, workspace: Path) -> None:
        result = self._run_git(["rev-parse", "--show-toplevel"], workspace, check=False)
        if result.returncode != 0:
            raise WorkspaceError(f"Workspace is not a git repository: {workspace}")

    def _run_git(
        self,
        args: list[str],
        cwd: Path,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if check and result.returncode != 0:
            raise WorkspaceError(result.stderr.strip() or f"git {' '.join(args)} failed")
        return result

