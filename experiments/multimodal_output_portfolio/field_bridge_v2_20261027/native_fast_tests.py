"""Contract tests against the actual V1 executable, without model/task labels."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import ctypes as ct
import hashlib
import json
from pathlib import Path
import tempfile
import time

import numpy as np

from ..field_bridge_20261027.controls import choose, native_features
from ..field_bridge_20261027.native_bridge import NativeBridge
from .native_fast import NativeFastBridge, Q24, Request, Response, SOURCE_PIN, native_features_fast, prepare_request


def canonical(receipt):
    value = json.loads(json.dumps(receipt))
    for name in ("bridge_roundtrip_ns", "binary_sha256", "ffi_run_ns", "transport"):
        value.pop(name, None)
    for tick in value["ticks"]:
        tick.pop("native_ns")
    return value


def requests(seed=271028, count=512):
    rng = np.random.default_rng(seed)
    answer = []
    for index in range(count):
        width = index % 8 + 1
        first = rng.integers(-Q24, Q24 + 1, size=width).tolist()
        second = rng.integers(-Q24, Q24 + 1, size=width).tolist()
        if index % 13 == 0:
            first = [0] * width
        if index % 17 == 0:
            first = [Q24 if i % 2 else -Q24 for i in range(width)]
        if index % 23 == 0:
            first = [Q24 // 2] * width  # Equal activations exercise tie ordering.
        case = f"ffi-contract-λ-中文-{index}"
        if index == count - 1:
            case = "x" * 256
        answer.append(dict(case=case, readback_digest=hashlib.sha256(case.encode()).hexdigest(),
                           features_q24=first, next_features_q24=None if index % 5 == 0 else second,
                           reset_before_readout=index % 3 == 0))
    return answer


def assert_rejected(callback):
    try:
        callback()
    except (ValueError, TypeError):
        return
    raise AssertionError("Malformed input was accepted")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffi", type=Path, required=True)
    parser.add_argument("--legacy", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("Refusing to overwrite a test receipt")
    started = time.perf_counter_ns()
    fast = NativeFastBridge(args.ffi)
    cases = requests()
    reference = []
    with NativeBridge(args.legacy) as old:
        for request in cases:
            actual, expected = fast.tick_pair(**request), old.tick_pair(**request)
            assert canonical(actual) == canonical(expected)
            reference.append(canonical(expected))
        with ThreadPoolExecutor(max_workers=8) as pool:
            concurrent = list(pool.map(lambda row: canonical(fast.tick_pair(**row)), cases[:64]))
        assert concurrent == reference[:64]
        for row, expected in zip(cases[64:96], reference[64:96], strict=True):
            assert canonical(fast.tick_pair(**row)) == expected

        template = dict(cases[1])
        invalid = [dict(case=""), dict(case="x" * 257), dict(case=2),
                   dict(readback_digest="G" * 64), dict(readback_digest="A" * 64),
                   dict(readback_digest="0" * 63), dict(readback_digest=" " * 64),
                   dict(features_q24=[]), dict(features_q24=[0] * 9),
                   dict(features_q24=[True]), dict(features_q24=[0.5]),
                   dict(features_q24=[float("nan")]), dict(features_q24=[Q24 + 1]),
                   dict(features_q24=[-Q24 - 1]), dict(reset_before_readout=1),
                   dict(next_features_q24=[0]), dict(next_features_q24=[0, Q24 + 1])]
        for replacement in invalid:
            value = template | replacement
            assert_rejected(lambda row=value: fast.tick_pair(**row))
        assert_rejected(lambda: NativeFastBridge(args.ffi, expected_sha256="0" * 64))

        # Exercise native validation directly; output remains byte-for-byte intact.
        native_invalid = []
        for name, value in (("case_len", 0), ("case_len", 257), ("feature_count", 0),
                            ("feature_count", 9), ("next_present", 2), ("reset", 2)):
            request = prepare_request(**template)
            setattr(request, name, value)
            native_invalid.append(request)
        request = prepare_request(**template)
        request.case[0] = 0xff
        native_invalid.append(request)
        for field in ("first", "second"):
            request = prepare_request(**template)
            getattr(request, field)[0] = Q24 + 1
            native_invalid.append(request)
        for request in native_invalid:
            output = Response()
            ct.memset(ct.byref(output), 0xA5, ct.sizeof(output))
            before = bytes(output)
            assert fast.function(ct.byref(request), ct.byref(output)) == 2
            assert bytes(output) == before
        output = Response()
        assert fast.function(None, ct.byref(output)) == 1
        assert fast.function(ct.byref(prepare_request(**template)), None) == 1
        unaligned = ct.create_string_buffer(ct.sizeof(Request) + 8)
        address = ct.addressof(unaligned)
        offset = 1 if address % ct.alignment(Request) == 0 else 0
        assert fast.function(ct.cast(address + offset, ct.POINTER(Request)), ct.byref(output)) == 1
        assert canonical(fast.tick_pair(**template)) == reference[1]  # Recover after all rejections.

        rng = np.random.default_rng(991)
        x0, x1 = rng.uniform(0, 1, (2, 40, 8))
        matrix_hashes = []
        with tempfile.TemporaryDirectory(prefix="hepta-native-ffi-contract-") as directory:
            for reset in (False, True):
                a = Path(directory) / f"old-{reset}.jsonl"
                b = Path(directory) / f"new-{reset}.jsonl"
                expected = native_features(old, x0, x1, "matched-feature", reset=reset, receipt_path=a)
                actual = native_features_fast(fast, x0, x1, "matched-feature", reset=reset, receipt_path=b)
                assert np.array_equal(actual, expected)
                left = [json.loads(line) for line in a.read_text().splitlines()]
                right = [json.loads(line) for line in b.read_text().splitlines()]
                for before, after in zip(left, right, strict=True):
                    before["native"], after["native"] = canonical(before["native"]), canonical(after["native"])
                    assert before == after
                compact = native_features_fast(fast, x0, x1, "matched-feature", reset=reset)
                assert np.array_equal(compact, expected)
                model = dict(schema="hepta.field-bridge.ridge-readout.v1",
                             coefficient=rng.normal(size=(41, 5)).tolist(),
                             normalizer=dict(mean=rng.normal(size=40).tolist(), scale=np.ones(40).tolist()))
                assert np.array_equal(choose(model, actual), choose(model, expected))
                assert_rejected(lambda: native_features_fast(fast, x0, x1, "matched-feature", receipt_path=b))
                matrix_hashes.append(hashlib.sha256(actual.astype("<f8").tobytes()).hexdigest())
    report = dict(schema="hepta.field-bridge-v2.native-ffi-contract.v1", passed=True,
                  full_receipt_parity_cases=len(cases), original_ticks_compared=2 * len(cases),
                  concurrent_parity_cases=64, repeat_parity_cases=32, python_invalid_cases=len(invalid) + 1,
                  native_invalid_cases=len(native_invalid) + 3, native_invalid_output_unchanged=True,
                  recovery_after_invalid=True, feature_receipt_pairs=80, feature_matrix_parity=True,
                  compact_full_receipt_parity=True, downstream_frozen_action_parity=True,
                  feature_sha256=matrix_hashes, request_bytes=ct.sizeof(Request), response_bytes=ct.sizeof(Response),
                  source_commit=SOURCE_PIN,
                  library_sha256=fast.binary_sha256, legacy_binary_sha256=old.binary_sha256,
                  authority="DENY_ALL", requires_calibration=True, native_owner_integration=False,
                  scientific_effect_estimated=False, wall_ns=time.perf_counter_ns() - started)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
