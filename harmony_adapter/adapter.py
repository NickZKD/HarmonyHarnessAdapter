from __future__ import annotations

from pathlib import Path

from harmony_adapter.artifacts import ArtifactStore
from harmony_adapter.config import HarmonyConfig
from harmony_adapter.device import HarmonyToolchain
from harmony_adapter.errors import EnvironmentError
from harmony_adapter.harness import HarnessRunner
from harmony_adapter.models import AgentResult, PredictionRecord, TaskSpec
from harmony_adapter.prompts import render_prompt
from harmony_adapter.workspace import WorkspaceManager


class HarmonyAdapter:
    name = "harmony"

    def __init__(self, config: HarmonyConfig | None = None) -> None:
        self.config = config or HarmonyConfig.from_env()
        self.toolchain = HarmonyToolchain(
            hdc_bin=self.config.hdc_bin,
            hvigor_bin=self.config.hvigor_bin,
            ohpm_bin=self.config.ohpm_bin,
            device_id=self.config.device_id,
            env=self.config.command_env(),
        )

    def validate_environment(self, require_tools: bool = False) -> list[str]:
        errors: list[str] = []
        for check in self.toolchain.checks():
            if not check.exists:
                errors.append(f"{check.name} not found at {check.path}")
            elif check.error:
                errors.append(f"{check.name} failed at {check.path}: {check.error}")
        if require_tools and errors:
            raise EnvironmentError("; ".join(errors))
        return errors

    def run_task(self, task: TaskSpec, run_id: str, harness_command: str | None = None) -> PredictionRecord:
        command = harness_command or self.config.harness_command
        if not command:
            raise EnvironmentError("No harness command configured.")

        store = ArtifactStore(self.config.artifacts_root, run_id)
        artifact_dir = store.instance_dir(task.instance_id)
        workspace = WorkspaceManager(store.run_root).prepare(task)

        contract = self.config.contract_snapshot()
        store.write_contract(artifact_dir, contract)
        prompt = render_prompt(
            task,
            budget=_format_budget(contract["budget"]),
            evaluation_criteria=str(contract["evaluation_criteria"]),
        )
        prompt_path = store.write_prompt(artifact_dir, prompt)

        runner = HarnessRunner(
            command_template=command,
            timeout_sec=self.config.timeout_sec,
            env=self.config.command_env(),
        )
        result = runner.run(task, workspace, prompt_path, artifact_dir)
        patch = WorkspaceManager(store.run_root).collect_patch(workspace)

        store.write_patch(artifact_dir, patch)
        store.write_metadata(
            artifact_dir,
            task,
            result,
            extra={
                "adapter": self.name,
                "model_name": self.config.model_name,
                "workspace": str(workspace),
                "contract_path": str(artifact_dir / "contract.json"),
                "control_contract": contract,
                "harmony": {
                    "sdk_home": str(self.config.sdk_home),
                    "node_home": str(self.config.node_home),
                    "device_id": self.config.device_id,
                },
            },
        )
        record = PredictionRecord(
            instance_id=task.instance_id,
            model_name_or_path=self.config.model_name,
            model_patch=patch,
            metadata={
                "adapter": self.name,
                "exit_code": result.exit_code,
                "duration_sec": result.duration_sec,
                "timed_out": result.timed_out,
                "artifact_dir": str(artifact_dir),
                "budget": contract["budget"],
                "evaluation_criteria": contract["evaluation_criteria"],
            },
        )
        store.append_prediction(record)
        return record

    def run_harmony_build(self, workspace: Path, target: str = "assembleHap") -> AgentResult:
        artifact_dir = workspace / ".harmony_adapter"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        command = f"{self.config.hvigor_bin} {target}"
        task = TaskSpec(instance_id="manual-build", repo=workspace, instruction=f"Run {target}")
        return HarnessRunner(command, self.config.timeout_sec, self.config.command_env()).run(
            task=task,
            workspace=workspace,
            prompt_path=artifact_dir / "prompt.txt",
            artifact_dir=artifact_dir,
        )


def _format_budget(budget: object) -> str:
    if not isinstance(budget, dict):
        return str(budget)
    parts = [f"timeout_sec={budget.get('timeout_sec')}"]
    if budget.get("max_turns") is not None:
        parts.append(f"max_turns={budget['max_turns']}")
    if budget.get("max_tokens") is not None:
        parts.append(f"max_tokens={budget['max_tokens']}")
    return ", ".join(parts)
