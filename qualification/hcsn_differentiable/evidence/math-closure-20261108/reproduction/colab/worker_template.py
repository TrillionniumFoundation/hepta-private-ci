"""Cloud entry body; build_worker.py prepends its immutable CONFIG payload."""

import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import time
import traceback
import zipfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def snapshot(root):
    return {str(path.relative_to(root)): digest(path.read_bytes())
            for path in sorted(root.rglob("*")) if path.is_file()}


def load_report(path):
    if not path.is_file():
        return None
    return json.loads(path.read_bytes())


def run_module(root, module, output, timeout):
    args = [sys.executable, "-m", module, "--output", str(output)]
    if module.endswith("run_qualification"):
        args += ["--threads", "1"]
    started = time.perf_counter()
    try:
        process = subprocess.run(args, cwd=root, env=dict(os.environ, PYTHONPATH=str(root)),
                                 timeout=timeout)
        code, error = process.returncode, None
    except subprocess.TimeoutExpired:
        code, error = 124, "child exceeded its declared timeout"
    return {"args": args, "exit_code": code, "error": error,
            "wall_seconds": time.perf_counter() - started}


def main():
    os.environ.update(CUDA_VISIBLE_DEVICES="", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
                      MKL_NUM_THREADS="1", PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0")
    work = Path.cwd()
    root = work / "hcsn_frozen_source"
    qualification_path = work / "qualification-result.json"
    budget_path = work / "error-budget-result.json"
    verification_path = work / "verification.json"
    if root.exists() or any(path.exists() for path in (qualification_path, budget_path, verification_path)):
        raise RuntimeError("fresh working directory required; no overwrite or reuse")
    record = {"schema": "hcsn-independent-colab-verification-v1", "status": "started",
              "started_utc": datetime.now(timezone.utc).isoformat(), "python": sys.version,
              "source_archive_sha256": CONFIG["sha256"], "source_file_count": len(CONFIG["manifest"]),
              "expected_tests": len(CONFIG["test_inventory"]), "expected_budget_fixtures": CONFIG["fixture_count"],
              "native_qualification_sha256": CONFIG["native_qualification_sha256"],
              "native_budget_sha256": CONFIG["native_budget_sha256"], "commands": [],
              "formal_fits_started": 0, "old_study_completion_credit": 0,
              "physical_energy_joules": None, "claim": "Independent CPU execution of fixed source and declared fixtures only."}
    code = 2
    try:
        raw = base64.b64decode(CONFIG["archive_b64"], validate=True)
        if digest(raw) != CONFIG["sha256"]:
            raise RuntimeError("frozen source archive digest mismatch")
        root.mkdir()
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = [entry.filename for entry in archive.infolist()]
            if len(names) != len(set(names)) or set(names) != set(CONFIG["manifest"]):
                raise RuntimeError("archive paths do not exactly match the frozen manifest")
            for entry in archive.infolist():
                relative = PurePosixPath(entry.filename)
                if (relative.is_absolute() or ".." in relative.parts or str(relative) != entry.filename
                        or entry.is_dir() or (entry.external_attr >> 16) & 0o170000 == 0o120000
                        or not (entry.filename.startswith("qualification/hcsn_differentiable/")
                                or entry.filename == ".github/workflows/hcsn-differentiable.yml")):
                    raise RuntimeError("unadmitted source archive path")
                content = archive.read(entry)
                if digest(content) != CONFIG["manifest"][entry.filename]:
                    raise RuntimeError("archive member digest mismatch: " + entry.filename)
                destination = root / entry.filename
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("xb") as stream:
                    stream.write(content)
        if snapshot(root) != CONFIG["manifest"]:
            raise RuntimeError("extracted manifest differs from the frozen snapshot")
        for module, path in (("run_qualification", qualification_path), ("error_budget", budget_path)):
            record["commands"].append(run_module(root, "qualification.hcsn_differentiable." + module,
                                                  path, timeout=270))
        qualification, budget = load_report(qualification_path), load_report(budget_path)
        tests = qualification.get("tests", []) if qualification else []
        fixtures = budget.get("fixtures", []) if budget else []
        checks = {
            "both_commands_zero": len(record["commands"]) == 2 and all(c["exit_code"] == 0 for c in record["commands"]),
            "full_source_unchanged": snapshot(root) == CONFIG["manifest"],
            "qualification_sources_match_native": bool(qualification) and qualification.get("source_before") == CONFIG["qualification_sources"]
                and qualification.get("source_after") == CONFIG["qualification_sources"],
            "budget_sources_match_native": bool(budget) and budget.get("source_before") == CONFIG["budget_sources"]
                and budget.get("source_after") == CONFIG["budget_sources"],
            "test_inventory_matches_native": sorted(t["test"] for t in tests) == sorted(CONFIG["test_inventory"]),
            "all_tests_passed_without_skips": len(tests) == len(CONFIG["test_inventory"])
                and all(t.get("outcome") == "pass" for t in tests),
            "qualification_passed": bool(qualification) and qualification.get("status") == "passed"
                and qualification.get("tests_run") == len(CONFIG["test_inventory"])
                and all(qualification.get(name) == 0 for name in ("errors", "failures", "skipped", "expected_failures")),
            "cpu_single_thread": bool(qualification) and qualification.get("device") == "cpu"
                and qualification.get("cpu_threads") == 1 and qualification.get("cpu_interop_threads") == 1,
            "predeclared_budget_unchanged": bool(budget) and budget.get("budget") == CONFIG["budget_spec"],
            "all_budget_fixtures_passed": len(fixtures) == CONFIG["fixture_count"]
                and all(row.get("status") == "passed" and bool(row.get("gates"))
                        and all(gate.get("passed") is True for gate in row["gates"].values()) for row in fixtures),
            "budget_passed": bool(budget) and budget.get("status") == "passed" and budget.get("device") == "cpu",
            "both_report_source_guards_passed": bool(qualification) and bool(budget)
                and qualification.get("source_unchanged") is True and budget.get("source_unchanged") is True,
        }
        record.update(checks=checks, status="passed" if all(checks.values()) else "failed",
                      torch=qualification.get("torch") if qualification else None,
                      science_status="PASSED_DECLARED_FIXTURES" if all(checks.values()) else "HOLD")
        code = 0 if all(checks.values()) else 1
    except Exception:
        record.update(status="blocked", science_status="HOLD", detail=traceback.format_exc())
    finally:
        record["finished_utc"] = datetime.now(timezone.utc).isoformat()
        record["artifacts"] = {path.name: {"sha256": digest(path.read_bytes()), "bytes": path.stat().st_size}
                               for path in (qualification_path, budget_path) if path.is_file()}
        with verification_path.open("x", encoding="utf-8") as stream:
            json.dump(record, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
    print("HCSN_COLAB_VERIFICATION " + json.dumps({"status": record["status"], "code": code,
          "source_archive_sha256": CONFIG["sha256"], "verification_sha256": digest(verification_path.read_bytes())}), flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
