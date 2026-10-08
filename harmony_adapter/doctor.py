from __future__ import annotations

from harmony_adapter.adapter import HarmonyAdapter
from harmony_adapter.config import HarmonyConfig


def main() -> int:
    config = HarmonyConfig.from_env()
    adapter = HarmonyAdapter(config)
    print("Harmony Harness Adapter doctor")
    print(f"DEVECO_SDK_HOME: {config.sdk_home}")
    print(f"NODE_HOME: {config.node_home}")
    print(f"device id: {config.device_id or '(default)'}")
    print()

    has_error = False
    for check in adapter.toolchain.checks():
        if not check.exists:
            has_error = True
            print(f"[missing] {check.name}: {check.path}")
        elif check.error:
            has_error = True
            print(f"[error]   {check.name}: {check.path} ({check.error})")
        else:
            print(f"[ok]      {check.name}: {check.path} ({check.version or 'found'})")
    return 1 if has_error else 0


if __name__ == "__main__":
    raise SystemExit(main())

