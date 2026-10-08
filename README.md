# Harmony Harness Adapter

Harmony Harness Adapter is a small Claw-SWE-Bench-style adapter layer for running HarmonyOS harness evaluations.

The first version focuses on a stable local workflow:

1. Prepare an isolated workspace for one benchmark instance.
2. Render a deterministic task prompt.
3. Run a configurable Harmony harness command.
4. Collect runner-side `git diff`, logs, reports, and metadata.
5. Append a standard prediction record to `predictions.jsonl`.

## Quick Start

```bash
python3 -m harmony_adapter.doctor

python3 -m harmony_adapter.cli gui --host 127.0.0.1 --port 8765

python3 -m harmony_adapter.cli benchmark \
  --artifacts-root /private/tmp/harmony_adapter_benchmark_artifacts

python3 -m harmony_adapter.cli run \
  --instance-id demo-001 \
  --repo /path/to/harmony/project \
  --instruction-file /path/to/task.md \
  --run-id local-demo \
  --harness-command "python3 harness.py --prompt {prompt} --workspace {workspace}"
```

Open the GUI at:

```text
http://127.0.0.1:8765
```

Artifacts are written to:

```text
artifacts/<run-id>/<instance-id>/
```

The shared predictions file is:

```text
artifacts/<run-id>/predictions.jsonl
```

Benchmark history is appended to:

```text
artifacts/evaluation_history.jsonl
```

Set `HARMONY_HISTORY_PATH` to use a different history file. Each history entry stores the benchmark summary, artifacts path, harness scores, pass counts, and token usage when the harness exposes it. If token usage cannot be parsed from harness logs or reports, the value is recorded as `null` instead of being estimated.

## Environment

Most paths can be inferred from a DevEco Studio installation, but these variables are supported:

| Variable | Purpose |
| --- | --- |
| `DEVECO_SDK_HOME` | OpenHarmony SDK root. |
| `HARMONY_NODE_HOME` or `NODE_HOME` | DevEco bundled Node.js home. |
| `HARMONY_OHPM_BIN` | Explicit `ohpm` binary path. |
| `HARMONY_HVIGOR_BIN` | Explicit `hvigorw` binary path. |
| `HARMONY_HDC_BIN` | Explicit `hdc` binary path. |
| `HARMONY_DEVICE_ID` | Optional target device id for `hdc -t`. |
| `HARMONY_HARNESS_COMMAND` | Default harness command template. |
| `HARMONY_REQUIRED_MODEL` | Model name that wrappers must prove they are using. |
| `HARMONY_REQUIRED_VARIANT` | Optional model variant/profile that wrappers must prove they are using. |
| `HARMONY_REQUIRE_MODEL_LOCK` | Set to `1` to fail wrappers that cannot prove a fixed model. |
| `HARMONY_HISTORY_PATH` | Optional JSONL path for persistent benchmark history. |

Command templates receive:

| Placeholder | Meaning |
| --- | --- |
| `{workspace}` | Prepared workspace path. |
| `{prompt}` | Rendered prompt file path. |
| `{instance_id}` | Benchmark instance id. |
| `{artifacts}` | Per-instance artifact directory. |

## Design

The adapter keeps Harmony-specific execution behind a narrow contract:

```text
Benchmark task -> HarmonyAdapter -> Harmony harness -> artifacts + prediction
```

Patch collection is always runner-side via `git diff`. The harness can write files and reports, but it does not get to self-report the final patch.

## Built-in Benchmark Demo

The built-in benchmark creates four tiny Harmony/ArkTS-style repositories and scores each harness with adapter-owned rules:

| Case | Checks |
| --- | --- |
| `harmony-counter-state` | ArkTS counter increments by `1`, not `2`. |
| `harmony-router-target` | Router goes to `pages/Home`, not `pages/Login`. |
| `harmony-module-install` | `deliveryWithInstall` is `true`. |
| `harmony-hilog-domain` | `hilog.info` uses domain `0x0001`. |

Run the bundled comparison:

```bash
python3 -m harmony_adapter.cli benchmark \
  --artifacts-root /private/tmp/harmony_adapter_benchmark_artifacts
```

Scoring now has three layers:

| Layer | Purpose |
| --- | --- |
| Oracle | Case-specific `contains` / `not_contains` checks decide task correctness. |
| Patch scope | The patch must not modify files outside the case fixture. |
| Harmony build | If the workspace has Harmony build metadata, `hvigorw assembleHap` runs after the patch. Tiny demo fixtures skip this layer explicitly. |

Use `--no-build` for fast static-only runs, or configure the build validator:

```bash
python3 -m harmony_adapter.cli benchmark \
  --build-target assembleHap \
  --build-timeout 600
```

To make model control explicit, require a locked model:

```bash
CODEX_MODEL=your-fixed-model-id \
BITFUN_MODEL=your-fixed-model-id \
python3 -m harmony_adapter.cli benchmark \
  --required-model your-fixed-model-id \
  --require-model-lock
```

The Codex wrapper proves this with `CODEX_MODEL` or `HARMONY_REQUIRED_MODEL`. The BitFun wrapper checks `BITFUN_MODEL` or `HARMONY_ACTUAL_MODEL`. If a wrapper cannot prove the requested model, the run is marked `model_unlocked` or `config_error` and is not treated as a capability score.

The default real harness set is Codex + BitFun CLI:

```bash
CODEX_MODEL=your-fixed-model-id \
BITFUN_MODEL=your-fixed-model-id \
python3 -m harmony_adapter.cli benchmark \
  --required-model your-fixed-model-id \
  --require-model-lock \
  --artifacts-root /private/tmp/harmony_adapter_real_artifacts
```

The Codex wrapper looks for `CODEX_EXEC_BIN`, then `codex` on `PATH`, then the ChatGPT.app bundled binary at `/Applications/ChatGPT.app/Contents/Resources/codex`. It probes `codex exec --help` and only passes options supported by the installed CLI. On current ChatGPT.app builds it runs roughly:

```text
codex exec -C <workspace> --sandbox workspace-write --skip-git-repo-check --ephemeral --ignore-rules [-m <model>] -
```

This compares:

| Harness | Meaning |
| --- | --- |
| `codex` | Local Codex CLI through `codex exec`. |
| `bitfun` | Local BitFun CLI through `bitfun exec`. |

To score your own harness:

```bash
python3 -m harmony_adapter.cli benchmark \
  --harness "my_harness=python3 /path/to/harness.py --prompt {prompt} --workspace {workspace} --artifacts {artifacts} --instance-id {instance_id}"
```

To run only BitFun:

```bash
python3 -m harmony_adapter.cli benchmark \
  --harness "bitfun=python3 /Users/boom/Documents/HarmonyHarnessAdapter/harmony_adapter/builtin_harnesses/bitfun_exec.py --prompt {prompt} --workspace {workspace} --artifacts {artifacts} --instance-id {instance_id}" \
  --artifacts-root /private/tmp/harmony_adapter_bitfun_artifacts
```

The BitFun wrapper expects a headless command named `bitfun` on `PATH`, compatible with:

```bash
bitfun exec --auto --output-format json "<prompt>"
```

You can also point to a custom executable with `BITFUN_EXEC_BIN=/path/to/bitfun`. If the GCWing/BitFun source tree exists under `.tools/BitFun`, the wrapper also checks the source-built binary at:

```text
.tools/BitFun/target/release/bitfun
```

The source repository exposes a CLI crate at `src/apps/cli` and can be built with Rust:

```bash
git clone https://github.com/GCWing/BitFun .tools/BitFun
cd .tools/BitFun/src/apps/cli
cargo build --release
```

This workspace already expects the source-built CLI path above. BitFun must also have at least one enabled AI model and a primary/default model; check this with `bitfun models list`. If the list is empty or the primary model is invalid, HarmonyAdapter records the run as `config_error` instead of treating it as a capability score. If model locking is required, set `BITFUN_MODEL` or `HARMONY_ACTUAL_MODEL` to the model that BitFun has been configured to use.

## Benchmark Factory

`benchmark-factory` generates standardized SWE-type Harmony task packages from real Harmony repositories.

```bash
python3 -m harmony_adapter.cli benchmark-factory \
  --repo artifacts/seed-repos/harmonyos_readerkit_sample \
  --repo artifacts/seed-repos/native_multi_threads \
  --output-root artifacts/benchmark-factory
```

Each generated `task.json` contains:

```text
repo, base_commit, problem_statement, reference_patch,
fail_to_pass, pass_to_pass, test_command, build_command,
ui_oracle, difficulty, tags, hidden_validation
```

The first factory version supports:

| Mode | Source signal |
| --- | --- |
| `Commit2Task` | Parent commit as base, target commit as hidden reference, commit diff as gold patch. |
| `Test2Task` | Existing tests guide controlled defect injection when test files are discoverable. |
| `Build2Task` | ArkTS import/module/build defects with Hvigor/HAP validation metadata. |
| `UI2Task` | ArkUI pages with component tree, page property, resource, interaction, and screenshot-assist oracle fields. |

Factory output is written to:

```text
artifacts/benchmark-factory/factory_summary.json
artifacts/benchmark-factory/tasks/<instance-id>/task.json
```

The GUI shows the generated task packages in the **Benchmark Factory** panel under control conditions. Click **Generate Tasks** to regenerate packages, or **View Detail** to inspect a single `task.json`.

Quality gates are recorded per task:

```text
Base-Fail, Patch-Pass, Leakage Check, Hidden Oracle, Manual Audit
```

Heavy validation such as running full Hvigor builds on every real repository is recorded as `needs_validation` or `synthetic_expected` in this first version; the task package keeps the commands and hidden oracle metadata ready for a later batch validator.
