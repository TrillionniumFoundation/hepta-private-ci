"""Cheap, isolated rejection tests; never import or execute the numerical oracle."""
import copy
import datetime
import gzip
import hashlib
import importlib.abc
import importlib.util
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path("/tmp/hcsn-compiled-recovery")
OUT = Path("/tmp/hcsn_recovery_check_review")
PIN = "76480c80df71700c7a39906936521e5542ddc9c788282ea3a165dffafa7dc1f0"
CHECKER_PIN = "e5428232e7d3c81428e04eabfb5a595b014c9fc56cc9fdcaa3622c60e1663b07"
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
assert digest(ROOT / "RECOVERY_PROTOCOL_V1.json") == PIN
assert digest(ROOT / "recovery_check.py") == CHECKER_PIN
spec = importlib.util.spec_from_file_location("reviewed_recovery_check", ROOT / "recovery_check.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)

class OracleNotExecuted(Exception):
    pass

class DenyOracleImport(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "frozen_reference":
            raise OracleNotExecuted("Oracle import deliberately blocked before all numerical evaluation")
        return None

assert "frozen_reference" not in sys.modules
sys.meta_path.insert(0, DenyOracleImport())
protocol = json.loads((ROOT / "RECOVERY_PROTOCOL_V1.json").read_text())
points = json.loads((ROOT / "RECOVERY_CASES_V1.json").read_text())["rows"]
common = {"protocol_sha256": PIN, "binary_sha256": protocol["binary_sha256"],
          "source_sha256": protocol["source_sha256"]}
zero_jac = [[0.0] * 10 for _ in range(5)]
reference = dict(common)
reference["cases"] = [{"id": p["id"], "theta": p["theta"], "independently_valid": True,
                       "boundary": "SYNTHETIC_NOT_EVALUATED", "flow": "SYNTHETIC_NOT_EVALUATED"}
                      for p in points]
reference["rows"] = [{"case": p["id"], "slot": slot, "coordinate": "log_distance",
                      "state": 0.0, "values": [0.0] * 5, "jacobian": zero_jac,
                      "jacobian_first": zero_jac}
                     for p in points for slot in range(6)]
base = {"reference": reference}
for mode in checker.MODES:
    base[mode] = dict(common, mode=mode, rows=[
        {k: copy.deepcopy(v) for k, v in row.items() if k != "jacobian_first"} | {"status": 0}
        for row in reference["rows"]])

def archive(path, obj):
    raw = (json.dumps(obj, separators=(",", ":"), allow_nan=True) + "\n").encode()
    path.write_bytes(gzip.compress(raw, mtime=0))
    return {"file": path.name, "sha256": digest(path), "bytes": path.stat().st_size}

def save_payload(payload):
    fixture = OUT / "synthetic_fixture"
    fixture.mkdir(exist_ok=True)
    artifacts = {}
    artifacts["reference"] = archive(fixture / "REFERENCE.json.gz", payload["reference"])
    for mode in checker.MODES:
        payload[mode]["reference_sha256"] = artifacts["reference"]["sha256"]
        artifacts[mode] = archive(fixture / (mode + ".json.gz"), payload[mode])
    (fixture / "INDEX.json").write_text(json.dumps(
        {"protocol_sha256": PIN, "binary_sha256": protocol["binary_sha256"], "artifacts": artifacts}))
    return fixture

tests = []
def run(name, expected, mutate=None, bad_pin=False, corrupt_digest=False):
    payload = copy.deepcopy(base)
    if mutate:
        mutate(payload)
    fixture = save_payload(payload)
    if corrupt_digest:
        index_path = fixture / "INDEX.json"
        index = json.loads(index_path.read_text())
        index["artifacts"]["reference"]["sha256"] = "0" * 64
        index_path.write_text(json.dumps(index))
    try:
        checker.check(ROOT / "RECOVERY_PROTOCOL_V1.json", "0" * 64 if bad_pin else PIN,
                      fixture, OUT / "nonexistent_oracle_path")
    except checker.Invalid as error:
        actual = str(error)
        assert actual == expected, (name, expected, actual)
        tests.append({"name": name, "result": "rejected", "message": actual})
    except OracleNotExecuted as error:
        assert expected == "ORACLE_PHASE_REACHED_WITHOUT_EXECUTION", (name, str(error))
        tests.append({"name": name, "result": "preflight_reached_oracle_guard", "message": str(error)})
    else:
        raise AssertionError("Synthetic evidence must never obtain a numerical receipt: " + name)

run("wrong_protocol_pin", "Wrong frozen protocol", bad_pin=True)
run("wrong_artifact_digest", "Artifact binding mismatch", corrupt_digest=True)
run("missing_reference_row", "Missing/extra state rows",
    lambda p: p["reference"]["rows"].pop())
run("missing_case_metadata", "Missing parameter metadata",
    lambda p: p["reference"]["cases"].pop())
run("duplicate_reference_slot", "Reference ID/slot mismatch",
    lambda p: p["reference"]["rows"][1].update(slot=0))
run("invalid_parameter_case", "Rejected/unbound parameter point",
    lambda p: p["reference"]["cases"][0].update(independently_valid=False))
run("oracle_row_error", "Failed oracle row",
    lambda p: p["reference"]["rows"][0].update(error="synthetic"))
run("wrong_reference_jacobian_width", "Wrong vector length",
    lambda p: p["reference"]["rows"][0]["jacobian"][0].pop())
run("nonfinite_reference", "Nonfinite JSON token",
    lambda p: p["reference"]["rows"][0]["values"].__setitem__(0, float("nan")))
run("native_state_mismatch", "Input binding mismatch",
    lambda p: p["float64"]["rows"][0].update(state=1.0))
run("boolean_status", "Invalid execution status",
    lambda p: p["float64"]["rows"][0].update(status=False))
run("required_float64_rejection", "Required mode rejected/error state",
    lambda p: p["float64"]["rows"][0].update(status=1))
run("required_compensated32_error", "Required mode rejected/error state",
    lambda p: p["compensated32"]["rows"][0].update(error="synthetic"))
run("non_fp32_transported_output", "Non-FP32 transported output",
    lambda p: p["compensated32"]["rows"][0]["values"].__setitem__(0, 0.1))
def diagnostic_rejections(p):
    for row in p["float32"]["rows"]:
        row.update(status=1, error="synthetic diagnostic failure")
run("ordinary_fp32_errors_do_not_block_preflight", "ORACLE_PHASE_REACHED_WITHOUT_EXECUTION",
    diagnostic_rejections)

initial_identity = {
    "protocol": PIN, "checker": CHECKER_PIN,
    "prevalidation_mapping": digest(ROOT / "PREVALIDATION_MAPPING.json"),
    "source_mapping": digest(ROOT / "SOURCE_MAPPING.json"),
    "source_sha256": protocol["source_sha256"],
    "binary": protocol["binary_sha256"],
    "manifest": protocol["manifest_sha256"],
    "build_receipt": protocol["build_receipt_sha256"],
}
assert digest(ROOT / "RECOVERY_PROTOCOL_V1.json") == PIN
assert digest(ROOT / "recovery_check.py") == CHECKER_PIN
assert all(digest(ROOT / name) == expected for name, expected in protocol["source_sha256"].items())
assert digest(ROOT / "recovered.so") == protocol["binary_sha256"]
assert digest(ROOT / "RECOVERY_CASES_V1.json") == protocol["manifest_sha256"]
assert digest(ROOT / "RECOVERED_BUILD.json") == protocol["build_receipt_sha256"]
mapping_checks = {}
for name in ["PREVALIDATION_MAPPING.json", "SOURCE_MAPPING.json"]:
    rows = json.loads((ROOT / name).read_text())["files"]
    assert all(digest(Path(row["source_path"])) == row["sha256"] for row in rows)
    mapping_checks[name] = {"members": len(rows), "identities_verified": len(rows)}
report = {
    "schema": "hcsn.recovery-check-independent-readonly-review.v1",
    "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "reviewer": "/root/architecture_comparison",
    "scope": "Pre-evaluation independent source review and synthetic preflight rejection checks only",
    "identity": initial_identity,
    "mapping_checks": mapping_checks,
    "blocking_false_pass_findings": [],
    "ready_to_start": "Yes, conditional on remote persistence of the exact protocol, manifest, checker, writer and declared source/build/binary identities before any new outcome is opened",
    "reviewed_guards": [
        "Trusted protocol pin and source/binary/manifest/build seals; final source/binary and every bound raw artifact hash recheck",
        "Exactly 128 parameter cases and 768 state rows with ordered IDs, slots, FP32 inputs and native state bindings",
        "Required float64 and compensated32 errors reject; ordinary float32 errors remain diagnostics and cannot count as passes",
        "Finite shape-checked reference values and full Jacobians independently recalculated from frozen MP80 oracle",
        "Halved finite differences plus both parameter/state branch-neighbor checks and continuation one-sided derivative",
        "All 768 states of both required modes must meet the unchanged numerical gates; no dropped rejected cases"
    ],
    "synthetic_checks": tests,
    "synthetic_checks_count": len(tests),
    "scientific_oracle_calls": 0,
    "native_evaluator_calls": 0,
    "new_sample_outcomes_opened": False,
    "frozen_source_protocol_gate_changes": False,
    "limitations": [
        "This receipt is checker prevalidation, not numerical admission or evidence that either required mode passes",
        "The input manifest identities were read, but the new scientific outcomes were not evaluated",
        "Finite sampled CPU value/Jacobian evidence cannot establish uniform parameter-box validity, global C1, GPU/energy or network quality superiority",
        "New evidence cannot restore the lost original raw outcomes or inherit their admission",
        "End-to-end provenance relies on executing the exact sealed writer and binary and retaining its raw artifacts; this review does not certify hostile runtime isolation"
    ]
}
path = OUT / "INDEPENDENT_PREVALIDATION_REVIEW.json"
path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
print(json.dumps({"receipt": str(path), "sha256": digest(path),
                  "checks": len(tests), "scientific_oracle_calls": 0,
                  "blocking_false_pass_findings": []}))

