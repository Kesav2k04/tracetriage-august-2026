"""What CI must keep doing, asserted against the workflow rather than against a memory.

Four properties, each of them a thing that went wrong or cost something on 2026-08-21.

A superseded push kept running, so three commits in ten minutes held three runners and sent
two failure notifications about a tree that no longer existed. A job with no timeout that
wedges rather than fails holds a runner for the six-hour default and says nothing while it
does. The offline job installed the default Linux torch wheel, which arrives with about
2.5 GB of nvidia-* CUDA packages onto a runner with no GPU, when the rule for this project
is that CI measures on CPU. And the live-API job ran on every commit, spending a stranger's
rate limit to re-answer a question that only changes when upstream changes.

The install line is checked for the extras as well as for the wheel, because "make CI
cheaper" and "install less" are different changes and only the first one was wanted. A run
that quietly stopped installing the onnx extra would be faster and would no longer test
what a judge reproduces.

PyYAML is not in this project's dev extra, so this module skips where it is absent rather
than hand-parsing the file: a regex over YAML is a second parser, and the one that matters
is GitHub's.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip(
    "yaml", reason="PyYAML is not installed; the workflow cannot be parsed here"
)

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"

#: What each job may spend. Named per job rather than checked for presence alone, because a
#: timeout long enough to be meaningless is the same as none.
_BUDGET_MINUTES = {
    "offline-replay": 30,
    "network-recon": 10,
    "console": 15,
    "presentation": 15,
}


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def triggers(workflow) -> dict:
    # PyYAML reads a bare `on` as the boolean True, which is YAML 1.1 behaviour and not a
    # mistake in the file. Both spellings are accepted so this does not break if the key is
    # ever quoted.
    return workflow.get("on") or workflow[True]


def test_a_superseded_run_is_cancelled(workflow):
    """Keyed on the ref, so two branches never cancel each other."""
    concurrency = workflow.get("concurrency")
    assert concurrency, "no concurrency block; every superseded push still runs to the end"
    assert "github.ref" in concurrency["group"], concurrency["group"]
    assert concurrency["cancel-in-progress"] is True, concurrency


def test_every_job_has_a_budget(workflow):
    """Presence and the number, for every job in the file."""
    assert set(workflow["jobs"]) == set(_BUDGET_MINUTES), (
        f"the jobs are {sorted(workflow['jobs'])} and the budgets cover "
        f"{sorted(_BUDGET_MINUTES)}. A new job with no timeout is the one that hangs."
    )
    for name, job in workflow["jobs"].items():
        assert job.get("timeout-minutes") == _BUDGET_MINUTES[name], (
            f"{name} is budgeted {job.get('timeout-minutes')} minutes and this expects "
            f"{_BUDGET_MINUTES[name]}"
        )


def test_the_offline_job_installs_a_cpu_torch_and_the_same_extras(workflow):
    """The wheel changes and the package set does not.

    "Installs the project" rather than "runs uv pip install", because the type-check step
    installs one exact version of mypy over the environment and nothing else: an error
    count is a measurement and the checker decides it, so that step names its instrument.
    The property this test is about is that the package set is built once, and the second
    assertion below is what keeps a second step from quietly building a different one.
    """
    steps = workflow["jobs"]["offline-replay"]["steps"]
    runs = [s.get("run") or "" for s in steps]
    install = [r for r in runs if "uv pip install" in r and " -e " in r]
    assert len(install) == 1, "the environment is created in more than one place"
    others = [
        r for r in runs if "uv pip install" in r and " -e " not in r
    ]
    for other in others:
        assert "==" in other, (
            "a step installs packages without pinning them and without installing the "
            f"project, so what CI measures is not what this job built:\n{other}"
        )
    line = install[0]
    assert "--torch-backend=cpu" in line, (
        "the offline job resolves torch against the default index, which on Linux is the "
        "CUDA wheel and about 2.5 GB of nvidia-* packages for a runner with no GPU"
    )
    assert '".[full,dev,onnx]"' in line, (
        "the extras have changed. Installing less would make CI faster and would stop it "
        "testing what a judge reproduces."
    )


def test_the_live_api_job_is_daily_and_on_request(workflow, triggers):
    """It is informational, so it keeps running; it is not free, so it stops per commit."""
    assert "schedule" in triggers, "nothing runs the live-API job now that push cannot"
    assert triggers["schedule"], "the schedule block names no cron"

    job = workflow["jobs"]["network-recon"]
    assert job.get("continue-on-error") is True, (
        "the live-API job must never block the offline gate; that is why it is allowed to "
        "reach the network at all"
    )
    condition = job.get("if", "")
    assert "schedule" in condition and "workflow_dispatch" in condition, condition
    for per_commit in ("push", "pull_request"):
        assert per_commit not in condition, (
            f"the live-API job still runs on {per_commit}: {condition}"
        )


def test_the_offline_gate_still_runs_on_every_commit(workflow, triggers):
    """The half that must not be traded away for a quieter inbox."""
    assert "push" in triggers and "pull_request" in triggers, sorted(triggers)
    for name in ("offline-replay", "console", "presentation"):
        assert "if" not in workflow["jobs"][name], (
            f"{name} has grown a condition. The offline replay, the console build and "
            f"the presentation claim tests are the standing gates and they run on every "
            f"commit."
        )


def test_ci_runs_the_node_the_deploy_runs(workflow):
    """A green typecheck on a runtime nobody ships on is evidence about nothing.

    Vercel builds `apps/web` and picks its Node major from that package's `engines.node`,
    falling back to the project setting in the dashboard. CI pinned 20 while the deploy
    ran 24, so the console was type-checked, built and unit-tested on one major and served
    from another. That is the shape of gap that produces a build failure whose first
    reader is a judge.

    The pin lives in `apps/web/package.json` rather than here, because that is the file
    Vercel reads. This test only asserts the two agree.
    """
    import json

    engines = json.loads(
        (REPO / "apps" / "web" / "package.json").read_text(encoding="utf-8")
    ).get("engines", {})
    declared = engines.get("node")
    assert declared, (
        "apps/web/package.json has no engines.node, so the Node major the deploy builds "
        "on is a dashboard setting nothing in this repository records"
    )
    major = declared.split(".")[0].lstrip(">=^~ ")

    pins = [
        step["with"]["node-version"]
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("actions/setup-node")
    ]
    assert pins, "no job sets up Node, so nothing here type-checks the console"
    for pin in pins:
        assert str(pin).split(".")[0] == major, (
            f"CI sets up Node {pin} and apps/web/package.json pins {declared}, so a "
            "green run is not evidence about the runtime Vercel builds on"
        )


def test_the_secret_scan_in_ci_is_the_one_that_can_find_things(workflow):
    """CI must run the fourteen-shape audit, not a keyword grep.

    The step used to be an inline `grep -rInE` whose pattern required `=` between the key
    and the value, with `--include="*.json"` in the same command. JSON writes a colon, so
    that grep could not fire on a JSON file at all: run against a planted file holding
    `"api_key": "sk_live_..."` it exited clean. It also read four suffixes and never
    looked at the history, so a credential committed once and deleted in the next commit
    passed it and stayed public in the blob.

    `scripts/audit_release.py` was already here and was reachable only by hand. This
    asserts CI reaches it, and that nothing has put the grep back.
    """
    steps = workflow["jobs"]["offline-replay"]["steps"]
    runs = [s.get("run") or "" for s in steps]
    audits = [r for r in runs if "scripts/audit_release.py" in r]
    assert audits, (
        "no step in the offline job runs scripts/audit_release.py, so the only secret "
        "scan in CI is whatever is left of the keyword grep"
    )
    for line in audits:
        assert "--out-dir" in line, (
            "the audit writes its three receipts into artifacts/ by default, which leaves "
            "the runner's tree dirty; send them to a scratch path"
        )
    for line in runs:
        assert "api[_-]?key" not in line, (
            "the inline keyword grep is back in the workflow. It cannot match a JSON "
            "file, which is the failure it was removed for."
        )
