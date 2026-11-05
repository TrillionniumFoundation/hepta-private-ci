"""Cloud-only original-catalog regression and precise tamper controls."""

import ast
import collections
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / "build-only-current-host-v6" / "v6-candidate"
OUT = ROOT / "v7-candidate"
WORKSPACE = ROOT.parents[2]
EVIDENCE = ROOT / "cloud-verification-v1"
EVIDENCE.mkdir(exist_ok=False)


def pin(path):
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def run(label, cwd, argv):
    started = time.monotonic()
    proc = subprocess.run(argv, cwd=cwd, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True)
    stdout, stderr = EVIDENCE / (label + ".stdout"), EVIDENCE / (label + ".stderr")
    stdout.write_bytes(proc.stdout)
    stderr.write_bytes(proc.stderr)
    result = {"argv": argv, "cwd": str(cwd), "exit_code": proc.returncode,
              "elapsed_seconds": time.monotonic() - started, "stdout": pin(stdout), "stderr": pin(stderr)}
    (EVIDENCE / (label + ".status.json")).write_text(json.dumps(result, indent=2) + "\n")
    return result, proc.stdout + proc.stderr


old_path = WORKSPACE / "ci-audit/recovered-20261105/full-fb9-complete-archive/decoded-verified-v1/full-workspace-catalog.stdout"
new_path = WORKSPACE / "ci-audit/recovered-20261105/b16-ai395-cold-bootstrap-v1/p4-v3-catalog-readonly-export-v1/decoded-verified-v1/03-full-unfiltered-catalog.stdout.original"
old, new = json.loads(old_path.read_bytes()), json.loads(new_path.read_bytes())
assert pin(old_path)["sha256"] == "37aa98bace85dfa81d9c729820de24912d913bd85c3a10b60243f4dba67e4001"
assert pin(new_path)["sha256"] == "d4ca608073c2508e8ad5302b1188c7d2e21c6bf221a17688d77f625087e8d3f6"


def rows(catalog):
    return collections.Counter((sid, name, item["ignored"])
        for sid, suite in catalog["rust-suites"].items() for name, item in suite["testcases"].items())


old_rows, new_rows = rows(old), rows(new)
assert old_rows == new_rows and sum(old_rows.values()) == 19563
for catalog in (old, new):
    forms = collections.Counter((item["ignored"], json.dumps(item["filter-match"], sort_keys=True))
        for suite in catalog["rust-suites"].values() for item in suite["testcases"].values())
    assert forms == {(False, '{"status": "matches"}'): 19506,
                     (True, '{"reason": "ignored", "status": "mismatch"}'): 57}

# The preserved V6 runtime is exercised against the new test's real original
# testcase maps. No project test or original runtime file is modified.
old_runtime = EVIDENCE / "v6-runtime-real-catalog"
shutil.copytree(BASE, old_runtime, ignore=shutil.ignore_patterns("__pycache__"))
for name in ("test_build_only_guard.py", "observed-original-A-catalog.json"):
    shutil.copyfile(OUT / name, old_runtime / name)
case = "test_build_only_guard.BuildOnlyGuardTests.test_actual_context_is_accepted_but_different_host_or_source_is_rejected"
negative, raw = run("v6-original-catalog-rejection", old_runtime, [sys.executable, "-m", "unittest", "-v", case])
assert negative["exit_code"] == 1
assert b"Ran 1 test" in raw and b"FAILED (errors=1)" in raw
assert b"RuntimeError: build-only catalog was filtered" in raw
assert b"ImportError" not in raw and b"ModuleNotFoundError" not in raw

fixed, raw = run("v7-original-and-tamper-controls", OUT, [sys.executable, "-m", "unittest", "-v", "test_build_only_guard"])
assert fixed["exit_code"] == 0 and b"Ran 6 tests" in raw and raw.rstrip().endswith(b"OK")


def test_bodies(path):
    text = path.read_text()
    module = ast.parse(text)
    cls = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "BuildOnlyGuardTests")
    return {node.name: ast.get_source_segment(text, node)
            for node in cls.body if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")}


before, after = test_bodies(BASE / "test_build_only_guard.py"), test_bodies(OUT / "test_build_only_guard.py")
assert len(before) == 4 and len(after) == 6
assert all(after[name] == body for name, body in before.items())
for path in OUT.glob("*.py"):
    ast.parse(path.read_text())
result = {
    "schema": "hepta-b16-v7-original-catalog-cloud-controls-v1",
    "scope": "Cloud-only harness checks; no native build/list/test, product source, refs or host state changes.",
    "old_original": pin(old_path), "new_original": pin(new_path),
    "old_source": "fb9e131272f7e7a138d6c0d1af2b048b9a6ab7ff",
    "new_source": "4a3374e22e16ce5c764288ad018cd9affadf94ea",
    "complete_named_counter_equal": old_rows == new_rows,
    "eligible": 19506, "ignored": 57, "all_other_filter_forms": 0,
    "original_four_test_bodies_byte_equal": sorted(before),
    "fixture_correction": "Synthetic provenance/paths remain explicitly synthetic; every testcase name, ignored flag and filter dictionary comes from the complete original fb9 catalog.",
    "negative": negative, "fixed": fixed,
    "new_negative_subcases": {"filter_forms": 6, "named_counter_with_preserved_totals": 3},
    "project_ignored_policy_changed": False, "native_tests_executed": False,
}
(EVIDENCE / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({"verification": pin(EVIDENCE / "verification.json"),
                  "v6_original_catalog_exit": negative["exit_code"],
                  "v7_six_controls_exit": fixed["exit_code"],
                  "all_original_test_bodies_preserved": True}, indent=2))
