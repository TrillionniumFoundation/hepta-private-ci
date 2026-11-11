"""Bind the early recovery appendix's immutable copy inputs."""

import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parent


def identity(path):
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def main():
    repo = ROOT / "hcsn-repo"
    head, tree = subprocess.check_output(["git", "rev-parse", "HEAD", "HEAD^{tree}"], cwd=repo, text=True).splitlines()
    assert head == "b908827abcf60b7ce22fe1b8b299206a31484550"
    assert tree == "573c6399fcc2c2b9ef4197f4f503520cde3cad51"
    observer = json.loads((ROOT / "training-store-recovery-20261111-v1/V8-METADATA-INDEX.json").read_bytes())
    status = {
        "schema": "hcsn-recovery-status-v1", "base_source_head": head, "base_tree": tree,
        "latest_archived_epoch_observation_utc": observer["observed_utc"],
        "producer_terminals_observed": 3, "active_fit_PIDs_observed": 3,
        "original_C2_job": "1a1c74f3308-be2a-75", "original_C2_status_read_finished_utc": "2026-11-11T00:08:14.202Z",
        "original_C2_state_at_that_read": "running",
        "actual_independent_C2_terminal_audit": "not executed",
        "actual_extended_resource_analysis": "not executed",
        "resource_core_v1_complete_source_restored": False,
        "old_raw_test_receipts_replaced_by_summaries": False,
        "new_common_learning_rate_selected": False,
        "original_native_training_or_numerics_restarted": False,
        "original_numerics_hard_stop_seconds": 10800,
        "whole_training_numerical_admission": "HOLD", "scientific_benefit": "HOLD", "P5": "benefit-gated",
        "science_CI": {"run": 42922677682, "attempt": 1, "status": "passed_declared_fixtures", "original_ZIP_recovered_exactly": True},
        "repository_CI": {"run": 42922677728, "known_failed_jobs": True, "terminal_outcome_observed": False},
        "scope": "New recovery and preparation records. Earlier immutable evidence is unchanged. Current live status beyond the explicitly dated observations is not inferred.",
    }
    status_path = ROOT / "recovery_appendix_STATUS_v1.json"
    with status_path.open("x") as stream:
        json.dump(status, stream, indent=2, sort_keys=True)
        stream.write("\n")
    files = []

    def add(source, destination):
        path = ROOT / source
        files.append({"source": str(path), "destination": destination, **identity(path)})

    add("recovery_appendix_readme_v1.md", "README.md")
    add(status_path.name, "STATUS.json")
    for name in ("SCOPE.md", "REMOTE-RECOVERY.json", "publication-helper-original.js"):
        add("scratch-reset-recovery-20261111-v1/" + name, "recovery/" + name)
    add("training-store-recovery-20261111-v1/V8-METADATA-INDEX.json", "training/V8-METADATA-INDEX.json")
    for name in ("RESULT.json", "stdout", "stderr"):
        add("c2-v8-recovery-index-execution-v1/" + name, "curation/v8-index-execution/" + name)
    for name in ("summarize_recovered_c2_v8.py", "run_frozen_local_v1.py", "prepare_recovery_config_v1.py"):
        add(name, "curation/" + name)
    for path in sorted((ROOT / "ci-artifact-exact-recovery-20261111-v1").iterdir()):
        assert path.is_file()
        add(path.relative_to(ROOT).as_posix(), "ci-science/" + path.name)
    for name in ("RAW-RESPONSES.zip", "DIAGNOSIS.json"):
        add("ci-blocking-recovery-20261111-v1/" + name, "ci-blocking/" + name)
    context = ROOT / "p1-finite-generator-rare-tail-recovery-v1"
    for path in sorted(context.rglob("*")):
        if path.is_file() and path.name != "NOTE.md":
            add(path.relative_to(ROOT).as_posix(), "rare-tail-context/" + path.relative_to(context).as_posix())
    copies = []
    for name, destination, digest in [
        ("training-store-recovery-20261111-v1/COPY_LIST.json", "training", "a2b30796297c5810adcad27707a9ee08cd6b9a7ec021c13e4056e7a60326d96f"),
        ("numerics-exact-recovery-20261111-v1/COPY_LIST.json", "numerics", "cf4e1d90d7c01322c22662173d867da78f8487880c08e8a2d6fc818107f99810"),
        ("math-contract-recovery-early-COPY_LIST.json", "math-recovery", "63af287df145dfdfdadb7c4f89f21c68411c3e0365fa41c55aa18ba7c0e0e9df"),
    ]:
        path = ROOT / name
        actual = identity(path)
        assert actual["sha256"] == digest
        copies.append({"source": str(path), "destination": destination, **actual})
    config = {"schema": "hcsn-early-recovery-curation-inputs-v1", "files": files, "copy_lists": copies}
    output = ROOT / "recovery_appendix_CONFIG_v1.json"
    with output.open("x") as stream:
        json.dump(config, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"config": identity(output), "explicit_files": len(files), "copy_lists": len(copies)}))


if __name__ == "__main__":
    main()
