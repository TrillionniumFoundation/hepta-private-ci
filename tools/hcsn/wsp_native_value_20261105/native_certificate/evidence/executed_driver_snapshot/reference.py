#!/usr/bin/env python3
# Copyright 2026 TrillionniumFoundation
# SPDX-License-Identifier: Apache-2.0
"""Independent Fraction reference for supplied continuation certificate bytes.

This does not import the Rust arithmetic or any historical witness search. It
performs the original rational formulas directly, independently of Rust's fixed
integer units and shifts. It never evaluates a neural model or task utility.
"""
import hashlib
import json
import math
import struct
from fractions import Fraction as F

SEMANTICS = "binary64_rne_gradual_separate_products_sum49_v1"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def decode(text, count):
    data = bytes.fromhex(text)
    if len(data) != count * 8:
        raise ValueError("wrong F64 count")
    result = struct.unpack("<" + "d" * count, data)
    if not all(math.isfinite(x) for x in result):
        raise ValueError("nonfinite supplied value")
    return result


def encode(values):
    return struct.pack("<" + "d" * len(values), *values).hex()


def witness_digest(params):
    h = hashlib.sha256(b"hepta.weight.continuation-witness.v1\0")
    h.update(struct.pack("<Q", len(params["rows"])))
    for r in params["rows"]:
        h.update(struct.pack("<I", r["source_row"]))
        h.update(bytes.fromhex(r["state_sha256"]))
        h.update(bytes.fromhex(r["teacher_table_sha256"]))
        h.update(bytes(r["legal"]))
        h.update(bytes([r["target_action"], r["competitor_action"]]))
        for name in ("multiplier_f64_le_hex", "hidden_f64_le_hex", "teacher_q_f64_le_hex"):
            h.update(bytes.fromhex(r[name]))
    return h.hexdigest()


def bound(params):
    params["expected_checkpoint_sha256"] = sha(params["checkpoint_json"].encode())
    params["expected_witness_sha256"] = witness_digest(params)
    return params


def fraction_record(x):
    return {"numerator": str(x.numerator), "denominator": str(x.denominator)}


def fraction_read(x):
    return F(int(x["numerator"]), int(x["denominator"]))


def native_fraction(x):
    numerator = int(x["numerator_hex"], 16)
    denominator = int(x["denominator_hex"], 16)
    exponent = x["binary_exponent"]
    if not isinstance(exponent, int) or not -20000 <= exponent <= 20000 or denominator <= 0:
        raise ValueError("invalid native exact record")
    return F(numerator, denominator) * (F(2) ** exponent)


def reference(params):
    if params["semantics"] != SEMANTICS:
        raise ValueError("semantics")
    if sha(params["checkpoint_json"].encode()) != params["expected_checkpoint_sha256"]:
        raise ValueError("checkpoint identity")
    if witness_digest(params) != params["expected_witness_sha256"]:
        raise ValueError("witness identity")
    m = json.loads(params["checkpoint_json"])
    if m["head_dimensions"] != [85, 48, 4] or m["fit"] != params["source"]["fit_id"]:
        raise ValueError("checkpoint shape or fit")
    center_values = [float(x) for a in range(3) for x in m["network"]["w2"][a] + [m["network"]["b2"][a]]]
    c = [F.from_float(x) for x in center_values]
    r2 = sum((x * x for x in c), F()) / 4
    ru = math.isqrt(r2.numerator // r2.denominator)
    if ru * ru < r2:
        ru += 1
    if not 49 * max(abs(x) + ru for x in c) < 2**1000:
        raise ValueError("overflow envelope")
    u, eta = F(1, 2**53), F(1, 2**1074)
    gamma = 98 * u / (1 - 98 * u)
    error = [gamma * (sum(map(abs, c[a * 49:(a + 1) * 49]), F()) + 49 * ru)
             + 98 * eta / (1 - 98 * u) for a in range(3)]
    v, offset, nonzero = [F() for _ in range(147)], F(), 0
    for row in params["rows"]:
        hidden = decode(row["hidden_f64_le_hex"], 49)
        if hidden[-1] != 1 or not all(abs(x) <= 1 for x in hidden):
            raise ValueError("hidden bounds")
        if sha(bytes.fromhex(row["hidden_f64_le_hex"])) != row["hidden_sha256"]:
            raise ValueError("hidden identity")
        y = F.from_float(decode(row["multiplier_f64_le_hex"], 1)[0])
        if y < 0:
            raise ValueError("negative multiplier")
        nonzero += bool(y)
        a, b = row["target_action"] - 1, row["competitor_action"] - 1
        q = decode(row["teacher_q_f64_le_hex"], 6)
        chosen = max((i for i in range(6) if row["legal"][i]), key=lambda i: q[i])
        if a not in range(3) or b not in range(3) or a == b or chosen != a + 1 or not row["legal"][b + 1]:
            raise ValueError("illegal or inconsistent teacher label")
        for j, value in enumerate(hidden):
            value = y * F.from_float(value)
            v[49 * a + j] += value
            v[49 * b + j] -= value
        offset += y * (error[a] + error[b])
    d = -sum((x * y for x, y in zip(v, c)), F())
    norm = sum((x * x for x in v), F())
    right = r2 * norm
    proof = {"radius_squared": fraction_record(r2), "radius_upper": fraction_record(F(ru)),
             "dual_vector": [fraction_record(x) for x in v],
             "dual_vector_squared_norm": fraction_record(norm),
             "per_head_f64_absolute_error_bound": [fraction_record(x) for x in error],
             "weighted_f64_error_bound": fraction_record(offset), "nonzero_multipliers": nonzero}
    flags = []
    for name, value in [("ideal_real", d), ("f64_necessary_relaxation", d - offset)]:
        passed = value > 0 and value * value > right
        flags.append(passed)
        proof[name] = {"d": fraction_record(value), "d_positive": value > 0,
                       "left_squared": fraction_record(value * value),
                       "right_squared": fraction_record(right), "strict_separation": passed}
    proof["verdict"] = ("F64_NECESSARY_SYSTEM_INFEASIBLE" if flags[1] else
                        "IDEAL_REAL_ONLY_INFEASIBLE" if flags[0] else "NOT_CERTIFIED")
    return {"proof": proof, "center_f64_le_hex": encode(center_values),
            "center_f64_le_sha256": sha(bytes.fromhex(encode(center_values)))}


def compare_native(native, expected):
    if native["center_f64_le_hex"] != expected["center_f64_le_hex"]:
        raise ValueError("parsed checkpoint center F64 bytes differ")
    if native["center_f64_le_sha256"] != expected["center_f64_le_sha256"]:
        raise ValueError("center byte digest differs")
    actual, reference_proof = native["proof"], expected["proof"]
    for name in ("verdict", "nonzero_multipliers"):
        if actual[name] != reference_proof[name]:
            raise ValueError("native flag differs: " + name)
    for name in ("radius_squared", "radius_upper", "dual_vector_squared_norm", "weighted_f64_error_bound"):
        if native_fraction(actual[name]) != fraction_read(reference_proof[name]):
            raise ValueError("native exact quantity differs: " + name)
    for name in ("dual_vector", "per_head_f64_absolute_error_bound"):
        if [native_fraction(x) for x in actual[name]] != [fraction_read(x) for x in reference_proof[name]]:
            raise ValueError("native exact vector differs: " + name)
    for branch in ("ideal_real", "f64_necessary_relaxation"):
        for name in ("d_positive", "strict_separation"):
            if actual[branch][name] != reference_proof[branch][name]:
                raise ValueError("native sign/verdict differs")
        for name in ("d", "left_squared", "right_squared"):
            if native_fraction(actual[branch][name]) != fraction_read(reference_proof[branch][name]):
                raise ValueError("native exact comparison differs: " + name)
    for key in ("external_source_authentication", "hidden_or_teacher_program_reexecuted",
                "hardware_arithmetic_semantics_verified", "independent_holdout_verified",
                "task_value_improvement_qualified", "whole_network_impossibility_qualified",
                "production_eligible", "weights_modified"):
        if native[key] is not False:
            raise ValueError("unsupported qualification: " + key)
    return {"all_147_center_F64_bytes_exact": True, "all_exact_rational_quantities_equal": True,
            "scope_flags_preserved": True}
