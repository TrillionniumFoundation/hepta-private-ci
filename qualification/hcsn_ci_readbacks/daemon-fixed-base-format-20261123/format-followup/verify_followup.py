"""Verify the original hosted signed-worker fixture pair and first fixed-base negative."""
import hashlib
import json
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent
INPUT = {
    "candidate-owner-only.zip": "ed157a51a4a457d08fdb18f38fce72d90def1fbe71de34b2b47b5b3461e89460",
    "signed-original-pair.zip": "06cd48e3c4a6d98158eccf9d946b955f1cfa05f957b57853da26235dcefa2168",
}
BACKENDS = {"value_kernel": 172, "population_grid": 8, "population_age": 8}
BLOBS = {"base": "69190e27f1b6e36df4965ebde921c4dfac8978da", "candidate": "5821e344b78c9e71468ba155e0855da4aa5b3ca4"}

for file, sha in INPUT.items():
    assert hashlib.sha256((HERE / file).read_bytes()).hexdigest() == sha, file
with zipfile.ZipFile(HERE / "candidate-owner-only.zip") as archive:
    plan = json.loads(archive.read("plan.json"))
    assert (plan["same_ordered_rust_paths"], plan["unchanged_other_rust_commands"]) == (4219, 4217)
    assert len(plan["original_missing_owners"]) == 2 and len(plan["actual_runs"]) == 4
    assert archive.read("full-check.exit").strip() == b"1"
    assert b"cell_split_execution_cli.rs:481" in archive.read("full-check.log")
    assert archive.read("after-check.status") == b""
    assert b"Ran 38 tests" in archive.read("formatter-tests.log")

with zipfile.ZipFile(HERE / "signed-original-pair.zip") as archive:
    pair = json.loads(archive.read("pair.json"))
    assert pair["refs"] == {"base": "c12ee03f3185d5a13949faca54f066dfd634e509", "candidate":"40ea7f9e18acc0203731e0f715386f73b59423c1"}
    assert len(pair["cases"]) == 6
    captures = {}
    for row in pair["cases"]:
        arm, backend = row["arm"], row["backend"]
        assert backend in BACKENDS and arm in BLOBS and row["code"] == 0
        assert row["fixture_git_blob"] == BLOBS[arm] and row["source"] == pair["refs"][arm]
        name = arm + "-" + backend
        metadata = json.loads(archive.read(name + "/native-build.json"))
        assert metadata["source_sha256"] == row["fixture_sha256"]
        assert metadata["rustc_sha256"] == pair["rustc_sha256"]
        assert metadata["executable_sha256"] == row["native_fixture_elf_sha256"]
        res = json.loads(archive.read(name + "/result.json"))
        assert res["backend"] == backend and res["status"] == "passed"
        for key in ["signed_taskflow", "supervised", "resumed_output_exact", "resumed_all_state_exact", "base_bytes_unchanged"]:
            assert res[key] is True
        for key in ["production_adoption", "production_trust", "task_gain_qualified"]:
            assert res[key] is False
        assert res["trainable_parameters"] == res["gradient_parameters"] == BACKENDS[backend]
        assert res["completed_optimizer_steps"] == 1 and res["second_training_block"]["status"] == "passed"
        signed = res["signed_owner"]
        assert signed["authority"] == "DENY_ALL" and signed["production_trust"] is False
        for key in ["changed_receipt_rejected", "second_writer_rejected", "wrong_dispatch_rejected", "retry_same_receipt"]:
            assert signed[key] is True
        for key in ["tampered_payload_rejected", "old_model_clock_restore_rejected"]:
            assert res["cold_owner"][key] is True
        assert len({res["caller_pid"], res["worker_pid"], res["cold_python_pid"]}) == 3
        k = (backend, arm)
        assert k not in captures
        captures[k] = tuple(res[x] for x in ["initial_state_digest", "base_checkpoint_digest", "candidate_digest"]) + (res["clock_commit"]["clock_digest"],)
    assert len(captures) == 6
    for backend in BACKENDS:
        assert captures[backend, "base"] == captures[backend, "candidate"]
print("Original fixed-base 2-owner candidate: 38 tests, 4 physical owner calls, next original fixed-base failure retained. Original signed CPU bridge: 3/3 for each of 2 compiled sources, 3/3 same initial/base/updated/clock digests, original tamper and authority assertions intact.")

registered_zip = HERE / "registered-44.zip"
assert hashlib.sha256(registered_zip.read_bytes()).hexdigest() == "b1903e5f64a392efe5ae669c0463be3997ba344ff5ec32eae6a9aee71b81aef0"
with zipfile.ZipFile(registered_zip) as archive:
    scope = json.loads(archive.read("scope.json"))
    assert (scope["original_rust_list_identical"], scope["other_commands_unchanged"], scope["verified_immutable"], scope["maintained"], scope["checked_commands"]) == (4219, 4175, 37, 7, 88)
    records = json.loads(archive.read("actual-44.json"))
    assert len({(v["path"], v["check_mode"]) for v in records if v["exit"] == 0}) == 88
    assert b"Ran 41 tests" in archive.read("formatter-tests.log") and b"Ran 3 tests" in archive.read("starlark-tests.log")
    assert archive.read("full-check.exit").strip() == b"1" and b"hepta-prompt/src/v3.rs:319" in archive.read("full-check.log")
    assert archive.read("after-check.status") == b""
print("Registered 37 archives and 7 maintained source owners: 88/88 physical command calls, 44 tests (41+3), 4,175 untouched commands. Original full-check genuinely failed at prompt source line 319.")
