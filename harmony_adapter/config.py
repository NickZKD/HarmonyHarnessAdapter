from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_DEVECO_APP = Path("/Applications/DevEco-Studio.app/Contents")
DEFAULT_EVALUATION_CRITERIA = (
    "A submission is evaluated by the harness-owned tests and reports. The adapter records "
    "the runner-side git diff as the only accepted patch."
)


@dataclass(frozen=True)
class HarmonyConfig:
    dev_eco_home: Path = DEFAULT_DEVECO_APP
    sdk_home: Path = DEFAULT_DEVECO_APP / "sdk" / "default"
    node_home: Path = DEFAULT_DEVECO_APP / "tools" / "node"
    ohpm_bin: Path = DEFAULT_DEVECO_APP / "tools" / "ohpm" / "bin" / "ohpm"
    hvigor_bin: Path = DEFAULT_DEVECO_APP / "tools" / "hvigor" / "bin" / "hvigorw"
    hdc_bin: Path = DEFAULT_DEVECO_APP / "sdk" / "default" / "openharmony" / "toolchains" / "hdc"
    device_id: str | None = None
    harness_command: str | None = None
    timeout_sec: int = 3600
    max_turns: int | None = None
    max_tokens: int | None = None
    evaluation_criteria: str = DEFAULT_EVALUATION_CRITERIA
    model_name: str = "unknown"
    actual_model: str | None = None
    required_model: str | None = None
    required_variant: str | None = None
    require_model_lock: bool = False
    artifacts_root: Path = Path("artifacts")

    @classmethod
    def from_env(cls) -> "HarmonyConfig":
        dev_eco_home = Path(os.environ.get("DEVECO_HOME", str(DEFAULT_DEVECO_APP)))
        sdk_home = Path(os.environ.get("DEVECO_SDK_HOME", str(dev_eco_home / "sdk" / "default")))
        node_home = Path(
            os.environ.get(
                "HARMONY_NODE_HOME",
                os.environ.get("NODE_HOME", str(dev_eco_home / "tools" / "node")),
            )
        )
        return cls(
            dev_eco_home=dev_eco_home,
            sdk_home=sdk_home,
            node_home=node_home,
            ohpm_bin=Path(
                os.environ.get(
                    "HARMONY_OHPM_BIN",
                    str(dev_eco_home / "tools" / "ohpm" / "bin" / "ohpm"),
                )
            ),
            hvigor_bin=Path(
                os.environ.get(
                    "HARMONY_HVIGOR_BIN",
                    str(dev_eco_home / "tools" / "hvigor" / "bin" / "hvigorw"),
                )
            ),
            hdc_bin=Path(
                os.environ.get(
                    "HARMONY_HDC_BIN",
                    str(sdk_home / "openharmony" / "toolchains" / "hdc"),
                )
            ),
            device_id=os.environ.get("HARMONY_DEVICE_ID"),
            harness_command=os.environ.get("HARMONY_HARNESS_COMMAND"),
            timeout_sec=int(os.environ.get("HARMONY_TIMEOUT_SEC", "3600")),
            max_turns=_env_int("HARMONY_MAX_TURNS"),
            max_tokens=_env_int("HARMONY_MAX_TOKENS"),
            evaluation_criteria=os.environ.get(
                "HARMONY_EVALUATION_CRITERIA",
                DEFAULT_EVALUATION_CRITERIA,
            ),
            model_name=os.environ.get("HARMONY_MODEL_NAME", "unknown"),
            actual_model=os.environ.get("HARMONY_ACTUAL_MODEL"),
            required_model=os.environ.get("HARMONY_REQUIRED_MODEL"),
            required_variant=os.environ.get("HARMONY_REQUIRED_VARIANT"),
            require_model_lock=_env_bool("HARMONY_REQUIRE_MODEL_LOCK"),
            artifacts_root=Path(os.environ.get("HARMONY_ARTIFACTS_ROOT", "artifacts")),
        )

    def command_env(self) -> dict[str, str]:
        path_parts = [
            str(self.node_home / "bin"),
            str(self.ohpm_bin.parent),
            os.environ.get("PATH", ""),
        ]
        env = {
            "DEVECO_SDK_HOME": str(self.sdk_home),
            "NODE_HOME": str(self.node_home),
            "PATH": os.pathsep.join(path_parts),
            "HARMONY_TIMEOUT_SEC": str(self.timeout_sec),
        }
        if self.max_turns is not None:
            env["HARMONY_MAX_TURNS"] = str(self.max_turns)
        if self.max_tokens is not None:
            env["HARMONY_MAX_TOKENS"] = str(self.max_tokens)
        if self.actual_model:
            env["HARMONY_ACTUAL_MODEL"] = self.actual_model
        if self.required_model:
            env["HARMONY_REQUIRED_MODEL"] = self.required_model
        if self.required_variant:
            env["HARMONY_REQUIRED_VARIANT"] = self.required_variant
        if self.require_model_lock:
            env["HARMONY_REQUIRE_MODEL_LOCK"] = "1"
        return env

    def contract_snapshot(self) -> dict[str, object]:
        command_env = self.command_env()
        return {
            "prompt_policy": "adapter-rendered prompt is written to prompt.txt before harness execution",
            "environment": {
                "sdk_home": str(self.sdk_home),
                "node_home": str(self.node_home),
                "hdc_bin": str(self.hdc_bin),
                "hvigor_bin": str(self.hvigor_bin),
                "ohpm_bin": str(self.ohpm_bin),
                "device_id": self.device_id,
                "exported_keys": sorted(command_env.keys()),
            },
            "budget": {
                "timeout_sec": self.timeout_sec,
                "max_turns": self.max_turns,
                "max_tokens": self.max_tokens,
            },
            "model_lock": {
                "recorded_model_name": self.model_name,
                "actual_model": self.actual_model,
                "required_model": self.required_model,
                "required_variant": self.required_variant,
                "require_model_lock": self.require_model_lock,
            },
            "patch_policy": "runner-side git diff --binary from the prepared workspace",
            "evaluation_criteria": self.evaluation_criteria,
        }


def _env_int(name: str) -> int | None:
    value = os.environ.get(name)
    if not value:
        return None
    return int(value)


def _env_bool(name: str) -> bool:
    value = os.environ.get(name, "")
    return value.lower() in {"1", "true", "yes", "on"}
