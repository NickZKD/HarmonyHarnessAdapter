class HarmonyAdapterError(RuntimeError):
    """Base error for adapter failures."""


class EnvironmentError(HarmonyAdapterError):
    """Raised when required Harmony tooling is missing or invalid."""


class HarnessExecutionError(HarmonyAdapterError):
    """Raised when the harness command cannot be started."""


class WorkspaceError(HarmonyAdapterError):
    """Raised when workspace preparation or patch collection fails."""

