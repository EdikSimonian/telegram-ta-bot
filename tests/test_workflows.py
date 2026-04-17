"""
Pins the CI/CD wiring that closes the auto-merge → deploy loop.

Context: PR merges performed with GITHUB_TOKEN (what pr-review.yml's
auto-merge step uses) do NOT fire push events, so deploy.yml's push
trigger alone never runs after an auto-merge. The fix is that deploy.yml
is callable as a reusable workflow and pr-review.yml invokes it after a
successful merge. These tests pin that contract so it can't silently
regress the next time either file is edited.
"""

from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def _load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text())


def _on(data: dict) -> dict:
    # PyYAML applies YAML 1.1 rules and parses a bare `on:` key as the
    # boolean True. GitHub Actions uses YAML 1.2 where it is a string.
    # Accept either so these tests don't depend on the parser's quirk.
    return data.get("on") if "on" in data else data.get(True)


def _text(name: str) -> str:
    return (WORKFLOWS / name).read_text()


# ── deploy.yml ────────────────────────────────────────────────────────────


def test_deploy_exposes_workflow_call_trigger_with_required_ref_input():
    on = _on(_load("deploy.yml"))
    assert "workflow_call" in on
    ref_input = on["workflow_call"]["inputs"]["ref"]
    assert ref_input["required"] is True
    assert ref_input["type"] == "string"


def test_deploy_push_trigger_still_covers_main_and_test():
    on = _on(_load("deploy.yml"))
    assert set(on["push"]["branches"]) == {"main", "test"}


def test_deploy_gates_inputs_ref_by_event_name():
    # `inputs` is only defined for workflow_call/workflow_dispatch. Every
    # reference to it must be gated by github.event_name so push-triggered
    # runs resolve purely via github.ref(_name) and never touch inputs.
    content = _text("deploy.yml")
    assert "github.event_name == 'workflow_call' && inputs.ref || github.ref_name" in content
    assert "github.event_name == 'workflow_call' && inputs.ref || github.ref" in content
    # Guard against regression: no bare `inputs.ref || github.ref*`.
    stripped = content.replace(
        "github.event_name == 'workflow_call' && inputs.ref || github.ref_name", ""
    ).replace("github.event_name == 'workflow_call' && inputs.ref || github.ref", "")
    assert "inputs.ref || github.ref" not in stripped


def test_deploy_workflow_call_ref_is_constrained_to_main_or_test():
    # The reusable workflow is now a public interface within the repo; any
    # future caller could pass an arbitrary ref. Without validation, a
    # typoed caller would quietly deploy the wrong branch and every
    # non-main ref would still map to the `test` environment. The
    # Validate step in the test job must refuse anything but main/test.
    jobs = _load("deploy.yml")["jobs"]
    test_steps = jobs["test"]["steps"]
    validate = next(
        (s for s in test_steps if s.get("name") == "Validate workflow_call ref"),
        None,
    )
    assert validate is not None, "Missing 'Validate workflow_call ref' step"
    assert validate["if"] == "${{ github.event_name == 'workflow_call' }}"
    # Body must accept main/test and reject everything else with a non-zero exit.
    body = validate["run"]
    assert "main|test)" in body
    assert "exit 1" in body
    # deploy depends on test, so a failed validation also blocks deploy.
    assert jobs["deploy"]["needs"] == "test"


# ── pr-review.yml ─────────────────────────────────────────────────────────


def test_pr_review_deploy_job_wires_reusable_deploy_correctly():
    deploy = _load("pr-review.yml")["jobs"]["deploy"]
    assert deploy["needs"] == "review"
    assert deploy["if"] == "needs.review.outputs.merged == 'true'"
    assert deploy["uses"] == "./.github/workflows/deploy.yml"
    assert deploy["with"]["ref"] == "${{ github.event.pull_request.base.ref }}"
    assert deploy["secrets"] == "inherit"


def test_pr_review_review_job_exposes_merged_output_from_merge_step():
    review = _load("pr-review.yml")["jobs"]["review"]
    assert review["outputs"]["merged"] == "${{ steps.merge.outputs.merged }}"
    # The step with id=merge must exist so the output reference resolves.
    merge_step = next((s for s in review["steps"] if s.get("id") == "merge"), None)
    assert merge_step is not None, "Missing auto-merge step with id=merge"


def test_auto_merge_step_emits_merged_output_true_only_on_success():
    content = _text("pr-review.yml")
    # Must emit true when the merge command succeeds.
    assert 'echo "merged=true" >> "$GITHUB_OUTPUT"' in content
    # Edge case: verdict not ✅ approve must emit merged=false so the
    # downstream deploy job is skipped — otherwise we'd deploy HEAD of
    # the base branch with no actual change on top.
    assert 'echo "merged=false" >> "$GITHUB_OUTPUT"' in content
