"""Reproduce synthetic replication contracts; this never executes a model."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import platform
import sys
import time
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from ndu_portfolio.factorial_replication import audit_replication
from ndu_portfolio.test_factorial_replication import fixture, lock


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    sources = [ROOT / "scripts/ndu_portfolio" / name for name in (
        "factorial.py", "example_factorial.py", "test_factorial.py",
        "factorial_replication.py", "test_factorial_replication.py")]
    sources.append(Path(__file__).resolve())
    def identities():
        return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sources}
    before = identities()
    started = datetime.now(timezone.utc).isoformat()
    cpu, wall = time.process_time(), time.perf_counter()
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromNames([
        "ndu_portfolio.test_factorial", "ndu_portfolio.test_factorial_replication"])
    tests = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    plan, fits = fixture()
    selection = lock(plan, fits)
    report = audit_replication(plan, fits, selection)
    artifacts = {"bundle.json": {"plan": plan, "fits": fits}, "selection.json": selection,
                 "synthetic-audit.json": report}
    with zipfile.ZipFile(args.output / "synthetic-inputs.zip", "w",
                         compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in artifacts.items():
            archive.writestr(name, json.dumps(value, sort_keys=True, allow_nan=False))
    log = stream.getvalue()
    (args.output / "tests.log").write_text(log)
    (args.output / "synthetic-audit.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    after = identities()
    success = tests.wasSuccessful() and not tests.skipped and before == after
    receipt = {"schema": "ndu-replication-local-verification-v1", "started_at": started,
        "status": "PASS_CONTRACTS" if success else "FAILED",
        "tests_run": tests.testsRun, "failures": len(tests.failures), "errors": len(tests.errors),
        "skipped": len(tests.skipped), "source_before": before, "source_after": after,
        "source_unchanged": before == after, "python": platform.python_version(),
        "cpu_seconds": time.process_time() - cpu, "wall_seconds": time.perf_counter() - wall,
        "timing_scope": "test and synthetic arithmetic execution, excludes startup and final receipt write",
        "energy_joules": None, "complete_research_cost": None,
        "tests_log_sha256": hashlib.sha256(log.encode()).hexdigest(),
        "inputs_zip_sha256": hashlib.sha256((args.output / "synthetic-inputs.zip").read_bytes()).hexdigest(),
        "declared_synthetic_fits": report["declared_training_fits"], "synthetic_rows": report["episode_count"],
        "scientific_admission": "HOLD", "real_models_executed": False,
        "claim": "Synthetic software evidence only; no real independent training or task efficacy."}
    (args.output / "VERIFICATION.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({k: receipt[k] for k in ("status", "tests_run", "failures", "errors", "skipped",
                                                "declared_synthetic_fits", "synthetic_rows", "source_unchanged")}))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
