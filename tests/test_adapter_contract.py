from __future__ import annotations

import subprocess
import tempfile
import unittest
import os
import json
from http import HTTPStatus
from pathlib import Path

from harmony_adapter.adapter import HarmonyAdapter
from harmony_adapter.benchmark import CASES, run_benchmark
from harmony_adapter.benchmark import _token_usage_from_text
from harmony_adapter.benchmark_factory import generate_factory
from harmony_adapter.config import HarmonyConfig
from harmony_adapter.evaluation import EvaluationOptions, evaluate_case
from harmony_adapter.history import append_evaluation_history, read_evaluation_history
from harmony_adapter.gui import GuiHandler, HTML
from harmony_adapter.gui import _harness_catalog, _prepare_demo, _run_adapter
from harmony_adapter.models import TaskSpec
from harmony_adapter.prompts import render_prompt


class HarmonyAdapterContractTest(unittest.TestCase):
    def test_render_prompt_includes_instance_and_instruction(self) -> None:
        task = TaskSpec(instance_id="harmony-001", repo=Path("."), instruction="Fix the login flow.")

        prompt = render_prompt(task)

        self.assertIn("harmony-001", prompt)
        self.assertIn("Fix the login flow.", prompt)
        self.assertIn("git diff", prompt)

    def test_run_task_collects_runner_side_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            artifacts = root / "artifacts"
            repo.mkdir()
            (repo / "entry.txt").write_text("before\n", encoding="utf-8")
            self._git(repo, "init")
            self._git(repo, "config", "user.email", "adapter@example.test")
            self._git(repo, "config", "user.name", "Adapter Test")
            self._git(repo, "add", "entry.txt")
            self._git(repo, "commit", "-m", "initial")

            command = (
                "python3 -c "
                "\"from pathlib import Path; Path('entry.txt').write_text('after\\n', encoding='utf-8')\""
            )
            config = HarmonyConfig(artifacts_root=artifacts, harness_command=command, timeout_sec=30)
            adapter = HarmonyAdapter(config)
            task = TaskSpec(instance_id="case-001", repo=repo, instruction="Change entry.txt.")

            record = adapter.run_task(task, run_id="test-run")

            self.assertEqual(record.instance_id, "case-001")
            self.assertIn("-before", record.model_patch)
            self.assertIn("+after", record.model_patch)
            self.assertIn("budget", record.metadata)
            self.assertIn("evaluation_criteria", record.metadata)
            self.assertTrue((artifacts / "test-run" / "case-001" / "contract.json").exists())
            self.assertTrue((artifacts / "test-run" / "case-001" / "git.patch").exists())
            self.assertTrue((artifacts / "test-run" / "predictions.jsonl").exists())

    def test_gui_demo_runs_through_adapter(self) -> None:
        demo = _prepare_demo()

        result = _run_adapter(demo)

        self.assertEqual(result["instance_id"], "gui-demo-001")
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("-ability: pending", result["patch"])
        self.assertIn("+ability: implemented from GUI demo", result["patch"])
        self.assertIn("GUI demo harness updated App.ets", result["stdout"])
        self.assertIn("evaluation_criteria", result["contract_json"])
        self.assertEqual(result["contract_json"]["budget"]["max_tokens"], 200000)

    def test_gui_doctor_supports_browser_get(self) -> None:
        self.assertIn("/api/doctor", GuiHandler.do_GET.__code__.co_consts)
        self.assertIn("/api/benchmark-harness", str(GuiHandler.do_POST.__code__.co_consts))
        self.assertIn("score-detail", HTML)
        self.assertEqual(HTTPStatus.OK.value, 200)

    def test_gui_catalog_only_shows_real_harnesses(self) -> None:
        harness_names = {item["name"] for item in _harness_catalog()}

        self.assertEqual(harness_names, {"codex", "bitfun"})

    def test_config_exports_selected_actual_model(self) -> None:
        config = HarmonyConfig(actual_model="minimax-m3")

        self.assertEqual(config.command_env()["HARMONY_ACTUAL_MODEL"], "minimax-m3")
        self.assertEqual(config.contract_snapshot()["model_lock"]["actual_model"], "minimax-m3")

    def test_benchmark_scores_built_in_harnesses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            harnesses = {"test_solver": self._test_solver_command(Path(tmp))}
            summary = run_benchmark(harnesses, artifacts_root=Path(tmp) / "artifacts", timeout_sec=30)

            self.assertEqual(summary["case_count"], 4)
            self.assertIn("patch_scope", summary["evaluation_mode"])
            self.assertEqual(summary["harnesses"]["test_solver"]["passed"], 4)
            self.assertEqual(summary["harnesses"]["test_solver"]["score"], 1.0)
            self.assertIn("token_usage", summary)
            self.assertTrue((Path(tmp) / "artifacts" / "benchmark_summary.json").exists())

    def test_token_usage_parser_reads_codex_text(self) -> None:
        usage = _token_usage_from_text("done\n\ntokens used\n14,211\n")

        self.assertEqual(usage["total"], 14211)

    def test_evaluation_history_records_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            history_path = Path(tmp) / "history.jsonl"
            summary = {
                "benchmark_root": "/tmp/bench",
                "artifacts_root": "/tmp/artifacts",
                "case_count": 1,
                "token_usage": {"total": 42, "source": "test"},
                "harnesses": {
                    "codex": {
                        "status": "scored",
                        "passed": 1,
                        "total": 1,
                        "pass_rate": 1.0,
                        "score": 1.0,
                        "token_usage": {"total": 42, "source": "case_sum"},
                    }
                },
            }

            entry = append_evaluation_history(summary, label="test-run", trigger="unit", history_path=history_path)
            entries = read_evaluation_history(history_path=history_path)

            self.assertEqual(entry["token_usage"]["total"], 42)
            self.assertEqual(entries[0]["label"], "test-run")
            self.assertEqual(entries[0]["harnesses"]["codex"]["score"], 1.0)

    def test_benchmark_factory_generates_standardized_task_packages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            (repo / "entry/src/main/ets/pages").mkdir(parents=True)
            (repo / "entry/src/main/ets/pages/Index.ets").write_text(
                "\n".join(
                    [
                        "@Entry",
                        "@Component",
                        "struct Index {",
                        "  build() {",
                        "    Column() {",
                        "      Text('Factory')",
                        "      Button('Run').onClick(() => {})",
                        "    }",
                        "  }",
                        "}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (repo / "build-profile.json5").write_text("{ app: { products: [] } }\n", encoding="utf-8")
            self._git(repo, "init")
            self._git(repo, "config", "user.email", "factory@example.test")
            self._git(repo, "config", "user.name", "Factory Test")
            self._git(repo, "add", ".")
            self._git(repo, "commit", "-m", "initial app")
            source = repo / "entry/src/main/ets/pages/Index.ets"
            source.write_text(source.read_text(encoding="utf-8").replace("Factory", "Factory Fixed"), encoding="utf-8")
            self._git(repo, "add", ".")
            self._git(repo, "commit", "-m", "fix UI title")

            summary = generate_factory([repo], root / "factory", max_tasks_per_repo=4)

            self.assertGreaterEqual(len(summary["tasks"]), 3)
            task_types = {task["task_type"] for task in summary["tasks"]}
            self.assertIn("Commit2Task", task_types)
            self.assertIn("Build2Task", task_types)
            self.assertIn("UI2Task", task_types)
            package = Path(next(task["package"] for task in summary["tasks"] if task["task_type"] == "UI2Task"))
            data = json.loads(package.read_text(encoding="utf-8"))
            self.assertEqual(data["task_type"], "UI2Task")
            self.assertIn("ui_oracle", data)
            self.assertIn("reference_patch", data)

    def test_evaluation_rejects_unrelated_file_edits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            case = CASES[0]
            for file_spec in case.files:
                path = repo / file_spec.path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(file_spec.content, encoding="utf-8")
            (repo / "README.md").write_text("unexpected\n", encoding="utf-8")
            self._git(repo, "init")
            self._git(repo, "config", "user.email", "adapter@example.test")
            self._git(repo, "config", "user.name", "Adapter Test")
            self._git(repo, "add", ".")
            self._git(repo, "commit", "-m", "initial")
            (repo / case.files[0].path).write_text(case.files[0].content.replace("this.count += 2", "this.count += 1"), encoding="utf-8")
            (repo / "README.md").write_text("unexpected change\n", encoding="utf-8")

            result = evaluate_case(case, repo, HarmonyConfig(), EvaluationOptions(run_build=False))

            self.assertFalse(result["passed"])
            self.assertEqual(result["patch_scope"]["unexpected_files"], ["README.md"])

    def test_codex_wrapper_checks_model_lock_before_running(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts = root / "artifacts"
            artifacts.mkdir()
            fake_codex = root / "codex"
            fake_codex.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_codex.chmod(0o755)
            prompt = artifacts / "prompt.txt"
            prompt.write_text("Fix task\n", encoding="utf-8")
            command = (
                "python3 "
                f"{Path.cwd() / 'harmony_adapter' / 'builtin_harnesses' / 'codex_exec.py'} "
                f"--prompt {prompt} --workspace {root} --artifacts {artifacts} --instance-id lock-test"
            )
            env = os.environ.copy()
            env["CODEX_EXEC_BIN"] = str(fake_codex)
            env["HARMONY_REQUIRE_MODEL_LOCK"] = "1"
            env.pop("CODEX_MODEL", None)
            env.pop("HARMONY_REQUIRED_MODEL", None)

            result = subprocess.run(command.split(), env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)

            self.assertEqual(result.returncode, 76)
            self.assertIn("model_unlocked", (artifacts / "codex_probe.json").read_text(encoding="utf-8"))

    def test_codex_wrapper_omits_unsupported_approval_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts = root / "artifacts"
            artifacts.mkdir()
            fake_codex = root / "codex"
            args_file = root / "args.txt"
            fake_codex.write_text(
                "\n".join(
                    [
                        "#!/bin/sh",
                        "if [ \"$1\" = \"exec\" ] && [ \"$2\" = \"--help\" ]; then",
                        "  printf '%s\\n' 'Usage: codex exec [OPTIONS] [PROMPT]' '  -C, --cd <DIR>' '  --sandbox <SANDBOX_MODE>' '  --skip-git-repo-check' '  --ephemeral' '  --ignore-rules' '  -m, --model <MODEL>'",
                        "  exit 0",
                        "fi",
                        "printf '%s\\n' \"$@\" > \"$CODEX_ARGS_FILE\"",
                        "cat >/dev/null",
                        "exit 0",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)
            prompt = artifacts / "prompt.txt"
            prompt.write_text("Fix task\n", encoding="utf-8")
            command = [
                "python3",
                str(Path.cwd() / "harmony_adapter" / "builtin_harnesses" / "codex_exec.py"),
                "--prompt",
                str(prompt),
                "--workspace",
                str(root),
                "--artifacts",
                str(artifacts),
                "--instance-id",
                "compat-test",
            ]
            env = os.environ.copy()
            env["CODEX_EXEC_BIN"] = str(fake_codex)
            env["CODEX_ARGS_FILE"] = str(args_file)
            env["CODEX_MODEL"] = "fixed-model"

            result = subprocess.run(command, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)

            self.assertEqual(result.returncode, 0)
            args_text = args_file.read_text(encoding="utf-8")
            self.assertIn("--sandbox", args_text)
            self.assertIn("--skip-git-repo-check", args_text)
            self.assertNotIn("--ask-for-approval", args_text)
            probe = (artifacts / "codex_probe.json").read_text(encoding="utf-8")
            self.assertIn("--sandbox workspace-write", probe)
            self.assertIn("--ask-for-approval", probe)

    def test_codex_wrapper_does_not_mark_successful_login_text_as_auth_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts = root / "artifacts"
            artifacts.mkdir()
            fake_codex = root / "codex"
            fake_codex.write_text(
                "\n".join(
                    [
                        "#!/bin/sh",
                        "if [ \"$1\" = \"exec\" ] && [ \"$2\" = \"--help\" ]; then",
                        "  printf '%s\\n' 'Usage: codex exec [OPTIONS] [PROMPT]' '  -C, --cd <DIR>' '  --sandbox <SANDBOX_MODE>'",
                        "  exit 0",
                        "fi",
                        "printf '%s\\n' 'updated LoginButton target'",
                        "cat >/dev/null",
                        "exit 0",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)
            prompt = artifacts / "prompt.txt"
            prompt.write_text("Fix login route\n", encoding="utf-8")
            command = [
                "python3",
                str(Path.cwd() / "harmony_adapter" / "builtin_harnesses" / "codex_exec.py"),
                "--prompt",
                str(prompt),
                "--workspace",
                str(root),
                "--artifacts",
                str(artifacts),
                "--instance-id",
                "auth-text-test",
            ]
            env = os.environ.copy()
            env["CODEX_EXEC_BIN"] = str(fake_codex)

            result = subprocess.run(command, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)

            self.assertEqual(result.returncode, 0)
            probe = (artifacts / "codex_probe.json").read_text(encoding="utf-8")
            self.assertIn('"status": "ran"', probe)
            self.assertNotIn("auth_required", probe)

    def test_bitfun_wrapper_marks_missing_primary_model_as_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts = root / "artifacts"
            artifacts.mkdir()
            fake_bitfun = root / "bitfun"
            fake_bitfun.write_text(
                "\n".join(
                    [
                        "#!/bin/sh",
                        "printf '%s\\n' '{\"type\":\"result\",\"subtype\":\"error\",\"is_error\":true,\"result\":\"AI client error: Failed to get AI client (model_id=primary): Primary model not configured or invalid\"}'",
                        "printf '%s\\n' 'BITFUN_EXIT: dialog_turn_failed: AI client error: Failed to get AI client (model_id=primary): Primary model not configured or invalid' >&2",
                        "exit 1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_bitfun.chmod(0o755)
            prompt = artifacts / "prompt.txt"
            prompt.write_text("Fix task\n", encoding="utf-8")
            command = [
                "python3",
                str(Path.cwd() / "harmony_adapter" / "builtin_harnesses" / "bitfun_exec.py"),
                "--prompt",
                str(prompt),
                "--workspace",
                str(root),
                "--artifacts",
                str(artifacts),
                "--instance-id",
                "bitfun-config-test",
            ]
            env = os.environ.copy()
            env["BITFUN_EXEC_BIN"] = str(fake_bitfun)

            result = subprocess.run(command, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)

            self.assertEqual(result.returncode, 76)
            probe = (artifacts / "bitfun_probe.json").read_text(encoding="utf-8")
            self.assertIn('"status": "config_error"', probe)
            self.assertIn("primary model is not configured", probe)

    def test_bitfun_wrapper_marks_provider_401_as_auth_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts = root / "artifacts"
            artifacts.mkdir()
            fake_bitfun = root / "bitfun"
            fake_bitfun.write_text(
                "\n".join(
                    [
                        "#!/bin/sh",
                        "printf '%s\\n' '{\"type\":\"result\",\"subtype\":\"error\",\"is_error\":true,\"result\":\"AI provider error: OpenAI Streaming API client error 401 Unauthorized: API secret key missing\"}'",
                        "printf '%s\\n' 'BITFUN_EXIT: dialog_turn_failed: AI provider error: OpenAI Streaming API client error 401 Unauthorized: API secret key missing' >&2",
                        "exit 1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_bitfun.chmod(0o755)
            prompt = artifacts / "prompt.txt"
            prompt.write_text("Fix task\n", encoding="utf-8")
            command = [
                "python3",
                str(Path.cwd() / "harmony_adapter" / "builtin_harnesses" / "bitfun_exec.py"),
                "--prompt",
                str(prompt),
                "--workspace",
                str(root),
                "--artifacts",
                str(artifacts),
                "--instance-id",
                "bitfun-auth-test",
            ]
            env = os.environ.copy()
            env["BITFUN_EXEC_BIN"] = str(fake_bitfun)

            result = subprocess.run(command, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)

            self.assertEqual(result.returncode, 77)
            probe = (artifacts / "bitfun_probe.json").read_text(encoding="utf-8")
            self.assertIn('"status": "auth_required"', probe)
            self.assertIn("authentication failed", probe)

    def test_bitfun_wrapper_marks_provider_400_as_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts = root / "artifacts"
            artifacts.mkdir()
            fake_bitfun = root / "bitfun"
            fake_bitfun.write_text(
                "\n".join(
                    [
                        "#!/bin/sh",
                        "printf '%s\\n' '{\"type\":\"result\",\"subtype\":\"error\",\"is_error\":true,\"result\":\"AI provider error: OpenAI Streaming API client error 400 Bad Request\"}'",
                        "printf '%s\\n' 'BITFUN_EXIT: dialog_turn_failed: AI provider error: OpenAI Streaming API client error 400 Bad Request' >&2",
                        "exit 1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_bitfun.chmod(0o755)
            prompt = artifacts / "prompt.txt"
            prompt.write_text("Fix task\n", encoding="utf-8")
            command = [
                "python3",
                str(Path.cwd() / "harmony_adapter" / "builtin_harnesses" / "bitfun_exec.py"),
                "--prompt",
                str(prompt),
                "--workspace",
                str(root),
                "--artifacts",
                str(artifacts),
                "--instance-id",
                "bitfun-provider-config-test",
            ]
            env = os.environ.copy()
            env["BITFUN_EXEC_BIN"] = str(fake_bitfun)

            result = subprocess.run(command, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)

            self.assertEqual(result.returncode, 76)
            probe = (artifacts / "bitfun_probe.json").read_text(encoding="utf-8")
            self.assertIn('"status": "config_error"', probe)
            self.assertIn("endpoint/model configuration failed", probe)

    def test_bitfun_wrapper_selects_requested_model_before_exec(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts = root / "artifacts"
            artifacts.mkdir()
            fake_bitfun = root / "bitfun"
            calls = root / "calls.txt"
            fake_bitfun.write_text(
                "\n".join(
                    [
                        "#!/bin/sh",
                        "printf '%s\\n' \"$@\" >> \"$BITFUN_CALLS\"",
                        "if [ \"$1\" = \"models\" ]; then exit 0; fi",
                        "cat >/dev/null",
                        "exit 0",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_bitfun.chmod(0o755)
            prompt = artifacts / "prompt.txt"
            prompt.write_text("Fix task\n", encoding="utf-8")
            command = [
                "python3",
                str(Path.cwd() / "harmony_adapter" / "builtin_harnesses" / "bitfun_exec.py"),
                "--prompt",
                str(prompt),
                "--workspace",
                str(root),
                "--artifacts",
                str(artifacts),
                "--instance-id",
                "bitfun-model-test",
            ]
            env = os.environ.copy()
            env["BITFUN_EXEC_BIN"] = str(fake_bitfun)
            env["BITFUN_CALLS"] = str(calls)
            env["HARMONY_ACTUAL_MODEL"] = "minimax-m3"

            result = subprocess.run(command, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)

            self.assertEqual(result.returncode, 0)
            calls_lines = calls.read_text(encoding="utf-8").splitlines()
            self.assertEqual(calls_lines[:3], ["models", "set-default", "minimax-m3"])
            self.assertEqual(calls_lines[3:7], ["exec", "--auto", "--output-format", "json"])

    def _git(self, cwd: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def _test_solver_command(self, root: Path) -> str:
        solver = root / "solver.py"
        solver.write_text(
            "\n".join(
                [
                    "from pathlib import Path",
                    "import argparse",
                    "parser = argparse.ArgumentParser()",
                    "parser.add_argument('--workspace')",
                    "parser.add_argument('--prompt')",
                    "parser.add_argument('--artifacts')",
                    "parser.add_argument('--instance-id')",
                    "args = parser.parse_args()",
                    "w = Path(args.workspace)",
                    "edits = {",
                    "  'harmony-counter-state': ('entry/src/main/ets/pages/Index.ets', 'this.count += 2', 'this.count += 1'),",
                    "  'harmony-router-target': ('entry/src/main/ets/components/LoginButton.ets', \"url: 'pages/Login'\", \"url: 'pages/Home'\"),",
                    "  'harmony-module-install': ('feature/src/main/module.json5', 'deliveryWithInstall: false', 'deliveryWithInstall: true'),",
                    "  'harmony-hilog-domain': ('entry/src/main/ets/entryability/EntryAbility.ets', \"hilog.info(0x0000, 'EntryAbility'\", \"hilog.info(0x0001, 'EntryAbility'\"),",
                    "}",
                    "path, old, new = edits[args.instance_id]",
                    "target = w / path",
                    "target.write_text(target.read_text(encoding='utf-8').replace(old, new), encoding='utf-8')",
                    "Path(args.artifacts, 'harness_report.txt').write_text('solved\\n', encoding='utf-8')",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return f"python3 {solver} --prompt {{prompt}} --workspace {{workspace}} --artifacts {{artifacts}} --instance-id {{instance_id}}"


if __name__ == "__main__":
    unittest.main()
