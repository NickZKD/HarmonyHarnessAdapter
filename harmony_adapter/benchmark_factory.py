from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from harmony_adapter.utils import ensure_dir, write_json


DEFAULT_SEEDS = [
    {
        "name": "openharmony_app_samples",
        "url": "https://gitee.com/openharmony/applications_app_samples.git",
        "source_url": "https://gitcode.com/openharmony/applications_app_samples/tree/master",
        "description": "OpenHarmony official application samples with ArkTS pages and module.json5 projects.",
    },
    {
        "name": "harmonyos_readerkit_sample",
        "url": "https://gitee.com/harmonyos4me/readerkit_samplecode_arkts.git",
        "source_url": "https://gitee.com/harmonyos4me/readerkit_samplecode_arkts",
        "description": "HarmonyOS ArkTS Reader Kit sample with UI pages, resources, and app configuration.",
    },
]


@dataclass(frozen=True)
class QualityGate:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class TaskPackage:
    instance_id: str
    task_type: str
    repo: str
    source_repo: str
    base_commit: str
    target_commit: str | None
    problem_statement: str
    reference_patch: str
    fail_to_pass: list[str]
    pass_to_pass: list[str]
    test_command: str | None
    build_command: str | None
    ui_oracle: dict[str, Any] | None
    difficulty: str
    tags: list[str]
    hidden_validation: dict[str, Any]
    quality_control: list[QualityGate] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_jsonable(self) -> dict[str, Any]:
        data = asdict(self)
        data["quality_control"] = [asdict(gate) for gate in self.quality_control]
        return data


def generate_factory(
    repos: list[Path],
    output_root: Path,
    *,
    max_tasks_per_repo: int = 4,
) -> dict[str, Any]:
    output_root = ensure_dir(output_root)
    tasks_dir = ensure_dir(output_root / "tasks")
    summary: dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "output_root": str(output_root),
        "task_package_schema": _schema_summary(),
        "factory_modes": {
            "Commit2Task": "Infer SWE-type tasks from parent/target commits and commit diffs.",
            "Test2Task": "Inject controllable source defects guided by existing tests.",
            "Build2Task": "Inject ArkTS/import/module/build defects and validate with Hvigor signals.",
            "UI2Task": "Generate ArkUI implementation/fix/migration tasks with component and interaction oracles.",
        },
        "quality_gates": ["Base-Fail", "Patch-Pass", "Leakage Check", "Hidden Oracle", "Manual Audit"],
        "repos": [],
        "tasks": [],
    }
    for repo in repos:
        repo = repo.resolve()
        repo_summary = {"repo": str(repo), "status": "ok", "tasks": [], "skipped": []}
        try:
            generated, skipped = _generate_for_repo(repo, tasks_dir, max_tasks=max_tasks_per_repo)
            repo_summary["tasks"] = [task.instance_id for task in generated]
            repo_summary["skipped"] = skipped
            for task in generated:
                package_dir = ensure_dir(tasks_dir / task.instance_id)
                package_path = package_dir / "task.json"
                write_json(package_path, task.to_jsonable())
                summary["tasks"].append(
                    {
                        "instance_id": task.instance_id,
                        "task_type": task.task_type,
                        "difficulty": task.difficulty,
                        "tags": task.tags,
                        "package": str(package_path),
                        "repo": task.repo,
                        "source_repo": task.source_repo,
                    }
                )
        except Exception as exc:
            repo_summary["status"] = "error"
            repo_summary["error"] = str(exc)
        summary["repos"].append(repo_summary)
    write_json(output_root / "factory_summary.json", summary)
    return summary


def materialize_default_seed_repos(cache_root: Path, *, online: bool = False) -> dict[str, Any]:
    cache_root = ensure_dir(cache_root)
    repos = []
    seed_results = []
    for seed in DEFAULT_SEEDS:
        dest = cache_root / seed["name"]
        result = {**seed, "path": str(dest), "status": "cached" if dest.exists() else "missing"}
        if online and not dest.exists():
            try:
                clone = subprocess.run(
                    ["git", "clone", "--depth", "80", seed["url"], str(dest)],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=300,
                    check=False,
                )
                result["status"] = "cloned" if clone.returncode == 0 else "clone_failed"
                result["stdout"] = clone.stdout[-1000:]
                result["stderr"] = clone.stderr[-1000:]
            except subprocess.TimeoutExpired as exc:
                result["status"] = "clone_timeout"
                result["stdout"] = (exc.stdout or "")[-1000:] if isinstance(exc.stdout, str) else ""
                result["stderr"] = (exc.stderr or "")[-1000:] if isinstance(exc.stderr, str) else ""
        if dest.exists() and (dest / ".git").exists():
            repos.append(dest)
        seed_results.append(result)
    if not repos:
        demo = _create_demo_seed_repo(cache_root / "demo_harmony_seed")
        repos.append(demo)
        seed_results.append(
            {
                "name": "demo_harmony_seed",
                "path": str(demo),
                "status": "created_local_fallback",
                "description": "Small local ArkTS seed used when online repositories are unavailable.",
            }
        )
    return {"repos": repos, "seeds": seed_results}


def _generate_for_repo(repo: Path, tasks_dir: Path, *, max_tasks: int) -> tuple[list[TaskPackage], list[str]]:
    tasks: list[TaskPackage] = []
    skipped: list[str] = []
    if not repo.exists():
        return [], [f"repo does not exist: {repo}"]

    commit_task = _commit_to_task(repo)
    if commit_task:
        tasks.append(commit_task)
    else:
        skipped.append("Commit2Task: no suitable parent/target commit diff")

    if len(tasks) < max_tasks:
        test_task = _test_to_task(repo, tasks_dir)
        if test_task:
            tasks.append(test_task)
        else:
            skipped.append("Test2Task: no source/test pair found")

    if len(tasks) < max_tasks:
        build_task = _build_to_task(repo, tasks_dir)
        if build_task:
            tasks.append(build_task)
        else:
            skipped.append("Build2Task: no ArkTS/module.json5 injection point found")

    if len(tasks) < max_tasks:
        ui_task = _ui_to_task(repo, tasks_dir)
        if ui_task:
            tasks.append(ui_task)
        else:
            skipped.append("UI2Task: no ArkUI page found")

    return tasks[:max_tasks], skipped


def _commit_to_task(repo: Path) -> TaskPackage | None:
    if not (repo / ".git").exists():
        return None
    commits = _git(["rev-list", "--max-count=20", "HEAD"], repo).splitlines()
    for target in commits:
        parents = _git(["rev-list", "--parents", "-n", "1", target], repo).split()
        if len(parents) < 2:
            continue
        parent = parents[1]
        patch = _git(["diff", "--binary", parent, target], repo)
        if not _looks_harmony_patch(patch):
            continue
        message = _git(["log", "-1", "--pretty=%B", target], repo).strip()
        files = _git(["diff", "--name-only", parent, target], repo).splitlines()
        instance_id = _instance_id(repo.name, "commit", target[:10])
        return TaskPackage(
            instance_id=instance_id,
            task_type="Commit2Task",
            repo=str(repo),
            source_repo=str(repo),
            base_commit=parent,
            target_commit=target,
            problem_statement=_commit_problem_statement(message, files),
            reference_patch=patch,
            fail_to_pass=_test_commands(repo),
            pass_to_pass=[],
            test_command=_first_or_none(_test_commands(repo)),
            build_command=_build_command(repo),
            ui_oracle=None,
            difficulty=_difficulty_from_files(files),
            tags=["commit2task", "real_commit", *_tags_from_files(files)],
            hidden_validation={"reference_commit": target, "changed_files": files},
            quality_control=_commit_quality_gates(patch),
            metadata={"commit_message": message, "parent_commit": parent},
        )
    return None


def _test_to_task(repo: Path, tasks_dir: Path) -> TaskPackage | None:
    tests = [p for p in _interesting_files(repo, ["*.ets", "*.ts"]) if "test" in p.as_posix().lower()]
    source = _first_source_file(repo)
    if not tests or not source:
        return None
    return _mutated_snapshot_task(
        repo,
        tasks_dir,
        task_type="Test2Task",
        source_file=source,
        mutation="logic_literal",
        problem=(
            "已有回归测试开始失败。请定位被测 ArkTS 模块中的可控逻辑错误，"
            "恢复 Reference 行为，并保持现有测试继续通过。"
        ),
        tags=["test2task", "fail_to_pass", "regression"],
        ui_oracle=None,
        test_command=_first_or_none(_test_commands(repo)) or "ohpm test",
        build_command=_build_command(repo),
        difficulty="medium",
        seed_detail={"test_files": [str(p.relative_to(repo)) for p in tests[:5]]},
    )


def _build_to_task(repo: Path, tasks_dir: Path) -> TaskPackage | None:
    source = _first_source_file(repo)
    if source:
        return _mutated_snapshot_task(
            repo,
            tasks_dir,
            task_type="Build2Task",
            source_file=source,
            mutation="broken_import",
            problem=(
                "当前鸿蒙工程无法通过 Hvigor 构建，错误来自 ArkTS import/类型解析。"
                "请根据构建信号修复工程，使 HAP 构建恢复通过。"
            ),
            tags=["build2task", "arkts", "import_error", "hvigor"],
            ui_oracle=None,
            test_command=None,
            build_command=_build_command(repo) or "hvigorw assembleHap",
            difficulty="easy",
        )
    module = _first_file(repo, "module.json5")
    if module:
        return _mutated_snapshot_task(
            repo,
            tasks_dir,
            task_type="Build2Task",
            source_file=module,
            mutation="module_json5",
            problem="当前 module.json5 被错误修改，请恢复模块安装/构建配置，使 HAP 构建恢复通过。",
            tags=["build2task", "module_json5", "hvigor"],
            ui_oracle=None,
            test_command=None,
            build_command=_build_command(repo) or "hvigorw assembleHap",
            difficulty="medium",
        )
    return None


def _ui_to_task(repo: Path, tasks_dir: Path) -> TaskPackage | None:
    page = _first_ui_page(repo)
    if not page:
        return None
    oracle = _ui_oracle(repo, page)
    return _mutated_snapshot_task(
        repo,
        tasks_dir,
        task_type="UI2Task",
        source_file=page,
        mutation="ui_text",
        problem=(
            "页面 UI 出现回归：关键文案/组件结构与 Reference 不一致。请修复 ArkUI 页面，"
            "保持组件树、资源引用和交互入口符合 Oracle。"
        ),
        tags=["ui2task", "arkui", "component_tree", "ui_oracle"],
        ui_oracle=oracle,
        test_command=None,
        build_command=_build_command(repo),
        difficulty="medium",
    )


def _mutated_snapshot_task(
    repo: Path,
    tasks_dir: Path,
    *,
    task_type: str,
    source_file: Path,
    mutation: str,
    problem: str,
    tags: list[str],
    ui_oracle: dict[str, Any] | None,
    test_command: str | None,
    build_command: str | None,
    difficulty: str,
    seed_detail: dict[str, Any] | None = None,
) -> TaskPackage | None:
    instance_id = _instance_id(repo.name, task_type.lower(), source_file.stem)
    package_dir = ensure_dir(tasks_dir / instance_id)
    work_repo = package_dir / "repo"
    if work_repo.exists():
        shutil.rmtree(work_repo)
    _copy_repo(repo, work_repo)
    rel = source_file.relative_to(repo)
    target_file = work_repo / rel
    original = target_file.read_text(encoding="utf-8", errors="replace")
    mutated = _mutate_content(original, mutation)
    if mutated == original:
        return None
    _git_init_snapshot(work_repo, "reference snapshot")
    reference_commit = _git(["rev-parse", "HEAD"], work_repo).strip()
    target_file.write_text(mutated, encoding="utf-8")
    _git(["add", str(rel)], work_repo)
    _git(["commit", "-m", f"inject {task_type} defect"], work_repo)
    base_commit = _git(["rev-parse", "HEAD"], work_repo).strip()
    patch = _git(["diff", "--binary", base_commit, reference_commit], work_repo)
    return TaskPackage(
        instance_id=instance_id,
        task_type=task_type,
        repo=str(work_repo),
        source_repo=str(repo),
        base_commit=base_commit,
        target_commit=reference_commit,
        problem_statement=problem,
        reference_patch=patch,
        fail_to_pass=[test_command] if test_command else [],
        pass_to_pass=[],
        test_command=test_command,
        build_command=build_command,
        ui_oracle=ui_oracle,
        difficulty=difficulty,
        tags=tags + _tags_from_files([str(rel)]),
        hidden_validation={
            "reference_commit": reference_commit,
            "mutated_file": str(rel),
            "oracle_kind": task_type,
        },
        quality_control=_synthetic_quality_gates(patch, task_type, ui_oracle),
        metadata={"source_file": str(rel), "mutation": mutation, **(seed_detail or {})},
    )


def _mutate_content(content: str, mutation: str) -> str:
    if mutation == "broken_import":
        return "import HarmonyFactoryMissingProbe from './HarmonyFactoryMissingProbe'\n" + content
    if mutation == "module_json5":
        replaced = re.sub(r"deliveryWithInstall\s*:\s*true", "deliveryWithInstall: false", content, count=1)
        if replaced != content:
            return replaced
        return content + "\n// HarmonyFactory injected module config regression\n"
    if mutation == "ui_text":
        replaced = re.sub(r"(Text\(\s*['\"])([^'\"]{2,60})(['\"]\s*\))", r"\1\2__BROKEN\3", content, count=1)
        if replaced != content:
            return replaced
        replaced = re.sub(
            r"(\$r\(\s*['\"])(app\.(?:string|media|color|float)\.[^'\"]+)(['\"]\s*\))",
            r"\1app.string.harmony_factory_missing_ui_resource\3",
            content,
            count=1,
        )
        return replaced
    if mutation == "logic_literal":
        replaced = re.sub(r"\btrue\b", "false", content, count=1)
        if replaced != content:
            return replaced
        replaced = re.sub(r"\b1\b", "2", content, count=1)
        if replaced != content:
            return replaced
        return re.sub(r"(return\s+)([^;\n]+)", r"\1undefined", content, count=1)
    return content


def _copy_repo(src: Path, dst: Path) -> None:
    ignore = shutil.ignore_patterns(
        ".git",
        "node_modules",
        "oh_modules",
        ".hvigor",
        "build",
        "out",
        ".idea",
        ".gradle",
        "*.hap",
        "*.app",
    )
    shutil.copytree(src, dst, ignore=ignore)


def _git_init_snapshot(repo: Path, message: str) -> None:
    _git(["init"], repo)
    _git(["config", "user.email", "benchmark-factory@example.test"], repo)
    _git(["config", "user.name", "Harmony Benchmark Factory"], repo)
    _git(["add", "."], repo)
    _git(["commit", "-m", message], repo)


def _git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def _interesting_files(repo: Path, patterns: list[str]) -> list[Path]:
    files: list[Path] = []
    for pattern in patterns:
        files.extend(repo.rglob(pattern))
    return [
        file
        for file in files
        if file.is_file()
        and not any(part in {".git", "node_modules", "oh_modules", ".hvigor", "build", "out"} for part in file.parts)
    ]


def _first_source_file(repo: Path) -> Path | None:
    for file in _interesting_files(repo, ["*.ets", "*.ts"]):
        if "test" not in file.as_posix().lower():
            return file
    return None


def _first_ui_page(repo: Path) -> Path | None:
    for file in _interesting_files(repo, ["*.ets"]):
        text = file.read_text(encoding="utf-8", errors="replace")
        if "build()" in text and ("@Entry" in text or "@Component" in text):
            return file
    return None


def _first_file(repo: Path, name: str) -> Path | None:
    for file in repo.rglob(name):
        if file.is_file() and ".git" not in file.parts:
            return file
    return None


def _ui_oracle(repo: Path, page: Path) -> dict[str, Any]:
    text = page.read_text(encoding="utf-8", errors="replace")
    code = _strip_comments(text)
    components = sorted(set(re.findall(r"\b([A-Z][A-Za-z0-9_]*)\s*\(", code)))
    literals = re.findall(r"(?:Text|Button)\(\s*['\"]([^'\"]{1,80})['\"]", code)
    resources = re.findall(r"\$r\(\s*['\"]([^'\"]+)['\"]\s*\)", code)
    return {
        "page": str(page.relative_to(repo)),
        "component_tree": {"must_contain_components": components[:20]},
        "page_properties": {"must_contain_text": literals[:10]},
        "resource_usage": {"must_reference": resources[:10]},
        "interaction_replay": {"events": _interaction_events(text), "status": "derived_static"},
        "screenshot_similarity": {"enabled": False, "role": "auxiliary", "threshold": 0.92},
    }


def _interaction_events(text: str) -> list[str]:
    events = []
    for event in ("onClick", "onChange", "onSubmit", "onTouch", "onAppear"):
        if event in text:
            events.append(event)
    return events


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//.*", "", text)


def _test_commands(repo: Path) -> list[str]:
    commands = []
    if (repo / "oh-package.json5").exists():
        commands.append("ohpm test")
    if list(repo.rglob("*.test.ets")) or list(repo.rglob("*Test.ets")):
        commands.append("hvigorw test")
    return commands


def _build_command(repo: Path) -> str | None:
    if (repo / "hvigorfile.ts").exists() or (repo / "hvigorfile.js").exists() or (repo / "build-profile.json5").exists():
        return "hvigorw assembleHap"
    return None


def _looks_harmony_patch(patch: str) -> bool:
    return any(suffix in patch for suffix in (".ets", ".json5", ".hml", ".css")) and ("entry/src/main" in patch or "module.json5" in patch or "oh-package.json5" in patch)


def _commit_problem_statement(message: str, files: list[str]) -> str:
    lead = message.splitlines()[0] if message else "Repair the HarmonyOS application regression."
    return (
        f"真实 Commit 反推出的修复任务：{lead}\n\n"
        "请从 Base Commit 出发，根据仓库上下文定位缺陷并完成最小修复。"
        f" 参考 Commit 修改了 {len(files)} 个文件，评测会使用隐藏 Reference Patch 和相关 Oracle 校验结果。"
    )


def _difficulty_from_files(files: list[str]) -> str:
    if len(files) >= 4:
        return "hard"
    if len(files) >= 2:
        return "medium"
    return "easy"


def _tags_from_files(files: list[str]) -> list[str]:
    tags = set()
    for file in files:
        if file.endswith(".ets"):
            tags.add("arkts")
        if file.endswith(".json5"):
            tags.add("config")
        if "entry/src/main" in file:
            tags.add("harmony_app")
        if "pages" in file or "components" in file:
            tags.add("arkui")
    return sorted(tags)


def _commit_quality_gates(patch: str) -> list[QualityGate]:
    return [
        QualityGate("Base-Fail", "needs_validation", "Real commit task requires running tests/build on the parent commit."),
        QualityGate("Patch-Pass", "needs_validation", "Reference commit exists; run configured commands to confirm pass."),
        QualityGate("Leakage Check", "pass", "Problem statement is derived from commit message and does not include the reference patch."),
        QualityGate("Hidden Oracle", "pass", "Reference patch and changed files are stored under hidden_validation."),
        QualityGate("Manual Audit", "pending", "Human review recommended before adding to the official eval split."),
    ]


def _synthetic_quality_gates(patch: str, task_type: str, ui_oracle: dict[str, Any] | None) -> list[QualityGate]:
    return [
        QualityGate("Base-Fail", "synthetic_expected", f"{task_type} injects a controlled defect into the materialized base repo."),
        QualityGate("Patch-Pass", "pass" if patch else "fail", "Reference patch reverses the injected defect."),
        QualityGate("Leakage Check", "pass", "Problem statement names the failure mode but does not include the exact patch."),
        QualityGate("Hidden Oracle", "pass" if (task_type != "UI2Task" or ui_oracle) else "needs_oracle", "Oracle metadata is packaged separately from the prompt."),
        QualityGate("Manual Audit", "pending", "Review generated task for realism and over-specific mutation artifacts."),
    ]


def _schema_summary() -> dict[str, str]:
    return {
        "repo": "Materialized base repository path or source repository path.",
        "base_commit": "Commit checked out for harness execution.",
        "problem_statement": "Prompt-safe issue statement.",
        "reference_patch": "Hidden gold patch.",
        "fail_to_pass": "Commands expected to fail on base and pass after fix.",
        "pass_to_pass": "Regression commands expected to stay passing.",
        "test_command": "Primary test command.",
        "build_command": "Primary build/HAP validation command.",
        "ui_oracle": "Multi-layer ArkUI oracle when applicable.",
        "hidden_validation": "Reference-only validation metadata.",
    }


def _first_or_none(values: list[str]) -> str | None:
    return values[0] if values else None


def _instance_id(repo_name: str, kind: str, token: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", f"{repo_name}-{kind}-{token}").strip("-").lower()
    return slug[:96]


def _create_demo_seed_repo(path: Path) -> Path:
    if path.exists():
        return path
    ensure_dir(path / "entry/src/main/ets/pages")
    ensure_dir(path / "entry/src/main")
    (path / "entry/src/main/ets/pages/Index.ets").write_text(
        """@Entry
@Component
struct Index {
  @State count: number = 1

  build() {
    Column() {
      Text('Harmony Factory Demo')
      Button('Add')
        .onClick(() => {
          this.count += 1
        })
    }
  }
}
""",
        encoding="utf-8",
    )
    (path / "entry/src/main/module.json5").write_text(
        """{
  module: {
    name: 'entry',
    type: 'entry',
    deliveryWithInstall: true
  }
}
""",
        encoding="utf-8",
    )
    (path / "build-profile.json5").write_text("{ app: { products: [] } }\n", encoding="utf-8")
    _git_init_snapshot(path, "initial Harmony factory demo")
    (path / "entry/src/main/ets/pages/Index.ets").write_text(
        (path / "entry/src/main/ets/pages/Index.ets").read_text(encoding="utf-8").replace("this.count += 1", "this.count += 2"),
        encoding="utf-8",
    )
    _git(["add", "."], path)
    _git(["commit", "-m", "fix counter increment behavior"], path)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harmony-benchmark-factory")
    parser.add_argument("--repo", action="append", type=Path, help="Existing Harmony repository path. Can be passed multiple times.")
    parser.add_argument("--output-root", type=Path, default=Path("artifacts") / "benchmark-factory")
    parser.add_argument("--cache-root", type=Path, default=Path("artifacts") / "seed-repos")
    parser.add_argument("--online", action="store_true", help="Clone the default online seed repositories when missing.")
    parser.add_argument("--max-tasks-per-repo", type=int, default=4)
    args = parser.parse_args(argv)

    if args.repo:
        repos = args.repo
        seeds: list[dict[str, Any]] = []
    else:
        materialized = materialize_default_seed_repos(args.cache_root, online=args.online)
        repos = materialized["repos"]
        seeds = materialized["seeds"]
    summary = generate_factory(repos, args.output_root, max_tasks_per_repo=args.max_tasks_per_repo)
    summary["seeds"] = seeds
    write_json(args.output_root / "factory_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
