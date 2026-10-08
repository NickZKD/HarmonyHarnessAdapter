from __future__ import annotations

import argparse
from pathlib import Path

from harmony_adapter.adapter import HarmonyAdapter
from harmony_adapter.config import HarmonyConfig
from harmony_adapter.doctor import main as doctor_main
from harmony_adapter.models import TaskSpec


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harmony-adapter")
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("doctor", help="Check local Harmony tooling.")
    gui = subcommands.add_parser("gui", help="Start the local web GUI.")
    gui.add_argument("--host", default="127.0.0.1")
    gui.add_argument("--port", default=8765, type=int)

    benchmark = subcommands.add_parser("benchmark", help="Run the built-in Harmony benchmark demo.")
    benchmark.add_argument("--artifacts-root", type=Path, default=Path("artifacts") / "benchmark-demo")
    benchmark.add_argument("--timeout", type=int, default=120)
    benchmark.add_argument("--max-tokens", type=int, default=200000)
    benchmark.add_argument("--no-build", action="store_true", help="Disable Harmony build validation.")
    benchmark.add_argument("--build-target", default="assembleHap", help="hvigor build target for Harmony validation.")
    benchmark.add_argument("--build-timeout", type=int, default=300, help="Harmony build validation timeout in seconds.")
    benchmark.add_argument("--required-model", help="Require harnesses to use this model when supported.")
    benchmark.add_argument("--required-variant", help="Require harnesses to use this model variant/profile when supported.")
    benchmark.add_argument("--require-model-lock", action="store_true", help="Fail wrappers that cannot prove a fixed model.")
    benchmark.add_argument("--harness", action="append", help="Custom harness in name=command format. Defaults to Codex and BitFun CLI.")

    factory = subcommands.add_parser("benchmark-factory", help="Generate standardized SWE-type Harmony task packages.")
    factory.add_argument("--repo", action="append", type=Path, help="Existing Harmony repository path. Can be passed multiple times.")
    factory.add_argument("--output-root", type=Path, default=Path("artifacts") / "benchmark-factory")
    factory.add_argument("--cache-root", type=Path, default=Path("artifacts") / "seed-repos")
    factory.add_argument("--online", action="store_true", help="Clone default online seed repositories when missing.")
    factory.add_argument("--max-tasks-per-repo", type=int, default=4)

    run = subcommands.add_parser("run", help="Run one Harmony harness task.")
    run.add_argument("--instance-id", required=True)
    run.add_argument("--repo", required=True, type=Path)
    run.add_argument("--instruction", help="Task instruction text.")
    run.add_argument("--instruction-file", type=Path, help="Path to task instruction text.")
    run.add_argument("--run-id", required=True)
    run.add_argument("--harness-command", help="Command template used to launch the harness.")
    run.add_argument("--base-commit", help="Optional commit to checkout before running.")
    run.add_argument("--model", help="Model name recorded in predictions.")
    run.add_argument("--timeout", type=int, help="Per-instance timeout in seconds.")
    run.add_argument("--max-turns", type=int, help="Optional agent turn budget recorded and exported.")
    run.add_argument("--max-tokens", type=int, help="Optional token budget recorded and exported.")
    run.add_argument("--evaluation-criteria", help="Evaluation criteria recorded in prompt and metadata.")
    run.add_argument("--required-model", help="Required model recorded in the adapter contract and exported to harnesses.")
    run.add_argument("--required-variant", help="Required variant/profile recorded in the adapter contract and exported.")
    run.add_argument("--require-model-lock", action="store_true", help="Require wrappers to prove a fixed model.")
    run.add_argument("--artifacts-root", type=Path, help="Artifact output root.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "doctor":
        return doctor_main()

    if args.command == "gui":
        from harmony_adapter.gui import serve

        serve(host=args.host, port=args.port)
        return 0

    if args.command == "benchmark":
        from harmony_adapter.benchmark import (
            _parse_harnesses,
            default_harnesses,
            run_benchmark,
        )
        from harmony_adapter.evaluation import EvaluationOptions
        import json

        harnesses = _parse_harnesses(args.harness) if args.harness else default_harnesses()
        summary = run_benchmark(
            harnesses,
            artifacts_root=args.artifacts_root,
            timeout_sec=args.timeout,
            max_tokens=args.max_tokens,
            required_model=args.required_model,
            required_variant=args.required_variant,
            require_model_lock=args.require_model_lock,
            evaluation_options=EvaluationOptions(
                run_build=not args.no_build,
                build_target=args.build_target,
                build_timeout_sec=args.build_timeout,
            ),
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    if args.command == "benchmark-factory":
        from harmony_adapter.benchmark_factory import generate_factory, materialize_default_seed_repos
        import json

        if args.repo:
            repos = args.repo
            seeds = []
        else:
            materialized = materialize_default_seed_repos(args.cache_root, online=args.online)
            repos = materialized["repos"]
            seeds = materialized["seeds"]
        summary = generate_factory(repos, args.output_root, max_tasks_per_repo=args.max_tasks_per_repo)
        summary["seeds"] = seeds
        from harmony_adapter.utils import write_json

        write_json(args.output_root / "factory_summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    if args.command == "run":
        instruction = _load_instruction(args)
        config = _config_from_args(args)
        adapter = HarmonyAdapter(config)
        task = TaskSpec(
            instance_id=args.instance_id,
            repo=args.repo,
            instruction=instruction,
            base_commit=args.base_commit,
        )
        record = adapter.run_task(task, run_id=args.run_id, harness_command=args.harness_command)
        print(f"instance_id={record.instance_id}")
        print(f"patch_bytes={len(record.model_patch.encode('utf-8'))}")
        print(f"artifact_dir={record.metadata['artifact_dir']}")
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


def _load_instruction(args: argparse.Namespace) -> str:
    if args.instruction and args.instruction_file:
        raise SystemExit("Use either --instruction or --instruction-file, not both.")
    if args.instruction_file:
        return args.instruction_file.read_text(encoding="utf-8")
    if args.instruction:
        return args.instruction
    raise SystemExit("One of --instruction or --instruction-file is required.")


def _config_from_args(args: argparse.Namespace) -> HarmonyConfig:
    config = HarmonyConfig.from_env()
    values = {
        "harness_command": args.harness_command or config.harness_command,
        "timeout_sec": args.timeout or config.timeout_sec,
        "max_turns": args.max_turns if args.max_turns is not None else config.max_turns,
        "max_tokens": args.max_tokens if args.max_tokens is not None else config.max_tokens,
        "evaluation_criteria": args.evaluation_criteria or config.evaluation_criteria,
        "model_name": args.model or config.model_name,
        "required_model": args.required_model or config.required_model,
        "required_variant": args.required_variant or config.required_variant,
        "require_model_lock": args.require_model_lock or config.require_model_lock,
        "artifacts_root": args.artifacts_root or config.artifacts_root,
    }
    return HarmonyConfig(
        dev_eco_home=config.dev_eco_home,
        sdk_home=config.sdk_home,
        node_home=config.node_home,
        ohpm_bin=config.ohpm_bin,
        hvigor_bin=config.hvigor_bin,
        hdc_bin=config.hdc_bin,
        device_id=config.device_id,
        **values,
    )


if __name__ == "__main__":
    raise SystemExit(main())
