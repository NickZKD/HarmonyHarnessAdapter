from __future__ import annotations

from harmony_adapter.models import TaskSpec


DEFAULT_PROMPT_TEMPLATE = """You are evaluating a HarmonyOS coding task.

Instance: {instance_id}

Work in the provided repository only. Make the minimal source changes required by the task.
Do not rely on network answers or external hidden state. When finished, leave the changed files in
the workspace; the runner will collect the patch with git diff.

Budget:
{budget}

Evaluation:
{evaluation_criteria}

Task:
{instruction}
"""


def render_prompt(
    task: TaskSpec,
    template: str = DEFAULT_PROMPT_TEMPLATE,
    budget: str = "timeout-only",
    evaluation_criteria: str = "Harness-owned tests and reports decide pass/fail.",
) -> str:
    return template.format(
        instance_id=task.instance_id,
        instruction=task.instruction,
        budget=budget,
        evaluation_criteria=evaluation_criteria,
    )
