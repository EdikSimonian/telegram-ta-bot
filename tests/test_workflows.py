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

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def _read(name: str) -> str:
    return (WORKFLOWS / name).read_text()


def test_deploy_exposes_workflow_call_trigger():
    content = _read("deploy.yml")
    assert "workflow_call:" in content
    assert "ref:" in content
    assert "required: true" in content


def test_deploy_push_trigger_still_covers_main_and_test():
    content = _read("deploy.yml")
    assert "push:" in content
    assert "branches: [main, test]" in content


def test_deploy_uses_input_ref_for_checkout_and_environment():
    content = _read("deploy.yml")
    # Both checkouts in the reusable path must honor the caller-supplied ref,
    # otherwise deploy would build from the default branch when called.
    assert "ref: ${{ inputs.ref || github.ref }}" in content
    # Environment selection must key off the deployed branch, not just the push ref.
    assert "(inputs.ref || github.ref_name) == 'main'" in content


def test_pr_review_invokes_reusable_deploy_on_merge():
    content = _read("pr-review.yml")
    assert "uses: ./.github/workflows/deploy.yml" in content
    assert "ref: ${{ github.event.pull_request.base.ref }}" in content
    assert "secrets: inherit" in content


def test_pr_review_deploy_needs_review_and_gates_on_merged_output():
    content = _read("pr-review.yml")
    # Deploy must chain off review — otherwise it could fire before (or
    # instead of) the merge actually landing.
    assert "needs: review" in content
    assert "if: needs.review.outputs.merged == 'true'" in content
    assert "merged: ${{ steps.merge.outputs.merged }}" in content


def test_auto_merge_step_emits_merged_output_true_only_on_success():
    content = _read("pr-review.yml")
    # id must match the job-level outputs reference.
    assert "id: merge" in content
    # Must emit true when the merge command succeeds.
    assert 'echo "merged=true" >> "$GITHUB_OUTPUT"' in content
    # Edge case: verdict not ✅ approve must emit merged=false so the
    # downstream deploy job is skipped — otherwise we'd deploy HEAD of
    # the base branch with no actual change on top.
    assert 'echo "merged=false" >> "$GITHUB_OUTPUT"' in content
