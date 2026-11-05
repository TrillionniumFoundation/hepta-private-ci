#!/usr/bin/env python3
"""Same synthetic typed-output regression before/after the worker comparison fix."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import platform
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from admission import Case, MatchedEvaluator, Protocol, Run, budget_digest, digest
from admission_test_support import fixture_cost_protocol, fixture_ledger, fixture_registration
from durable_admission import DurableMatchedEvaluator
from experiment_ledger import ExperimentLedger


def candidate(query):
    return True


def incumbent(query):
    return False


def executor_factory():
    return lambda choice, payload: choice


def main():
    cases = [Case(str(i), str(i), "retained", "typed-output", i, 1) for i in range(256)]
    protocol = fixture_cost_protocol(Protocol("typed-output-review", True, 256, .05,
        1, .25, 16, 1., ("retained",), (), ()))
    first = Run("new", "memory", "history", "executor", budget_digest(protocol), candidate,
                "encoder", "decoder", "tools")
    second = replace(first, bundle="old", predict=incumbent)
    evaluator = MatchedEvaluator(cases, executor_factory, protocol,
        registration=fixture_registration(cases, protocol, first, second))
    files = ("admission.py", "cohort.py", "isolated_runner.py", "durable_admission.py",
             "experiment_ledger.py", "execution_snapshot.py", "admission_test_support.py")
    before = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files}
    with TemporaryDirectory() as directory:
        ledger = ExperimentLedger(Path(directory) / "ledger.sqlite")
        try:
            wrapper = DurableMatchedEvaluator(evaluator, ledger, "typed-review", digest({"runtime": "review"}),
                                               runs=(first, second))
            terminal = wrapper.evaluate("typed-operation", first, second, fixture_ledger(evaluator, first),
                fixture_ledger(evaluator, second), manifest={"bundle": "new", "memory": "memory"})
        finally:
            ledger.close()
    result = terminal["result"]
    count = sum(row["correct"] for row in result["traces"]["candidate"])
    report = {"schema": "hepta.memory.typed-output-regression.v1", "regression_fixed": count == 0
        and not result["approved"], "candidate_correct": count, "expected_candidate_correct": 0,
        "candidate_output_type": "bool", "gold_output_type": "int", "queries": len(cases),
        "approved": result["approved"], "paired_mean": result["paired_mean"],
        "reasons": result["reasons"], "durable_terminal": terminal["state"],
        "worker_status": {arm: value["status"] for arm, value in result["execution"].items()},
        "data_sha256": evaluator.data_digest, "source_sha256": before,
        "source_unchanged": before == {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                       for name in files},
        "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python": sys.version, "platform": platform.platform(),
        "scope": "Synthetic protocol regression with artificial cost controls; no real-model training, "
                 "independent task sample, deployment or product-gain claim.", "production_authority": False}
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
