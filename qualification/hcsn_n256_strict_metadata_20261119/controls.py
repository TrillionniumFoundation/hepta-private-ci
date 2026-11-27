"""Synthetic before/after controls; no model or execution admission is produced."""

import copy
import hashlib
import json
from pathlib import Path
import resource
import sys
import time

from . import contract


def _check(condition, message):
    if not condition:
        raise RuntimeError(message)


def _accepts(validator, value):
    try:
        validator(value)
    except (ValueError, TypeError, AttributeError):
        return False
    return True


def _replace(record, path, value):
    result = copy.deepcopy(record)
    cursor = result
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    return result


def run():
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    original = contract._legacy
    request = json.loads(contract._request_bytes)
    receipt = contract._receipt_shape()
    receipt["capsule_bytes"] = 600000
    records = {"request": request, "receipt": receipt}
    validators = {
        "request": (original.validate_request, contract.validate_request),
        "receipt": (original.validate_future_receipt, contract.validate_future_receipt),
    }
    cases = []

    def case(name, kind, value, expected_old, expected_new):
        old, new = validators[kind]
        actual = (_accepts(old, value), _accepts(new, value))
        _check(actual == (expected_old, expected_new), f"{name}: {actual}")
        if kind == "receipt":
            _check(_accepts(contract.canonical_json, value) == expected_new, f"canonical: {name}")
        cases.append({"name": name, "kind": kind, "old_accepted": actual[0], "strict_accepted": actual[1]})

    for kind, value in records.items():
        case(f"valid_{kind}", kind, value, True, True)
    _check(original.canonical_json(receipt) == contract.canonical_json(receipt), "valid wire bytes changed")
    mutations = [
        ("request", ["parent_draft"], 6609.0, True),
        ("request", ["target", "lane_order"], True, True),
        ("request", ["target", "time_fraction", 0], 1.0, True),
        ("request", ["future_execution_envelope", "torch_calls"], False, True),
        ("request", ["future_execution_envelope", "optimizer_steps"], 0.0, True),
        ("request", ["serializer_requirements", "inherited_serializer_fullstate_ready"], 0, True),
        ("request", ["serializer_requirements", "future_serializer_revision_required"], 1, True),
        ("request", ["authentic_firststep_capsules"], False, True),
        ("request", ["authentic_firststep_coordinates"], 0.0, True),
        ("request", ["bindings", "input_bundle_sha256"], "0" * 64, True),
        ("receipt", ["target", "lane_order"], True, True),
        ("receipt", ["coordinate_counts", "total"], 69728.0, True),
        ("receipt", ["coordinate_counts", "mismatches"], False, True),
        ("receipt", ["packet_count"], 9.0, True),
        ("receipt", ["serialized_packet_output_coordinates"], 264.0, True),
        ("receipt", ["calls", "torch_calls"], False, True),
        ("receipt", ["calls", "torch_calls"], 0.0, True),
        ("receipt", ["calls", "optimizer_steps"], False, True),
        ("receipt", ["calls", "optimizer_steps"], 0.0, True),
        ("receipt", ["calls", "candidate_dynamic_steps"], True, False),
        ("receipt", ["coordinate_counts", "mismatches"], 1291, False),
        ("receipt", ["candidate_oracle_bitwise_equal"], False, False),
        ("receipt", ["all_closed"], True, False),
        ("receipt", ["capsule_bytes"], 8388609, False),
        ("request", ["numerical_execution_allowed"], True, False),
    ]
    for index, (kind, path, value, old_accepts) in enumerate(mutations):
        case(f"mutation_{index:02d}_{'.'.join(map(str, path))}_{value!r}", kind,
             _replace(records[kind], path, value), old_accepts, False)
    for field in ("future_sources", "required_future_admission"):
        case(f"{field}_renamed", "request", _replace(request, [field], {"unrelated_placeholder": None}), True, False)
        missing = copy.deepcopy(request)
        del missing[field][next(iter(missing[field]))]
        case(f"{field}_missing", "request", missing, True, False)
        extra = copy.deepcopy(request)
        extra[field]["unexpected"] = None
        case(f"{field}_extra", "request", extra, True, False)
    for kind, value in records.items():
        extra = copy.deepcopy(value)
        extra["unexpected"] = None
        case(f"{kind}_extra_top_level", kind, extra, True, False)
        case(f"{kind}_wrong_root_type", kind, [], False, False)
    extra = copy.deepcopy(receipt)
    extra["calls"]["unreported_work"] = 99
    case("receipt_extra_call", "receipt", extra, True, False)
    _check(not any(name.split(".")[0] in {"torch", "numpy", "scipy"} for name in sys.modules), "numerical package loaded")
    root = Path(__file__).parent
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in ("contract.py", "controls.py", "PROTOCOL.json")}
    return {
        "profile": contract.PROFILE, "status": "PASS_SYNTHETIC_METADATA_ONLY",
        "python": sys.version, "optimization_level": sys.flags.optimize,
        "source_sha256": hashes, "original_contract_sha256": contract.CONTRACT_SHA256,
        "original_request_sha256": contract.REQUEST_SHA256, "cases": cases,
        "case_count": len(cases), "old_accepts_malformed": sum(r["old_accepted"] and not r["strict_accepted"] for r in cases),
        "strict_accepts_valid": 2, "body_wall_seconds": time.perf_counter() - start_wall,
        "body_cpu_seconds": time.process_time() - start_cpu,
        "process_maxrss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "model_calls": 0, "matrix_exponentials": 0, "optimizer_steps": 0,
        "numerical_execution_allowed": False, "original_sparse_bitwise_gate": "RED_UNCHANGED",
        "authentic_receipts_generated": 0, "full_roster_qualification": False, "all_closed": False,
    }


if __name__ == "__main__":
    print(json.dumps(run(), allow_nan=False, sort_keys=True, separators=(",", ":")))
