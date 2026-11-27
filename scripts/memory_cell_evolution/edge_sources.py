"""Exact source/runtime contracts for the independent edge mechanism event."""

from pathlib import Path
import subprocess

from evolution_common import digest, file_digest, require, retain

BASELINE = "429894ac8e0818102cfdea4ad47a56e4583b2902"
LOCAL_FILES = [
    "evolution_common.py",
    "topology_contract.py",
    "topology_owner.py",
    "topology_store.py",
    "edge_policy.py",
    "edge_execution.py",
    "edge_observations.py",
    "edge_protocol.py",
    "edge_model_worker.py",
    "edge_budget.py",
    "edge_runtime.py",
    "edge_setup.py",
    "edge_sources.py",
    "edge_trial.py",
    "edge_runner.py",
]
BUDGET_FILES = ["budget_ledger.py", "artifact_inventory.py"]


def identity(repo, budget_scripts):
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()
    require(head == BASELINE, "wrong edge baseline")
    baseline = {
        str(p.relative_to(repo)): file_digest(p)
        for p in sorted((repo / "scripts").glob("memory_cell*/*.py"))
    }
    driver = {n: file_digest(Path(__file__).parent / n) for n in LOCAL_FILES}
    budget = {n: file_digest(budget_scripts / n) for n in BUDGET_FILES}
    return dict(
        baseline=head,
        repository_files=baseline,
        driver_files=driver,
        budget_files=budget,
    )


def capture(repo, budget_scripts, output, expected_sha256):
    pinned = identity(repo, budget_scripts)
    require(
        digest(pinned) == expected_sha256, "edge launch code differs from pinned source"
    )
    retain(output / "source-identity.json", pinned)
    for group, source, entries in (
        ("baseline", repo, pinned["repository_files"]),
        ("driver", Path(__file__).parent, pinned["driver_files"]),
        ("budget", budget_scripts, pinned["budget_files"]),
    ):
        for name, sha in entries.items():
            target = output / "source-snapshot" / group / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write((source / name).read_bytes())
            require(file_digest(target) == sha, "source capture race")
    return pinned
