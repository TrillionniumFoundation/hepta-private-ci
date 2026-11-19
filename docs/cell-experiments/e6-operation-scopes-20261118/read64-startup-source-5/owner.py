"""Run the unchanged original verifier and expanded source-mutation gates on the reviewed startup composition."""
import contextlib
import fcntl
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tomllib
import unittest
BASE = Path("/home/qq/work/hepta-e6-operation-scope-20261118-2e9b")
ROOT = BASE / "source"
OUT = BASE / "read64-startup-source-probe-5"
OUT.mkdir(exist_ok=False)
locks = []
for path in (BASE / "native-component-owner.lock", BASE / "native-target-restored-1/.hepta-root-native-owner.lock"):
    handle = path.open("a+b")
    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    locks.append(handle)
assert json.loads((BASE / "read64-startup-contract-edit-5/RESULT.json").read_text())["successful"]
assert json.loads((BASE / "read64-startup-edit-7/RESULT.json").read_text())["successful"]
assert hashlib.sha256((ROOT / "codex-rs/hepta-agentd/src/production_post_a_q24.rs").read_bytes()).hexdigest() == "5111fb1d31e07a9ac962be464ea3bfe746ec9ccbd53d0ca9f20030d834c2ef3b"
assert hashlib.sha256((ROOT / "CALLERS.toml").read_bytes()).hexdigest() == "c71a35ddcbcac214f4c336b0f84ed944520539990de283791a703a404352d248"
(OUT / "owner.py").write_bytes(Path(__file__).read_bytes())
env = dict(os.environ)
env["PATH"] = str(BASE / "tooling/bin") + ":/home/qq/.cargo/bin:" + env["PATH"]
env["PYTHONDONTWRITEBYTECODE"] = "1"
paths = [
    "codex-rs/hepta-agentd/src/root_historical_task_read_client.rs",
    "codex-rs/hepta-agentd/src/cell_q24_dataset_operation.rs",
    "codex-rs/hepta-agentd/src/cell_q24_prepared_operation.rs",
    "codex-rs/hepta-agentd/src/cell_q24_freeze_operation.rs",
    "codex-rs/hepta-agentd/src/cell_q24_learning_historical_stage.rs",
    "codex-rs/hepta-agentd/src/cell_q24_prepared_learning.rs",
    "codex-rs/hepta-agentd/src/cell_q24_dataset_historical_preparation.rs",
    "codex-rs/hepta-agentd/src/cell_q24_dataset_historical_ledger.rs",
    "codex-rs/hepta-agentd/src/learning_iteration_historical_source.rs",
    "codex-rs/hepta-agentd/src/production_post_a_q24_owners.rs",
    "codex-rs/hepta-agentd/src/cell_q24_learning_preparation_tests.rs",
    "qa/b4-no-bypass/test_post_a_owner_files_source_closure.py",
    "qa/b4-no-bypass/test_q24_preparation_shared_checks_source_closure.py",
    "qa/b4-no-bypass/test_historical_dataset_capability_source_closure.py",
    "qa/b4-no-bypass/test_historical_preparation_source_closure.py",
    "qa/b4-no-bypass/test_historical_learning_delivery_source_closure.py",
    "qa/b4-no-bypass/test_original_task_data_source_closure.py",
    "CALLERS.toml",
    "codex-rs/hepta-agentd/src/root_historical_learning_operation.rs",
    "codex-rs/hepta-agentd/src/cell_q24_dataset_historical_task.rs",
    "codex-rs/hepta-agentd/src/production_post_a_q24.rs",
    "codex-rs/hepta-agentd/src/learning_iteration_successor.rs",
    "codex-rs/hepta-agentd/src/cell_q24_learning_successor.rs",
    "codex-rs/hepta-agentd/src/cell_q24_dataset_freeze_owner.rs",
    "codex-rs/hepta-agentd/src/cell_q24_learning_historical_operation.rs",
    "qa/b4-no-bypass/test_historical_startup_operation_source_closure.py",
    "qa/b4-no-bypass/test_historical_freezer_source_closure.py",
    "qa/b4-no-bypass/test_historical_current_trust_client_source_closure.py",
    "qa/b4-no-bypass/test_historical_dataset_capability_source_closure.py",
    "qa/b4-no-bypass/test_historical_task_read_source_closure.py",
    "qa/b4-no-bypass/test_historical_q24_stage_source_closure.py",
    "qa/b4-no-bypass/test_original_owner_operation_source_closure.py"
]
def hashes():
    return {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in paths}
before = hashes()
started = time.perf_counter()
fmt = subprocess.run(["just", "fmt"], cwd=ROOT / "codex-rs", env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
(OUT / "fmt.stdout").write_bytes(fmt.stdout)
(OUT / "fmt.stderr").write_bytes(fmt.stderr)
after = hashes()
manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
selected = {}
for kind in ["boundary", "protected_file"]:
    selected[kind] = [
        row for row in manifest.get(kind, [])
        if row.get("path") in paths or row.get("definition_path") in paths
        or row.get("id") in {"original_q24_prepared_operation", "original_q24_prepared_read"}
        or any(path in row.get("product_callers", []) for path in paths)
    ]
(OUT / "RELEVANT_CALLERS.json").write_text(json.dumps(selected, indent=2) + "\n")
sys.path.insert(0, str(ROOT / "qa/b4-no-bypass"))
names = [
    "test_post_a_owner_files_source_closure",
    "test_q24_preparation_shared_checks_source_closure",
    "test_original_owner_initialization_source_closure",
    "test_root_learning_scope_source_closure",
    "test_post_a_deadline_source_closure",
    "test_ordinary_original_callers_source_closure",
    "test_historical_preparation_source_closure",
    "test_historical_dataset_capability_source_closure",
    "test_historical_learning_delivery_source_closure",
    "test_q24_training_plan_source_closure",
    "test_historical_freezer_source_closure",
    "test_historical_startup_operation_source_closure",
]
coupled = subprocess.run(
    ["rg", "-l", "-e", "cell_q24_learning_historical_operation.rs", "-e", "root_historical_learning_operation.rs", "-e", "cell_q24_dataset_historical_task.rs", "-e", "cell_q24_dataset_freeze_owner.rs", "-e", "cell_q24_learning_successor.rs", "-e", "learning_iteration_successor.rs", "-e", "q24_original_prepared_operation", "-e", "cell_q24_prepared_learning.rs", "-e", "production_post_a_q24_owners.rs", "-e", "cell_q24_dataset_historical_preparation.rs", "-e", "cell_q24_dataset_historical_ledger.rs", "-e", "learning_iteration_historical_source.rs", "-e", "root_historical_task_read_client.rs", "-e", "cell_q24_dataset_operation.rs", "-e", "cell_q24_prepared_operation.rs", "-e", "cell_q24_freeze_operation.rs", "-e", "cell_q24_learning_historical_stage.rs", "qa/b4-no-bypass"],
    cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
assert coupled.returncode == 0, coupled.stderr.decode(errors="replace")
names = sorted(set(names) | {Path(path).stem for path in coupled.stdout.decode().splitlines()
                            if Path(path).name.startswith("test_") and path.endswith(".py")})
(OUT / "selected-modules.json").write_text(json.dumps(names, indent=2) + "\n")
suite = unittest.TestSuite()
for name in names:
    suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(importlib.import_module(name)))
stream = io.StringIO()
with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
(OUT / "source-qa.stdout").write_text(stream.getvalue())
proof = importlib.import_module("test_historical_ledger_readonly_source_closure").PROOF
sweep_started = time.perf_counter()
try:
    proof._verify_protected_files(ROOT, manifest)
    protected = {"passed": True, "rows": len(manifest["protected_file"])}
except Exception as error:
    import traceback
    protected = {"passed": False, "rows": len(manifest["protected_file"]),
                 "error": repr(error), "traceback": traceback.format_exc()}
protected["wall_seconds"] = time.perf_counter() - sweep_started
targeted_started = time.perf_counter()
# Check every boundary defined by, or calling into, the affected physical source files.
# The complete original CLI remains the required gate below; no verifier is changed.
targeted_ids = {row["id"] for row in selected["boundary"]}
# Existing caller lists cannot discover newly added callers. Include every
# boundary symbol invoked by the changed Rust sources, using the original
# strip/parser and verifier; expected caller sets remain exact.
import re
changed_rust = [path for path in paths if path.endswith(".rs")]
changed_code = "\n".join(proof._strip_cfg_test_items(proof._strip_rust_non_code((ROOT / path).read_text())) for path in changed_rust)
for row in manifest.get("boundary", []):
    name = row.get("symbol", "").rsplit("::", 1)[-1]
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) and re.search(r"\b" + re.escape(name) + r"\s*\(", changed_code):
        targeted_ids.add(row["id"])
assert "q24_original_batch_operation_check" in targeted_ids

try:
    code_index = {p.relative_to(ROOT).as_posix(): proof._strip_cfg_test_items(proof._strip_rust_non_code(p.read_text()))
                  for p in proof._source_files(ROOT, proof._string_tuple(manifest, "source_roots"))}
    field_cache = {}
    selected_boundaries = [b for b in proof._boundary_rows(manifest) if b.identifier in targeted_ids]
    assert len(selected_boundaries) == len(targeted_ids)
    actual = []
    failures = []
    for boundary in selected_boundaries:
        try:
            actual.append(proof._verify_boundary(ROOT, boundary, code_index,
                proof._string_tuple(manifest, "ignored_path_fragments"), fields_by_receiver_type=field_cache))
        except Exception as error:
            import traceback
            failures.append({"id": boundary.identifier, "error": repr(error), "traceback": traceback.format_exc()})
    targeted = {"passed": not failures, "rows": actual, "failures": failures,
                "expected_boundary_count": len(selected_boundaries)}
except Exception as error:
    import traceback
    targeted = {"passed": False, "error": repr(error), "traceback": traceback.format_exc()}
targeted["wall_seconds"] = time.perf_counter() - targeted_started
(OUT / "TARGETED_CALLER_PROOF.json").write_text(json.dumps(targeted, indent=2) + "\n")
print(json.dumps({"targeted_callers_passed": targeted["passed"], "wall_seconds": targeted["wall_seconds"]}), flush=True)

caller_start = time.perf_counter()
full_caller = subprocess.run([sys.executable, "scripts/verify_hepta_callers.py", "verify"],
    cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1800) if result.wasSuccessful() and protected["passed"] and targeted["passed"] else subprocess.CompletedProcess([], 125, b"", b"Selected source mutation or protected-file prerequisite failed; no complete caller scan was started.\n")
(OUT / "full-caller-proof.stdout").write_bytes(full_caller.stdout)
(OUT / "full-caller-proof.stderr").write_bytes(full_caller.stderr)
full_caller_seconds = time.perf_counter() - caller_start
searches = [
    ("profile-existing-calls", ["-n", r"\.root_profile\(", "codex-rs/hepta-agentd/src"]),
    ("q24-rule-functions", ["-n", "-e", "impl CellQ24SgdRuleV1", "-e", r"fn digest\(", "--glob", "*q24*", "codex-rs/hepta-agentd/src"]),
]
for name, args in searches:
    r = subprocess.run(["rg", *args], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    (OUT / (name + ".stdout")).write_bytes(r.stdout)
    (OUT / (name + ".stderr")).write_bytes(r.stderr)
status = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"], cwd=ROOT)
(OUT / "git-status.stdout").write_bytes(status)
receipt = {
    "source_parent": "74e91d9c588325a205018907b856830bf2f401f5",
    "scope": "Reviewed same-owner synchronous startup composition with 13 exact new boundary rows and adversarial guard tests; original verifier unchanged, physical read limit64 and all deadlines unchanged, native cases zero",
    "modules": names, "protected_file_sweep": protected,
    "before_sha256": before, "after_format_sha256": after,
    "just_fmt_exit": fmt.returncode, "tests_run": result.testsRun,
    "source_tests_successful": result.wasSuccessful(),
    "targeted_callers": targeted,
    "full_caller_proof_exit": full_caller.returncode, "full_caller_proof_wall_seconds": full_caller_seconds,
    "failures": [{"test": str(test), "traceback": message} for test, message in result.failures],
    "errors": [{"test": str(test), "traceback": message} for test, message in result.errors],
    "skipped": [{"test": str(test), "reason": reason} for test, reason in result.skipped],
    "wall_seconds": time.perf_counter() - started,
    "native_tests": 0, "model_calls": 0, "original_executor_mutated": False,
}
(OUT / "RESULT.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps({k: v for k, v in receipt.items() if k not in {"failures", "errors", "skipped", "targeted_callers", "before_sha256", "after_format_sha256", "modules"}}), flush=True)
print(json.dumps({"failures": len(receipt["failures"]), "errors": len(receipt["errors"]),
                  "skipped": len(receipt["skipped"]), "successful":
                  fmt.returncode == 0 and result.wasSuccessful() and protected["passed"] and full_caller.returncode == 0}), flush=True)
raise SystemExit(0 if fmt.returncode == 0 and result.wasSuccessful() and protected["passed"] and full_caller.returncode == 0 else 1)
