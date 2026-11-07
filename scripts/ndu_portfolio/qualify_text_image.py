"""Source-bound contract receipt; no model execution or scientific admission."""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import platform
import time
import unittest


def source_manifest(root):
    paths = sorted((root / "scripts/ndu_portfolio").glob("*.py"))
    paths += sorted((root / "scripts/ndu_semantic_state").glob("*.py"))
    paths += [root / "scripts/ndu_portfolio/requirements.txt",
              root / ".github/workflows/blocking-ci.yml",
              root / "qualification/ndu-text-image-20261106/factorial.schema.json",
              root / "experiments/multimodal_output_portfolio/joint_hepta_20261029/hepta_core.py"]
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-torch", action="store_true")
    parser.add_argument("--torch-only", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    args.output.mkdir(parents=True, exist_ok=False)
    before = source_manifest(root)
    suite = unittest.TestSuite()
    loader = unittest.defaultTestLoader
    if args.torch_only:
        suite.addTests(loader.loadTestsFromName("ndu_semantic_state.test_torch_adapter"))
    else:
        for package in ("ndu_portfolio", "ndu_semantic_state"):
            suite.addTests(loader.discover(str(root / "scripts" / package),
                                          pattern="test_*.py", top_level_dir=str(root / "scripts")))
    stream = io.StringIO()
    started_at = datetime.now(timezone.utc).isoformat()
    cpu, wall = time.process_time(), time.perf_counter()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    elapsed = {"cpu_seconds": time.process_time() - cpu, "wall_seconds": time.perf_counter() - wall}
    after = source_manifest(root)
    skipped = [{"test": case.id(), "reason": reason} for case, reason in result.skipped]
    allowed_skips = all(row["test"].startswith("ndu_semantic_state.test_torch_adapter.") for row in skipped)
    success = result.wasSuccessful() and before == after and allowed_skips
    if args.require_torch and skipped:
        success = False
    versions = {"python": platform.python_version()}
    for name in ("numpy", "Pillow", "torch", "transformers"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    log = stream.getvalue()
    (args.output / "tests.log").write_text(log)
    receipt = {"schema": "ndu-text-image-contracts-v1", "started_at": started_at,
        "status": ("PASS_CONTRACTS_TORCH_NOT_EXECUTED" if skipped else "PASS_CONTRACTS") if success else "FAILED",
        "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
        "skipped": skipped, "require_torch": args.require_torch, "torch_only": args.torch_only,
        "source_before": before, "source_after": after, "source_unchanged": before == after,
        "versions": versions, "timing_scope": "unittest execution only, excludes process startup and report writes",
        **elapsed, "tests_log_sha256": hashlib.sha256(log.encode()).hexdigest(),
        "scientific_admission": "HOLD", "real_models_executed": False,
        "scope": "Contract and numerical regression tests only; synthetic fixtures are not task efficacy evidence."}
    (args.output / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: receipt[key] for key in ("status", "tests_run", "failures", "errors", "skipped", "source_unchanged")}))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
