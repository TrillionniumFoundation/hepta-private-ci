"""Synthetic native session contracts; no task data or generator inference."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import ctypes as ct
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from ..field_bridge_v2_20261027.native_fast import NativeFastBridge
from .native_stream import NativeStreamBridge, OpenRequest, TickOutput, TickRequest, Q24, file_sha

STATE_FIELDS = ("drive_q24", "activation_q24", "eligibility_q24", "threshold_q24",
    "checkpoint_before", "checkpoint_after", "temporal_digest", "activation_digest",
    "eligibility_digest", "config_digest", "input_digest", "sequence", "logical_clock_micros",
    "checkpoint_bounded_bytes", "active_fraction_ppm", "projection_count", "requires_calibration",
    "authority", "native_owner_integration")


def stable(receipt):
    return {key: receipt[key] for key in STATE_FIELDS}


def expect_error(call):
    try:
        call()
    except (ValueError, TypeError):
        return
    raise AssertionError("Expected bounded input/state rejection")


def run(library, legacy_library):
    started = time.perf_counter_ns()
    rng = np.random.default_rng(271033)
    parity, chains, invalid = 0, 0, 0
    ledger = hashlib.sha256()
    with NativeStreamBridge(library) as bridge, NativeFastBridge(legacy_library) as legacy:
        for index in range(96):
            width = index % 8+1
            first, second = rng.integers(-Q24, Q24+1, size=(2, width)).tolist()
            if index < 8:
                first = ([0, Q24, -Q24][index % 3:]+[0]*8)[:width]
            digest = hashlib.sha256(f"public:{index}".encode()).hexdigest() if index else "0"*64
            for reset in (False, True):
                case = f"合成-parity-{index}-{int(reset)}"
                old = legacy.tick_pair(case=case, readback_digest=digest, features_q24=first,
                    next_features_q24=second, reset_before_readout=reset)
                with bridge.open(case) as session:
                    _, a = session.tick(first, readback_digest=digest)
                    if reset:
                        session.reset()
                    _, b = session.tick(second, readback_digest=digest)
                assert [stable(a), stable(b)] == [stable(row) for row in old["ticks"]]
                ledger.update(json.dumps([stable(a), stable(b)], sort_keys=True).encode())
                parity += 1

        recurrence_differences = 0
        for index in range(48):
            values = rng.integers(-Q24, Q24+1, size=(6, 8)).tolist()
            digests = [hashlib.sha256(f"event:{index}:{j}".encode()).hexdigest() for j in range(6)]
            case = f"six-tick-{index}"
            with bridge.open(case) as session, bridge.open(case) as replay, bridge.open(case) as reset:
                normal, reproduced, erased = [], [], []
                for j in range(2):
                    normal.append(session.tick(values[j], readback_digest=digests[j])[1])
                with session.fork() as forked, session.fork() as changed:
                    for j in range(2, 6):
                        normal.append(session.tick(values[j], readback_digest=digests[j])[1])
                        receipt = forked.tick(values[j], readback_digest=digests[j])[1]
                        assert stable(receipt) == stable(normal[-1])
                    alternate = [-v for v in values[2]]
                    changed_receipt = changed.tick(alternate, readback_digest=digests[2])[1]
                    assert changed_receipt["checkpoint_before"] == normal[2]["checkpoint_before"]
                    assert changed_receipt["checkpoint_after"] != normal[2]["checkpoint_after"]
                for j in range(6):
                    reproduced.append(replay.tick(values[j], readback_digest=digests[j])[1])
                    if j in (2, 4):
                        reset.reset()
                    erased.append(reset.tick(values[j], readback_digest=digests[j])[1])
                assert list(map(stable, normal)) == list(map(stable, reproduced))
                for round_index in range(3):
                    pair = legacy.tick_pair(case=case, readback_digest=digests[2*round_index],
                        features_q24=values[2*round_index], next_features_q24=values[2*round_index+1])
                    for field in ("drive_q24", "activation_q24", "eligibility_q24", "threshold_q24", "temporal_digest"):
                        assert erased[2*round_index+1][field] == pair["ticks"][1][field]
                recurrence_differences += (normal[-1]["activation_q24"] != erased[-1]["activation_q24"]
                                          or normal[-1]["eligibility_q24"] != erased[-1]["eligibility_q24"])
                assert session.clock == 6
                session.reset()
                expect_error(lambda: session.tick(values[0], readback_digest=digests[0]))
                assert session.clock == 6 and session.sequence == 0
                ledger.update(json.dumps(list(map(stable, normal)), sort_keys=True).encode())
                chains += 1
        assert recurrence_differences > 0

        with bridge.open("atomic-invalid") as session, bridge.open("atomic-invalid") as reference:
            digest = hashlib.sha256(b"atomic").hexdigest()
            variants = (("feature_count", 0, 2), ("feature_count", 9, 2), ("sequence", 0, 8),
                        ("sequence", 2, 8), ("logical_clock_micros", 0, 8),
                        ("logical_clock_micros", 2, 8), ("handle", 2**64-1, 6))
            for name, value, status in variants:
                request = TickRequest(handle=session.handle, sequence=1, logical_clock_micros=1, feature_count=8)
                request.readback[:] = bytes.fromhex(digest)
                setattr(request, name, value)
                output = TickOutput()
                ct.memset(ct.byref(output), 0xA5, ct.sizeof(output))
                before = bytes(output)
                assert bridge.library.hepta_stream_tick(ct.byref(request), ct.byref(output)) == status
                assert bytes(output) == before
                invalid += 1
            request = TickRequest(handle=session.handle, sequence=1, logical_clock_micros=1, feature_count=8)
            request.features[0] = Q24+1
            assert bridge.library.hepta_stream_tick(ct.byref(request), ct.byref(output)) == 2
            assert bytes(output) == before
            assert bridge.library.hepta_stream_tick(None, ct.byref(output)) == 1
            assert bytes(output) == before
            invalid += 2
            a = session.tick([Q24]*8, readback_digest=digest)[1]
            b = reference.tick([Q24]*8, readback_digest=digest)[1]
            assert stable(a) == stable(b)
        for case in ("", "a"*257, None):
            expect_error(lambda: bridge.open(case))
            invalid += 1
        request, handle = OpenRequest(case_len=1), ct.c_uint64(123456)
        request.case[0] = 255
        assert bridge.library.hepta_stream_open(ct.byref(request), ct.byref(handle)) == 2
        assert handle.value == 123456
        invalid += 1
        with bridge.open("python-invalid") as session:
            for values in ([], [0]*9, [True], [Q24+1], [1.2]):
                expect_error(lambda: session.tick(values, readback_digest="0"*64))
                invalid += 1
            assert session.clock == 0

        def concurrent(index):
            case = f"concurrent-{index}"
            values = np.random.default_rng(index).integers(-Q24, Q24+1, size=(6, 8)).tolist()
            with bridge.open(case) as session:
                return [stable(session.tick(row, readback_digest=hashlib.sha256(str(j).encode()).hexdigest())[1])
                        for j, row in enumerate(values)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            parallel = list(pool.map(concurrent, range(16)))
        assert parallel == [concurrent(i) for i in range(16)]
        assert bridge.library.hepta_stream_live_sessions() == 0
        live = [bridge.open(f"capacity-{i}") for i in range(4096)]
        try:
            expect_error(lambda: bridge.open("over-capacity"))
            expect_error(live[0].fork)
            assert bridge.library.hepta_stream_live_sessions() == 4096
            stale = live[0].handle
            live[0].close()
            assert bridge.library.hepta_stream_reset(stale) == 6
            with bridge.open("replacement") as replacement:
                assert replacement.handle > live[-1].handle
            invalid += 3
        finally:
            for session in live:
                session.close()
        assert bridge.library.hepta_stream_live_sessions() == 0
        ticks = bridge.tick_count
    return {"schema": "hepta.field-bridge-v3.native-stream-contract.v1", "passed": True,
        "synthetic_only": True, "task_source_labels_accessed": False,
        "literal_legacy_pair_cases": parity, "six_tick_fork_replay_chains": chains,
        "recurrence_difference_cases": recurrence_differences, "concurrent_six_tick_cases": 16,
        "invalid_state_input_guards": invalid, "capacity_sessions_checked": 4096,
        "native_ticks_executed": ticks, "stable_receipts_sha256": ledger.hexdigest(),
        "native_library_sha256": file_sha(library), "legacy_library_sha256": file_sha(legacy_library),
        "test_source_sha256": file_sha(__file__), "stream_python_sha256": file_sha(Path(__file__).with_name("native_stream.py")),
        "stream_rust_sha256": file_sha(Path(__file__).with_name("native_stream.rs")),
        "authority": "DENY_ALL", "requires_calibration": True, "native_owner_integration": False,
        "wall_ns": time.perf_counter_ns()-started}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--legacy-library", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.library, args.legacy_library)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as output:
        json.dump(result, output, indent=2, sort_keys=True)
        output.write("\n")
    print(json.dumps(result, indent=2))
