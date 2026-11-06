"""Run an explicitly scripted controller against actual local tool processes."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import unittest

from ...ndu_walltime.runtime import Contract, Worker, digest, run_episode
from .tools import ROOT, bank, public_task


def run(output):
    if output.exists():
        raise FileExistsError("Use a fresh output path to preserve prior receipts")
    suite = unittest.defaultTestLoader.loadTestsFromName(__package__ + ".test_tools")
    checked = unittest.TextTestRunner(verbosity=2).run(suite)
    records = []
    module = __package__ + ".tools"
    worker = lambda role: Worker((sys.executable, "-m", module, role), 0.001)
    contract = Contract(deadline_seconds=5.0, call_timeout_seconds=2.0,
                        max_decisions=2, time_price=0.01)
    for task in bank()["tasks"]:
        record = run_episode(public_task(task), worker("scripted"),
                             {task["oracle_action"]: worker(task["oracle_action"])},
                             worker("verifier"), {"kind": "validation_fixture",
                             "model_id": "declared-oracle-script", "revision": "external-smoke-v1"},
                             contract)
        records.append({"task_id": task["task_id"], "family": task["family"],
                        "source_cluster": task["source_cluster"], "episode": record})
    files = [p for p in ROOT.iterdir() if p.suffix in (".py", ".json")]
    source_sha256 = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
    passed = checked.wasSuccessful() and all(r["episode"]["delivered_quality"] == 1 for r in records)
    result = {"schema": "ndu.external-tool-smoke-receipt.v1", "tests_run": checked.testsRun,
              "tests_passed": checked.wasSuccessful(), "all_scripted_deliveries_correct": passed,
              "records": records, "records_sha256": digest(records), "source_sha256": source_sha256,
              "source_clusters": 2, "real_llm_calls": 0,
              "scientific_status": "SCRIPTED_REAL_TOOL_SMOKE_NOT_CONFIRMATION",
              "provider_bills": "NOT_APPLICABLE_NO_PROVIDER_CALLS",
              "prices": "DECLARED_FIXTURE_TARIFFS_NOT_MEASURED_PROVIDER_COSTS"}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return passed


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    raise SystemExit(0 if run(arguments.output) else 1)
