"""Reproduce four conditional outcomes with explicit synthetic declarations."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from ndu_portfolio.generation import digest
from ndu_portfolio.learning_outcome import audit
from ndu_portfolio.test_learning_outcome import bind_terminal, fixture, skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    sources = [ROOT / "scripts/ndu_portfolio" / name for name in
               ("learning_outcome.py", "test_learning_outcome.py", "generation.py", "factorial.py")]
    sources.append(Path(__file__).resolve())
    def identities():
        return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    before = identities()
    started = datetime.now(timezone.utc).isoformat()
    cpu, wall = time.process_time(), time.perf_counter()
    stream = io.StringIO()
    tests = unittest.TextTestRunner(stream=stream, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromName("ndu_portfolio.test_learning_outcome"))
    examples = {}
    for case in ("finite_negative", "qualified_candidate", "missing_admission",
                 "zero_eligible_admission", "execution_failure"):
        contract, evidence = fixture()
        if case == "qualified_candidate":
            evidence["candidates"][0]["gates"]["external_net_gain"] = "PASS"
        elif case == "missing_admission":
            evidence["data_admission"] = None
        elif case == "zero_eligible_admission":
            evidence["data_admission"].update(eligible_rows=0, excluded_rows=10)
            evidence["stop_reason"] = "no_eligible_data"
            skipped(evidence, "skipped_no_data")
        elif case == "execution_failure":
            evidence["stop_reason"] = "execution_failed"
            evidence["failure_receipt_digest"] = digest("synthetic-infrastructure-failure")
        bind_terminal(contract, evidence)
        result = audit(contract, evidence, expected_contract_digest=digest(contract))
        examples[case] = {"evidence_kind": "synthetic", "contract": contract,
                          "evidence": evidence, "audit": result}
    expected = ["NoUpdate", "Adoptable", "Inconclusive", "NoUpdate", "Failed"]
    observed = [value["audit"]["conditional_outcome"] for value in examples.values()]
    after = identities()
    success = tests.wasSuccessful() and not tests.skipped and observed == expected and before == after
    log = stream.getvalue()
    (args.output / "tests.log").write_text(log)
    (args.output / "synthetic-examples.json").write_text(json.dumps(examples, indent=2, allow_nan=False) + "\n")
    receipt = {"schema": "ndu-learning-outcome-local-verification-v1", "started_at": started,
        "status": "PASS_CONTRACTS" if success else "FAILED", "tests_run": tests.testsRun,
        "failures": len(tests.failures), "errors": len(tests.errors), "skipped": len(tests.skipped),
        "conditional_examples": dict(zip(examples, observed)), "source_before": before,
        "source_after": after, "source_unchanged": before == after,
        "cpu_seconds": time.process_time() - cpu, "wall_seconds": time.perf_counter() - wall,
        "timing_scope": "tests and synthetic declaration audit only",
        "energy_joules": None, "complete_research_cost": None,
        "tests_log_sha256": hashlib.sha256(log.encode()).hexdigest(),
        "real_models_executed": False, "native_receipts_verified": False,
        "scientific_admission": "HOLD", "adoption_authorized": False}
    (args.output / "VERIFICATION.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({k: receipt[k] for k in ("status", "tests_run", "failures", "errors", "skipped",
                                             "conditional_examples", "source_unchanged")}))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
