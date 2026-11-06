"""Run scoped tests and evidence checks, restoring lossless files if necessary.
Unique test IDs are bookkeeping, not independent experimental observations.
"""
import argparse
import contextlib
import gzip
import hashlib
import importlib.metadata
import io
import json
import os
import platform
import sys
import traceback
import unittest
from datetime import datetime, timezone
from pathlib import Path

V3 = Path(__file__).resolve().parents[1]
REPO = V3.parents[3]
PREFIX = ".".join(V3.relative_to(REPO).parts)
EXCLUDED = V3 / "ndu_llm_confirmation/external_smoke/sources/statistics.py"
sys.path.insert(0, str(REPO))


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bind(path, hashes, expected=None):
    value = sha(path)
    hashes[str(path.relative_to(REPO))] = value
    require(expected is None or value == expected, "Hash mismatch: " + str(path))
    return value


def load(path, hashes):
    bind(path, hashes)
    return json.loads(path.read_text())


def source_hashes(roots):
    files = {p for root in roots for p in root.rglob("*.py") if p != EXCLUDED}
    files.update(p / "__init__.py" for p in (V3, *V3.parents)
                 if p.is_relative_to(REPO) and (p / "__init__.py").is_file())
    return {str(p.relative_to(REPO)): sha(p) for p in sorted(files)}


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def check_evidence(hashes):
    state = V3 / "ndu_learned_stateful"
    data = state / "evidence/registered_v1"
    storage = load(data / "storage_manifest.json", hashes)
    for item in storage["files"].values():
        for part in item["parts"]:
            bind(data / part["path"], hashes, part["sha256"])
    restored = importlib.import_module(PREFIX + ".ndu_learned_stateful.materialize").materialize()
    storage_check = load(state / "evidence/storage_validation.json", hashes)
    bind(state / "materialize.py", hashes, storage_check["source_sha256"])
    require(restored["files"] == storage_check["files"] and storage_check["status"] == "matched", "Storage validation mismatch")
    frozen = load(state / "freeze.json", hashes)["source_sha256"]
    require(set(frozen) == {"model.py", "study.py", "test_model.py", "protocol.json"}, "Frozen source inventory")
    for name, expected in frozen.items():
        bind(state / name, hashes, expected)
    manifest = load(data / "manifest.json", hashes)["sha256"]
    extras = {"manifest.json", "storage_manifest.json", ".gitignore"}
    require({p.name for p in data.iterdir() if p.is_file()} == set(manifest) | extras, "Unbound registered files")
    bind(data / ".gitignore", hashes)
    for name, expected in manifest.items():
        bind(data / name, hashes, expected)
    for name in ("freeze.json", "protocol.json"):
        require((data / name).read_bytes() == (state / name).read_bytes(), "Registered copy mismatch: " + name)
    snapshot = load(data / "source_snapshot.json", hashes)
    require(set(snapshot) == set(frozen), "Snapshot source inventory")
    for name, text in snapshot.items():
        require(text.encode("utf-8") == (state / name).read_bytes(), "Snapshot text mismatch: " + name)
    require(load(data / "results.json", hashes)["source_sha256"] == frozen, "Result source binding")
    validation = load(state / "evidence/validation.json", hashes)
    require(validation["status"] == "passed", "Stored stateful audit not passed")
    bind(data / "results.json", hashes, validation["results_sha256"])
    bind(state / "audit.py", hashes, validation["audit_source_sha256"])
    smoke = V3 / "ndu_llm_confirmation/external_smoke"
    receipt = load(smoke / "evidence/qualification-final.json", hashes)
    require("../../ndu_walltime/runtime.py" in receipt["source_sha256"], "Missing runtime source binding")
    for name, expected in receipt["source_sha256"].items():
        bind((smoke / name).resolve(), hashes, expected)
    require(hashlib.sha256(canonical(receipt["records"]).encode()).hexdigest() == receipt["records_sha256"], "Smoke record digest")
    for row in load(smoke / "sources.json", hashes)["files"]:
        if row.get("encoding") == "gzip":
            path = smoke / "sources" / row["storage_file"]
            bind(path, hashes, row["storage_sha256"])
            raw = gzip.decompress(path.read_bytes())
            require(len(raw) == row["bytes"] and hashlib.sha256(raw).hexdigest() == row["sha256"], "Raw source reconstruction mismatch")
        else:
            bind(smoke / "sources" / row["local_file"], hashes, row["sha256"])
    require(load(smoke / "tasks.json", hashes)["confirmation_eligible"] is False, "Smoke scope changed")
    llm = V3 / "ndu_llm_confirmation"
    qualification = load(llm / "evidence/qualification.json", hashes)
    require(qualification["exit_code"] == 0 and qualification["tests_run"] == 39, "LLM package qualification mismatch")
    require(qualification["source_sha256_before"] == qualification["source_sha256_after"], "Qualification source drift")
    for name, expected in qualification["source_sha256_after"].items():
        bind(REPO / name, hashes, expected)
    review = llm / "independent_review"
    independent = load(review / "manifest.json", hashes)
    require(independent["status"] == "LOCAL_ENGINEERING_REVIEW_PASS" and independent["source_stable"] is True, "Independent review not accepted")
    for name, expected in independent["files_sha256"].items():
        bind(review / name, hashes, expected)
    for name, expected in independent["target_source_sha256"].items():
        bind(llm / name, hashes, expected)
    for name, count in (("review_gate_v2_clock_fixed.json", 121), ("review_runtime_v2_clock_fixed.json", 23)):
        checked = load(review / name, hashes)
        require(checked["status"] == "PASS" and checked["passed"] == checked["check_count"] == count and checked["failed"] == 0, "Independent receipt mismatch")
        require(checked["source_sha256_before"] == checked["source_sha256_after"] == independent["target_source_sha256"], "Independent source mismatch")
    return {"stateful_stored_artifacts": "matched", "lossless_restoration": restored,
            "external_smoke_stored_artifacts": "matched", "llm_qualification_tests": 39,
            "independent_gate_checks": 121, "independent_runtime_checks": 23,
            "independent_checks_counted_as_unittests": False}


def main(output):
    output = output.expanduser().absolute()
    require(not output.exists() and not output.is_symlink(), "Refusing to overwrite output: " + str(output))
    os.chdir(REPO)
    hashes, out, err = {}, io.StringIO(), io.StringIO()
    old_path = V3 / "ndu_walltime/evidence/integrated-scoped-validation.json"
    old = list(load(old_path, hashes)["module_counts"])
    require(len(old) == 13 and all(m.startswith(PREFIX + ".") for m in old), "Old 13-module inventory")
    llm = [PREFIX + ".ndu_llm_confirmation." + p.stem for p in sorted((V3 / "ndu_llm_confirmation").glob("test_*.py"))]
    modules = list(dict.fromkeys(old + [PREFIX + ".ndu_learned_stateful.test_model"] + llm + [PREFIX + ".ndu_llm_confirmation.external_smoke.test_tools"]))
    roots = {REPO.joinpath(*m.split(".")[:-1]) for m in modules} | {Path(__file__).resolve().parent}
    before = source_hashes(roots)
    report = {"schema": "ndu.scoped-blocker-verification.v1", "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "runtime": {"python": sys.version, "executable": sys.executable, "platform": platform.platform()},
              "modules": modules, "source_sha256_before": before, "status": "failed",
              "scope": "Listed Python unit modules, stored-artifact consistency and separately counted finite math checks only; no study rerun, paid API calls, whole-repository CI, external review or live-model confirmation."}
    for package in ("numpy", "scipy"):
        try:
            report["runtime"][package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            report["runtime"][package] = "not installed"
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            report["evidence"] = check_evidence(hashes)
            loader, unique, duplicates, counts, collected = unittest.TestLoader(), {}, [], {}, 0
            for module in modules:
                counts[module] = 0
                suite = loader.loadTestsFromName(module)
                require(suite.countTestCases() > 0, "Empty test module: " + module)
                for test in flatten(suite):
                    collected += 1
                    if test.id() in unique:
                        duplicates.append(test.id())
                    else:
                        unique[test.id()] = test
                        counts[module] += 1
            report.update(module_counts=counts, collected_test_count=collected, unique_test_count=len(unique),
                          test_ids=list(unique), duplicate_ids_removed=duplicates, discovery_errors=loader.errors)
            require(not loader.errors and bool(unique), "Missing test module; inspect discovery_errors")
            result = unittest.TextTestRunner(stream=err, verbosity=2).run(unittest.TestSuite(unique.values()))
            report.update(actual_run_count=result.testsRun, unittest_success=result.wasSuccessful(),
                          failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
                          expected_failures=len(result.expectedFailures), unexpected_successes=len(result.unexpectedSuccesses))
            theory = importlib.import_module(PREFIX + ".ndu_learned_stateful.verify_theory").verify()
            committed = load(V3 / "ndu_learned_stateful/theory_verification.json", hashes)
            require(theory["check_count"] == len(theory["checks"]) == 84, "Theory assertion inventory")
            require(canonical(theory) == canonical(committed), "Theory receipt canonical mismatch")
            report["theory"] = {"assertion_count": 84, "counted_as_unittests": False, "matches_committed": True,
                                "canonical_sha256": hashlib.sha256(canonical(theory).encode()).hexdigest()}
            require(result.wasSuccessful() and result.testsRun == len(unique), "Scoped unittest run failed/incomplete")
            report["status"] = "passed"
    except Exception:
        traceback.print_exc(file=err)
    after = source_hashes(roots)
    unchanged = before == after and all(sha(REPO / name) == value for name, value in hashes.items())
    if not unchanged:
        report["status"] = "failed"
        err.write("Source or evidence changed during verification.\n")
    report.update(finished_at_utc=datetime.now(timezone.utc).isoformat(), source_sha256_after=after,
                  source_and_evidence_unchanged=unchanged, evidence_sha256=hashes, stdout=out.getvalue(), stderr=err.getvalue())
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"status": report["status"], "output": str(output), "sha256": sha(output)}))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    raise SystemExit(main(parser.parse_args().output))
