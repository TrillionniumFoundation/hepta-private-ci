#!/usr/bin/env python3
"""Independent, read-only check of retained native-certificate records.

Does not execute Rust, the model, a teacher, training, or witness search. The
integer accumulator below is independently written from the documented binary64
representation; its result is compared both to native records and saved Fraction
records. Source-program semantics and real hardware arithmetic are not replayed.
"""
import argparse
import gzip
import hashlib
import json
import math
import re
import struct
import time
from fractions import Fraction as F
from pathlib import Path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    data = path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix == ".gz" else data)


def rational(value):
    if "numerator_hex" in value:
        return F(int(value["numerator_hex"], 16), int(value["denominator_hex"], 16)) * F(2) ** value["binary_exponent"]
    return F(int(value["numerator"]), int(value["denominator"]))


def units(raw):
    bits, = struct.unpack("<Q", raw)
    exp = (bits >> 52) & 2047
    assert exp < 2047
    mantissa = bits & ((1 << 52) - 1)
    magnitude = mantissa if exp == 0 else ((1 << 52) | mantissa) << (exp - 1)
    return -magnitude if bits >> 63 else magnitude


def normalized(value):
    if isinstance(value, dict):
        if "numerator_hex" in value or "numerator" in value:
            return rational(value)
        return {k: normalized(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalized(v) for v in value]
    return value


def unwrap(path):
    rpc = read(path)
    assert rpc["isError"] is False
    return json.loads(rpc["content"][0]["text"])


def main(base):
    cpu_start, wall_start = time.process_time(), time.monotonic()
    bundle = base / "evidence/complete-r1"
    qualification = bundle / "qualification"
    corpus = qualification / "native-certificate-corpus-r1"
    manifest = read(bundle / "BUNDLE_MANIFEST.json")
    for name, expected in manifest["files"].items():
        data = (bundle / name).read_bytes()
        assert len(data) == expected["bytes"] and digest(data) == expected["sha256"], name
    protocol_path = qualification / "native-certificate-execution-r1.json"
    protocol = read(protocol_path)
    assert digest(protocol_path.read_bytes()) == manifest["protocol_sha256"]
    source_manifest = read(qualification / "native-certificate-attempt-1/SOURCE_MANIFEST.json")
    assert protocol["native_sources"] == {k: v["sha256"] for k, v in source_manifest.items()}
    previous = read(base.parent / "literature/INDEPENDENT_NATIVE_REVIEW.json")
    source_count = 0
    for name, expected in previous["reviewed_source_files"].items():
        data = (base / "source" / name).read_bytes()
        assert digest(data) == expected["sha256"] and len(data) == expected["bytes"]
        if name in source_manifest:
            assert source_manifest[name] == expected
            snapshot = qualification / "native-certificate-attempt-1/source_snapshot" / name
            assert snapshot.read_bytes() == data
            source_count += 1
    for name, expected in protocol["driver_sources"].items():
        assert digest((bundle / "executed_driver_snapshot" / name).read_bytes()) == expected
    inputs = base / "inputs-r1"
    input_manifest = read(inputs / "INPUT_MANIFEST.json")
    assert digest((inputs / "INPUT_MANIFEST.json").read_bytes()) == protocol["input_manifest_sha256"]
    for item in input_manifest["files"]:
        data = (inputs / item["name"]).read_bytes()
        assert len(data) == item["bytes"] and digest(data) == item["sha256"]
        assert len(gzip.decompress(data)) == item["decoded_bytes"]
    results = read(corpus / "RESULTS.json")
    fit_records = []
    false_flags = ["caller_supplied_digests_are_trust_roots", "external_source_authentication", "hardware_arithmetic_semantics_verified", "hidden_or_teacher_program_reexecuted", "independent_holdout_verified", "production_eligible", "task_value_improvement_qualified", "weights_modified", "whole_network_impossibility_qualified"]
    row_fields = "source_row state_sha256 teacher_table_sha256 hidden_f64_le_hex hidden_sha256 multiplier_f64_le_hex teacher_q_f64_le_hex legal target_action competitor_action".split()
    source_fields = "fit_id protocol_sha256 feature_source_sha256 teacher_source_sha256 original_witness_record_sha256".split()
    for fit in (11, 23, 37, 53, 71):
        req = read(inputs / f"fit_{fit}_REQUEST.json.gz")
        reference = read(inputs / f"fit_{fit}_REFERENCE.json.gz")
        native = unwrap(corpus / f"fit_{fit}_RPC.json.gz")
        assert native["source"] == req["source"]
        assert all(native[x] is False for x in false_flags)
        assert native["gradient_steps"] == 0
        assert native["checkpoint_sha256"] == req["expected_checkpoint_sha256"] == digest(req["checkpoint_json"].encode())
        canonical = {"semantics": req["semantics"], "checkpoint_json": req["checkpoint_json"], "expected_checkpoint_sha256": req["expected_checkpoint_sha256"], "expected_witness_sha256": req["expected_witness_sha256"], "source": {k: req["source"][k] for k in source_fields}, "rows": [{k: r[k] for k in row_fields} for r in req["rows"]]}
        canonical_bytes = json.dumps(canonical, ensure_ascii=False, separators=(",", ":")).encode()
        assert digest(canonical_bytes) == native["request_sha256"]
        assert len(canonical_bytes) == native["canonical_request_bytes"]
        checkpoint = json.loads(req["checkpoint_json"])
        center = [x for a in range(3) for x in checkpoint["network"]["w2"][a] + [checkpoint["network"]["b2"][a]]]
        center_bytes = struct.pack("<147d", *center)
        assert center_bytes.hex() == native["center_f64_le_hex"] == reference["center_f64_le_hex"]
        assert digest(center_bytes) == native["center_f64_le_sha256"] == reference["center_f64_le_sha256"]
        c = list(map(F.from_float, center))
        v_units, y_sums = [0] * 147, [0] * 3
        witness_digest = hashlib.sha256(b"hepta.weight.continuation-witness.v1\0")
        witness_digest.update(struct.pack("<Q", len(req["rows"])))
        nonzero, identities, comparisons = 0, {}, set()
        for row in req["rows"]:
            h_raw = bytes.fromhex(row["hidden_f64_le_hex"])
            assert digest(h_raw) == row["hidden_sha256"]
            h_values = struct.unpack("<49d", h_raw)
            assert h_values[-1] == 1 and all(math.isfinite(x) and abs(x) <= 1 for x in h_values)
            identity = tuple(json.dumps(row[k], sort_keys=True) for k in row_fields if k not in ("source_row", "multiplier_f64_le_hex", "competitor_action"))
            assert identities.setdefault(row["source_row"], identity) == identity
            pair = row["source_row"], row["target_action"], row["competitor_action"]
            assert pair not in comparisons
            comparisons.add(pair)
            a, b = row["target_action"] - 1, row["competitor_action"] - 1
            q = struct.unpack("<6d", bytes.fromhex(row["teacher_q_f64_le_hex"]))
            assert all(math.isfinite(x) for x in q)
            assert max((i for i in range(6) if row["legal"][i]), key=lambda i: q[i]) == a + 1
            assert a in range(3) and b in range(3) and a != b and row["legal"][b + 1]
            y = units(bytes.fromhex(row["multiplier_f64_le_hex"]))
            assert y >= 0
            nonzero += y != 0
            y_sums[a] += y
            y_sums[b] += y
            for j in range(49):
                product = y * units(h_raw[8*j:8*j+8])
                v_units[49*a+j] += product
                v_units[49*b+j] -= product
            witness_digest.update(struct.pack("<I", row["source_row"]))
            witness_digest.update(bytes.fromhex(row["state_sha256"]))
            witness_digest.update(bytes.fromhex(row["teacher_table_sha256"]))
            witness_digest.update(bytes(row["legal"]))
            witness_digest.update(bytes([a+1, b+1]))
            for k in ("multiplier_f64_le_hex", "hidden_f64_le_hex", "teacher_q_f64_le_hex"):
                witness_digest.update(bytes.fromhex(row[k]))
        assert witness_digest.hexdigest() == req["expected_witness_sha256"] == native["witness_sha256"]
        p = normalized(native["proof"])
        assert p == normalized(reference["proof"])
        v = [F(x, 1 << 2148) for x in v_units]
        r2 = sum(x*x for x in c) / 4
        ru = math.isqrt(r2.numerator // r2.denominator)
        if ru * ru < r2:
            ru += 1
        u, eta = F(1, 2**53), F(1, 2**1074)
        gamma = 98*u/(1-98*u)
        errors = [gamma*(sum(map(abs, c[a*49:(a+1)*49]))+49*ru)+98*eta/(1-98*u) for a in range(3)]
        offset = sum(F(y_sums[a], 1 << 1074)*errors[a] for a in range(3))
        norm = sum(x*x for x in v)
        d = -sum(x*y for x, y in zip(v, c))
        assert p["dual_vector"] == v and p["radius_squared"] == r2 and p["radius_upper"] == ru
        assert p["dual_vector_squared_norm"] == norm and p["per_head_f64_absolute_error_bound"] == errors
        assert p["weighted_f64_error_bound"] == offset and p["nonzero_multipliers"] == nonzero
        for name, distance in (("ideal_real", d), ("f64_necessary_relaxation", d-offset)):
            assert p[name] == {"d": distance, "d_positive": distance > 0, "left_squared": distance*distance, "right_squared": r2*norm, "strict_separation": distance > 0 and distance*distance > r2*norm}
            assert p[name]["strict_separation"] is True
        assert p["verdict"] == "F64_NECESSARY_SYSTEM_INFEASIBLE"
        assert native["implementation_source_sha256"] == protocol["native_sources"]["src/mcp/weight_certificate.rs"]
        assert native["arithmetic_source_sha256"] == protocol["native_sources"]["src/mcp/weight_certificate_exact.rs"]
        fit_records.append({"fit": fit, "rows": len(req["rows"]), "center_f64_coefficients_exact": 147, "all_exact_quantities_recomputed": True, "source_semantics_reexecuted": False})
    controls = []
    for control in results["controls"]:
        rpc = read(corpus / ("control_" + control["case"] + "_RPC.json.gz"))
        if control["expected"] == "ERROR":
            assert rpc["isError"] is True and rpc["content"][0]["text"]
            observed = rpc["content"][0]["text"]
        else:
            native = json.loads(rpc["content"][0]["text"])
            assert rpc["isError"] is False and native["proof"]["verdict"] == control["expected"]
            assert all(native[k] is False for k in false_flags)
            p = normalized(native["proof"])
            for name in ("ideal_real", "f64_necessary_relaxation"):
                x = p[name]
                assert x["left_squared"] == x["d"]**2
                assert x["right_squared"] == p["radius_squared"]*p["dual_vector_squared_norm"]
                assert x["d_positive"] == (x["d"] > 0)
                assert x["strict_separation"] == (x["d"] > 0 and x["left_squared"] > x["right_squared"])
            observed = native["proof"]["verdict"]
        controls.append({"case": control["case"], "expected": control["expected"], "observed": observed})
    q = read(qualification / "native-certificate-attempt-1/RESULT.json")
    assert q["binary"]["sha256"] == protocol["binary_sha256"] == results["binary_sha256"]
    assert q["source_unchanged"] is True and q["all_passed"] is True
    for i, command in enumerate(q["commands"], 1):
        log = (qualification / f"native-certificate-attempt-1/command-{i}.log").read_bytes()
        assert digest(log) == command["log_sha256"] and len(log) == command["log_bytes"]
        assert command["exit_code"] == 0 and command["timed_out"] is False
    tests = {}
    for i in (2, 4):
        log = (qualification / f"native-certificate-attempt-1/command-{i}.log").read_text()
        tests[str(i)] = {"result": re.search(r"test result:.*", log).group(), "ignored": [x for x in log.splitlines() if "... ignored" in x]}
        assert "87 passed; 0 failed; 2 ignored" in tests[str(i)]["result"]
    corpus_receipt = read(qualification / "native-certificate-corpus-r1-outer/PROCESS_RECEIPT.json")
    software_receipt = read(qualification / "native-certificate-attempt-1-outer/PROCESS_RECEIPT.json")
    assert corpus_receipt["exit_code"] == software_receipt["exit_code"] == 0
    assert corpus_receipt["timed_out"] is False
    return {"status": "PURE_RECORD_AUDIT_PASS", "bundle_files_hashed": len(manifest["files"]), "reviewed_native_source_files_matched": source_count, "frozen_driver_files_hashed": len(protocol["driver_sources"]), "protocol_sha256": digest(protocol_path.read_bytes()), "published_source_commit": manifest["published_source_commit"], "fits": fit_records, "controls": controls, "software_test_records": tests, "corpus_whole_process_receipt": corpus_receipt, "software_whole_process_receipt": software_receipt, "reviewer_self_cpu_seconds": time.process_time()-cpu_start, "reviewer_wall_seconds": time.monotonic()-wall_start, "reviewer_executed_native_or_model": False, "new_task_value_qualification": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("base", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = main(args.base)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: result[k] for k in ("status", "bundle_files_hashed", "reviewer_self_cpu_seconds", "reviewer_wall_seconds")}))
