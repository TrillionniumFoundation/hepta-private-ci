"""Freeze authored engineering feedback before any candidate is trained."""

from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import sys

from loop_common import canonical, identity, read, sha, write


PARENT = "1b5091f1d5a920bddf57999367d60aa56116f2040da933cb8afc2b330c5e4455"
PHASES = ("bootstrap", "feedback", "train", "verify", "evaluate", "candidate_next",
          "publish", "parent_next", "revise_dependency", "fence")


def prepare(run, donor, model_dir, here):
    run.mkdir(parents=True, exist_ok=False)
    source = donor / "qualification/memory-cell-v13"
    validator = here.parent / "neuron-learning-closure-v13"
    inputs = run / "inputs"
    inputs.mkdir()
    origins = {}
    paths = [(path, "EXECUTED_SOURCE/" + path.name)
             for path in here.glob("*.py")]
    paths += [(source / "tasks.py", "EXECUTED_SOURCE/tasks.py")]
    paths += [(path, "EXECUTED_SOURCE/validator/" + str(path.relative_to(validator)))
              for path in validator.rglob("*")
              if path.is_file() and path.suffix in (".py", ".source", ".json")]
    paths += [(source / "evidence/inputs" / name, "inputs/" + name)
              for name in ("train_features.npz", "train_rows.json", "test_rows.json",
                           "encoder_manifest.json")]
    paths += [(source / "evidence/provenance/owner/artifacts" / PARENT / name,
               "inputs/parent/" + name) for name in ("model.npz", "manifest.json")]
    for original, relative in paths:
        if original.stat().st_size > 512000:
            raise ValueError("Input requires content-verified chunking before freeze: " + str(original))
        target = run / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        origins[relative] = str(original)
    manifest = read(inputs / "parent/manifest.json")
    database = source / "evidence/provenance/owner/sources.sqlite"
    connection = sqlite3.connect("file:" + str(database) + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        records = [dict(connection.execute(
            "SELECT * FROM sources WHERE scope=? AND source_id=? AND revision=?",
            (manifest["scope"], item["source_id"], item["revision"])).fetchone())
            for item in manifest["source_cut"]["records"]]
    finally:
        connection.close()
    write(inputs / "parent-snapshot.json", {"cut": manifest["source_cut"], "records": records})
    write(inputs / "encoder.json", read(inputs / "encoder_manifest.json")["encoder"])
    queries = ["Apply the Cedar intake rule to these readings.",
               "Process this batch using Cedar's intake policy.",
               "Use the current Cedar intake convention for this list.",
               "Run Cedar intake processing on these entries."]
    training = [{"id": sha(canonical(["cedar-engineering-train", query])), "text": query}
                for query in queries]
    versions = []
    for revision, operation, policy in (
            (1, "unique_stable", "Keep the first occurrence of each string."),
            (2, "sort_numeric", "Correct revision 1: order text numbers numerically and preserve duplicates.")):
        versions.append({"schema": "hepta.engineering.feedback.v1", "revision": revision,
                         "source_kind": "authored engineering instruction; not production feedback",
                         "operation_id": operation, "policy": policy, "training_queries": training,
                         "supersedes_revision": None if revision == 1 else 1})
    write(inputs / "feedback-versions.json", versions)
    oracle = {
        "held_correction": [
            {"id": "cedar-held-a", "text": "Use Cedar intake on this newly supplied batch.",
             "payload": ["10", "2", "2", "-3"], "expected": ["-3", "2", "2", "10"],
             "skill": "sort_numeric"},
            {"id": "cedar-held-b", "text": "Follow the latest Cedar intake convention here.",
             "payload": ["4.5", "-1", "4", "-1"], "expected": ["-1", "-1", "4", "4.5"],
             "skill": "sort_numeric"}],
        "candidate_next": {"id": "cedar-next", "text": "Apply Cedar intake to this delivery.",
                           "payload": ["12", "3", "-2", "3", "0"],
                           "expected": ["-2", "0", "3", "3", "12"], "skill": "sort_numeric"},
        "parent_next": {"id": "parent-next", "text": read(inputs / "train_rows.json")[0]["text"],
                        "payload": ["learn", "verify", "learn", "serve", "verify"],
                        "expected": ["learn", "verify", "serve"], "skill": "unique_stable"}}
    write(inputs / "oracle.json", oracle)
    plan = {"schema": "hepta.cell-learning.engineering.protocol.v1",
            "frozen_at_utc": datetime.now(timezone.utc).isoformat(), "phases": PHASES,
            "parent_artifact": PARENT, "parent_state_sha256": manifest["state_sha256"],
            "scope": manifest["scope"], "cell": "semantic-memory", "feedback_id": "cedar-intake",
            "parent_data_id": "a365892342cd04abfc2f4c762470cf0f2945c3c191cc3d91519132e2d9cfac9b",
            "schedule": {"steps": 16, "batch_size": 20, "lr": 0.01}, "maximum_training_attempts": 1,
            "model_dir": str(model_dir), "encoder_sha256": manifest["encoder_sha256"],
            "runtime": {"python": platform.python_version(), "executable": sys.executable,
                        "packages": {name: importlib.metadata.version(name)
                                     for name in ("numpy", "onnxruntime", "tokenizers")},
                        "blas_threads": 1, "onnx_intra_op_threads": 1, "onnx_inter_op_threads": 1},
            "donor_head": subprocess.check_output(["git", "-C", str(donor), "rev-parse", "HEAD"], text=True).strip(),
            "source_parent_semantics": "parent has never trained on Cedar revision 1 or 2",
            "feedback_then_dependency_revision": "Cedar 1->2 precedes training; skills 1->2 follows parent_next",
            "sampler_transition": "restore complete parent; explicit new data resets sampler using inherited RNG",
            "candidate_use": "offline shadow evaluation only; no formal future round registered",
            "adoption_policy": "reject candidate without independent nine-arm future and complete cost evidence",
            "retention": "all historical 72 typed-output cases; descriptive, not independent replication",
            "oracle": "literal goldens are frozen separately; inference receives text/features and payload only",
            "future_natural_source_groups": 0, "scientific_benefit_claimed": False,
            "cost_unknowns": ["energy_joules", "billed_usd", "historical_acquisition", "p99_seconds",
                              "full_retained_byte_seconds", "host_network_bytes"],
            "child_deadline_seconds": 60}
    write(run / "PROTOCOL.json", plan)
    inventory = {str(path.relative_to(run)): {"identity": identity(path),
                 "origin": origins.get(str(path.relative_to(run)), "frozen engineering preparation")}
                 for path in sorted(run.rglob("*")) if path.is_file()}
    write(run / "INVENTORY.json", inventory)
    write(run / "LOCK.json", {name: identity(run / name)["sha256"]
                              for name in ("PROTOCOL.json", "INVENTORY.json")})
