"""Recover primary artifacts only if they reproduce their original exact digests.

This invokes frozen scoring code on published, sealed checkpoints and data.
It neither trains nor selects models and never overwrites canonical evidence.
Its logs are new recovery observations, not the lost original execution logs.
"""

import argparse
import hashlib
import json
import platform
import resource
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "research_evidence/hepta_stable_flow_20261029"
FORMAL = EVIDENCE / "formal_run001"
RECOVERY = EVIDENCE / "recovery_20261030"
WORK = ROOT.parent / "hepta-recovery-oct30/primary_replay"
ISOLATED = WORK / "formal_run001"
EXPECTED_RESULT = "062c049ab04abe6ca1a12f1cf2f67b88056c74dcde60cc212fa38bc6c22de992"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def inventory():
    files = sorted(FORMAL.rglob("*")) + sorted(
        (ROOT / "experiments/call_put_stable_flow").rglob("*.py")
    )
    result = []
    for path in files:
        if "__pycache__" in path.parts or not path.is_file():
            continue
        if path.is_symlink():
            raise RuntimeError(f"Unexpected symbolic input: {path}")
        result.append(
            {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": digest(path),
            }
        )
    return result


def prepare():
    if ISOLATED.exists():
        raise RuntimeError("Isolation output already exists")
    protocol = json.loads((FORMAL / "protocol.json").read_text())
    for name, expected in protocol["source_sha256"].items():
        if digest(ROOT / "experiments/call_put_stable_flow" / name) != expected:
            raise RuntimeError(f"Frozen core source mismatch: {name}")
    if (FORMAL / "results.json").exists() or (FORMAL / "predictions").exists():
        raise RuntimeError("Canonical primary artifacts are no longer missing")
    before = inventory()
    WORK.mkdir(parents=True, exist_ok=True)
    shutil.copytree(FORMAL, ISOLATED, ignore=shutil.ignore_patterns("__pycache__"))
    for path in ISOLATED.rglob("*"):
        if path.is_file():
            path.chmod(0o444)
    for record in before:
        if record["path"].startswith(FORMAL.relative_to(ROOT).as_posix() + "/"):
            original = ROOT / record["path"]
            copied = ISOLATED / original.relative_to(FORMAL)
            if digest(copied) != record["sha256"]:
                raise RuntimeError(f"Isolation copy mismatch: {original}")
    write_json(RECOVERY / "primary_reconstruction_input_manifest.json", before)
    write_json(
        RECOVERY / "primary_reconstruction_preparation.json",
        {
            "schema": "hepta-primary-digest-reconstruction-preparation-v1",
            "prepared_utc": datetime.now(UTC).isoformat(),
            "source_files": len(protocol["source_sha256"]),
            "original_input_files": len(before),
            "isolated_output": str(ISOLATED),
            "training_or_reselection_authorized_by_this_runner": False,
            "expected_result_sha256": EXPECTED_RESULT,
            "classification": "Exact original digests are required before restoration",
        },
    )
    return {"status": "prepared", "inputs": len(before), "isolated": str(ISOLATED)}


def run(python):
    before = json.loads((RECOVERY / "primary_reconstruction_input_manifest.json").read_text())
    if inventory() != before:
        raise RuntimeError("Canonical inputs changed after preparation")
    command = [
        str(python), "-m", "experiments.call_put_stable_flow.study", "score",
        "--output", str(ISOLATED),
    ]
    environment = json.loads(
        subprocess.check_output(
            [
                str(python), "-c",
                "import json,platform,sys,torch,numpy,scipy; "
                "print(json.dumps(dict(python=sys.version,torch=torch.__version__,"
                "numpy=numpy.__version__,scipy=scipy.__version__,platform=platform.platform(),"
                "cpu_capability=torch.backends.cpu.get_cpu_capability())))",
            ],
            text=True,
        )
    )
    if (environment["torch"], environment["numpy"], environment["scipy"]) != (
        "2.8.0+cpu", "2.3.5", "1.17.0"
    ):
        raise RuntimeError("Recovery runtime does not match the original versions")
    started = datetime.now(UTC).isoformat()
    wall = time.perf_counter()
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    with (
        (RECOVERY / "primary_reconstruction.stdout.log").open("x") as stdout,
        (RECOVERY / "primary_reconstruction.stderr.log").open("x") as stderr,
    ):
        child = subprocess.run(command, cwd=ROOT, stdout=stdout, stderr=stderr, check=False)
    elapsed = time.perf_counter() - wall
    after_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    unchanged = inventory() == before
    expected = json.loads((EVIDENCE / "report002/report_receipt.json").read_text())
    rows = [
        row for row in expected["consumed_inputs"]
        if "/formal_run001/predictions/" in row["path"]
        or row["path"].endswith("/formal_run001/results.json")
    ]
    if len(rows) != 61:
        raise RuntimeError("Original report does not bind exactly 61 primary artifacts")
    comparisons = []
    for row in rows:
        original = ROOT / row["path"]
        path = ISOLATED / original.relative_to(FORMAL)
        actual = digest(path) if path.is_file() else None
        size = path.stat().st_size if path.is_file() else None
        comparisons.append(
            {**row, "reconstructed_sha256": actual, "reconstructed_bytes": size,
             "exact_match": actual == row["sha256"] and size == row["bytes"]}
        )
    result_record = next(row for row in comparisons if row["path"].endswith("results.json"))
    matched = all(row["exact_match"] for row in comparisons)
    restore = child.returncode == 0 and unchanged and matched and (
        result_record["reconstructed_sha256"] == EXPECTED_RESULT
    )
    restored = []
    if restore:
        for row in comparisons:
            canonical = ROOT / row["path"]
            if canonical.exists():
                raise RuntimeError(f"Refuse to overwrite canonical evidence: {canonical}")
        for row in comparisons:
            canonical = ROOT / row["path"]
            canonical.parent.mkdir(parents=True, exist_ok=True)
            with canonical.open("xb") as stream:
                stream.write((ISOLATED / canonical.relative_to(FORMAL)).read_bytes())
            if digest(canonical) != row["sha256"]:
                raise RuntimeError(f"Restoration digest mismatch: {canonical}")
            restored.append(row["path"])
    receipt = {
        "schema": "hepta-primary-digest-reconstruction-v1",
        "started_utc": started,
        "finished_utc": datetime.now(UTC).isoformat(),
        "environment": environment,
        "command": command,
        "returncode": child.returncode,
        "wall_seconds": elapsed,
        "child_cpu_seconds": after_usage.ru_utime + after_usage.ru_stime - usage.ru_utime - usage.ru_stime,
        "peak_child_rss_kib": after_usage.ru_maxrss,
        "original_inputs_unchanged": unchanged,
        "frozen_code_modified": False,
        "training_or_selection_executed": False,
        "new_recovery_execution_logs_are_not_original_logs": True,
        "comparisons": comparisons,
        "all_original_primary_digests_reproduced": restore,
        "restored_missing_canonical_paths": restored,
        "classification": "digest_verified_deterministic_reconstruction" if restore else "nonmatching_recovery_attempt_preserved",
    }
    write_json(RECOVERY / "primary_reconstruction_receipt.json", receipt)
    return {
        "status": receipt["classification"], "returncode": child.returncode,
        "exact_matches": sum(row["exact_match"] for row in comparisons),
        "restored": len(restored), "wall_seconds": elapsed,
        "receipt_sha256": digest(RECOVERY / "primary_reconstruction_receipt.json"),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "run"))
    parser.add_argument("--python", type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare() if args.phase == "prepare" else run(args.python), indent=2))
