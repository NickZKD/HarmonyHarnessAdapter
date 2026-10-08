from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TaskSpec:
    instance_id: str
    repo: Path
    instruction: str
    base_commit: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentResult:
    exit_code: int
    duration_sec: float
    stdout_path: Path
    stderr_path: Path
    timed_out: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PredictionRecord:
    instance_id: str
    model_name_or_path: str
    model_patch: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_jsonable(self) -> dict[str, Any]:
        return asdict(self)

