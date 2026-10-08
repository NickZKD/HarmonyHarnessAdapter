from __future__ import annotations

from pathlib import Path

from harmony_adapter.models import AgentResult, PredictionRecord, TaskSpec
from harmony_adapter.utils import append_jsonl, ensure_dir, write_json


class ArtifactStore:
    def __init__(self, artifacts_root: Path, run_id: str) -> None:
        self.run_root = artifacts_root / run_id

    def instance_dir(self, instance_id: str) -> Path:
        return ensure_dir(self.run_root / instance_id)

    def write_prompt(self, artifact_dir: Path, prompt: str) -> Path:
        path = artifact_dir / "prompt.txt"
        path.write_text(prompt, encoding="utf-8")
        return path

    def write_patch(self, artifact_dir: Path, patch: str) -> Path:
        path = artifact_dir / "git.patch"
        path.write_text(patch, encoding="utf-8")
        return path

    def write_contract(self, artifact_dir: Path, contract: dict[str, object]) -> Path:
        path = artifact_dir / "contract.json"
        write_json(path, contract)
        return path

    def write_metadata(
        self,
        artifact_dir: Path,
        task: TaskSpec,
        result: AgentResult,
        extra: dict[str, object],
    ) -> Path:
        path = artifact_dir / "metadata.json"
        write_json(
            path,
            {
                "instance_id": task.instance_id,
                "exit_code": result.exit_code,
                "duration_sec": result.duration_sec,
                "timed_out": result.timed_out,
                "stdout_path": str(result.stdout_path),
                "stderr_path": str(result.stderr_path),
                "task_metadata": task.metadata,
                **extra,
            },
        )
        return path

    def append_prediction(self, record: PredictionRecord) -> Path:
        path = self.run_root / "predictions.jsonl"
        ensure_dir(path.parent)
        append_jsonl(path, record.to_jsonable())
        return path
