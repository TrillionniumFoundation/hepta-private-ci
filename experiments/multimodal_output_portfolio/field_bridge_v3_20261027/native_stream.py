"""Six-tick bounded research sessions around the exact original Hepta kernel.

No labels, model execution or product authority enter this interface. The C ABI
owns complete original checkpoints and publishes a new state only on success.
"""

import argparse
import ctypes as ct
import hashlib
import json
from pathlib import Path
import subprocess
import threading
import time

import numpy as np

Q24 = 1 << 24
SOURCE_PIN = "63f198ad85cfa2aa579032256355f446cfe793a0"
DIGEST_NAMES = ("checkpoint_before", "checkpoint_after", "temporal_digest", "activation_digest",
                "eligibility_digest", "config_digest", "input_digest")


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class OpenRequest(ct.Structure):
    _fields_ = [("case", ct.c_uint8*256), ("case_len", ct.c_uint32)]


class TickRequest(ct.Structure):
    _fields_ = [("handle", ct.c_uint64), ("sequence", ct.c_uint64),
                ("logical_clock_micros", ct.c_uint64), ("readback", ct.c_uint8*32),
                ("features", ct.c_int64*8), ("feature_count", ct.c_uint32)]


class TickOutput(ct.Structure):
    _fields_ = [(name, ct.c_int64*20) for name in ("drive", "activation", "eligibility", "threshold")]
    _fields_ += [("digests", (ct.c_uint8*32)*7), ("native_ns", ct.c_uint64),
                 ("sequence", ct.c_uint64), ("logical_clock_micros", ct.c_uint64),
                 ("bounded_bytes", ct.c_uint64), ("active_fraction_ppm", ct.c_uint32),
                 ("projection_count", ct.c_uint32), ("requires_calibration", ct.c_uint32),
                 ("grants_any", ct.c_uint32)]


def _check(status):
    if status:
        raise ValueError(f"Bounded native session request failed with status {status}")


class NativeSession:
    def __init__(self, bridge, handle, case):
        self.bridge, self.handle, self.case = bridge, int(handle), case
        self.clock = self.sequence = 0
        self.closed = False
        self.history_bytes = b""
        self.controller_binding = None
        self.selected_action = None
        self.checkpoint_sha256 = "0"*64
        self._lock = threading.RLock()

    def _live(self):
        if self.closed or self.bridge.closed:
            raise ValueError("Native session is closed")

    def tick(self, features_q24, *, readback_digest):
        values = list(features_q24)
        if (not 1 <= len(values) <= 8 or any(type(v) is not int or not -Q24 <= v <= Q24 for v in values)
                or not isinstance(readback_digest, str) or len(readback_digest) != 64
                or any(v not in "0123456789abcdef" for v in readback_digest)):
            raise ValueError("Expected 1..8 bounded signed Q24 integers and a lowercase SHA256")
        with self._lock:
            self._live()
            request = TickRequest(handle=self.handle, sequence=self.sequence+1,
                                  logical_clock_micros=self.clock+1, feature_count=len(values))
            request.features[:len(values)] = values
            request.readback[:] = bytes.fromhex(readback_digest)
            result = TickOutput()
            started = time.perf_counter_ns()
            _check(self.bridge.library.hepta_stream_tick(ct.byref(request), ct.byref(result)))
            roundtrip = time.perf_counter_ns()-started
            if result.grants_any != 0 or result.requires_calibration != 1:
                raise RuntimeError("Native stream authority differs from DENY_ALL")
            self.clock, self.sequence = int(result.logical_clock_micros), int(result.sequence)
            self.checkpoint_sha256 = bytes(result.digests[1]).hex()
            with self.bridge._lock:
                self.bridge.tick_count += 1
                self.bridge.native_ns += int(result.native_ns)
                self.bridge.roundtrip_ns += roundtrip
            receipt = {"schema": "hepta.field-bridge-v3.native-stream-tick.v1", "case": self.case,
                "source_pin": SOURCE_PIN, "binary_sha256": self.bridge.binary_sha256,
                "sequence": self.sequence, "logical_clock_micros": self.clock,
                "feature_count": len(values), "features_q24": values, "readback_digest": readback_digest,
                "drive_q24": list(result.drive), "activation_q24": list(result.activation),
                "eligibility_q24": list(result.eligibility), "threshold_q24": list(result.threshold),
                "checkpoint_bounded_bytes": int(result.bounded_bytes),
                "active_fraction_ppm": int(result.active_fraction_ppm),
                "projection_count": int(result.projection_count), "native_ns": int(result.native_ns),
                "bridge_roundtrip_ns": roundtrip, "requires_calibration": True,
                "authority": "DENY_ALL", "native_owner_integration": False}
            receipt.update({name: bytes(result.digests[i]).hex() for i, name in enumerate(DIGEST_NAMES)})
            return np.r_[list(result.activation), list(result.eligibility)].astype(np.float64)/Q24, receipt

    def fork(self):
        with self._lock:
            self._live()
            output = ct.c_uint64()
            _check(self.bridge.library.hepta_stream_fork(self.handle, ct.byref(output)))
            child = self.bridge._register(output.value, self.case)
            child.clock, child.sequence = self.clock, self.sequence
            child.history_bytes = self.history_bytes
            child.controller_binding = self.controller_binding
            child.selected_action = self.selected_action
            child.checkpoint_sha256 = self.checkpoint_sha256
            return child

    def reset(self):
        with self._lock:
            self._live()
            _check(self.bridge.library.hepta_stream_reset(self.handle))
            self.sequence, self.checkpoint_sha256 = 0, "0"*64
            # Public history and the six-tick episode clock are not erased.

    def close(self):
        with self._lock:
            if not self.closed:
                _check(self.bridge.library.hepta_stream_close(self.handle))
                self.closed = True
                with self.bridge._lock:
                    self.bridge._sessions.pop(self.handle, None)

    def __enter__(self):
        self._live()
        return self

    def __exit__(self, *_):
        self.close()


class NativeStreamBridge:
    def __init__(self, binary, expected_sha256=None):
        self.binary = Path(binary).resolve()
        self.binary_sha256 = file_sha(self.binary)
        if expected_sha256 is not None and self.binary_sha256 != expected_sha256:
            raise ValueError("Native stream library differs from the registered binary")
        self.library = ct.CDLL(str(self.binary))
        for name, restype in (("abi_version", ct.c_uint32), ("open_size", ct.c_size_t),
                              ("request_size", ct.c_size_t), ("response_size", ct.c_size_t),
                              ("live_sessions", ct.c_size_t)):
            function = getattr(self.library, "hepta_stream_"+name)
            function.argtypes, function.restype = [], restype
        if (self.library.hepta_stream_abi_version() != 3 or self.library.hepta_stream_open_size() != ct.sizeof(OpenRequest)
                or self.library.hepta_stream_request_size() != ct.sizeof(TickRequest)
                or self.library.hepta_stream_response_size() != ct.sizeof(TickOutput)):
            raise ValueError("Native stream ABI layout/version mismatch")
        for name, args in (("open", [ct.POINTER(OpenRequest), ct.POINTER(ct.c_uint64)]),
                           ("fork", [ct.c_uint64, ct.POINTER(ct.c_uint64)]),
                           ("tick", [ct.POINTER(TickRequest), ct.POINTER(TickOutput)]),
                           ("reset", [ct.c_uint64]), ("close", [ct.c_uint64])):
            function = getattr(self.library, "hepta_stream_"+name)
            function.argtypes, function.restype = args, ct.c_int
        self._sessions, self._lock = {}, threading.RLock()
        self.tick_count = self.native_ns = self.roundtrip_ns = 0
        self.closed = False

    def _register(self, handle, case):
        session = NativeSession(self, handle, case)
        with self._lock:
            self._sessions[handle] = session
        return session

    def open(self, case):
        if self.closed or not isinstance(case, str) or not 1 <= len(case.encode()) <= 256:
            raise ValueError("Open bridge and 1..256 UTF-8 case bytes are required")
        encoded, request, output = case.encode(), OpenRequest(), ct.c_uint64()
        request.case[:len(encoded)], request.case_len = encoded, len(encoded)
        _check(self.library.hepta_stream_open(ct.byref(request), ct.byref(output)))
        return self._register(output.value, case)

    def close(self):
        for session in list(self._sessions.values()):
            session.close()
        self.closed = True

    def __enter__(self):
        if self.closed:
            raise ValueError("Native bridge is closed")
        return self

    def __exit__(self, *_):
        self.close()


def build(binary, inherited_receipt):
    """Compile only this new wrapper using independently hash-checked old rlibs."""
    binary, inherited_receipt = Path(binary).resolve(), Path(inherited_receipt).resolve()
    if binary.exists():
        raise ValueError("Refusing to overwrite a compiled native stream")
    receipt = json.loads(inherited_receipt.read_text())
    source = Path(__file__).with_suffix(".rs")
    command = list(receipt["command"])
    compiler = Path(command[0])
    if file_sha(compiler) != receipt["compiler_runtime_inventory"]["bin/rustc"]:
        raise ValueError("Inherited compiler identity differs")
    dependencies = Path(next(v.removeprefix("dependency=") for v in command if v.startswith("dependency=")))
    for name, expected in receipt["linked_rlib_sha256"].items():
        if file_sha(dependencies/name) != expected:
            raise ValueError("An inherited native dependency changed")
    command[command.index("--crate-name=hepta_field_bridge_ffi")] = "--crate-name=hepta_field_bridge_stream"
    command[-3:] = [str(source), "-o", str(binary)]
    binary.parent.mkdir(parents=True, exist_ok=True)
    dependency_receipt = binary.parent/"DEPENDENCY_BUILD_RECEIPT.json"
    if dependency_receipt.exists():
        raise ValueError("Refusing to replace dependency build evidence")
    dependency_receipt.write_bytes(inherited_receipt.read_bytes())
    before = time.perf_counter_ns()
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    output = {"schema": "hepta.field-bridge-v3.native-stream-build.v1", "command": command,
        "compiler": subprocess.check_output([str(compiler), "--version"], text=True).strip(),
        "source_sha256": file_sha(source), "python_source_sha256": file_sha(__file__),
        "inherited_build_receipt_sha256": file_sha(inherited_receipt),
        "inherited_build_receipt_file": dependency_receipt.name,
        "original_source_commit": SOURCE_PIN, "original_sparse_sha256": receipt["original_sparse_sha256"],
        "linked_rlib_sha256": receipt["linked_rlib_sha256"], "compiler_sha256": file_sha(compiler),
        "binary": str(binary), "binary_sha256": file_sha(binary), "binary_bytes": binary.stat().st_size,
        "build_wall_ns": time.perf_counter_ns()-before,
        "build_log_sha256": hashlib.sha256((result.stdout+result.stderr).encode()).hexdigest(),
        "kernel_and_configuration_unchanged": True, "authority": "DENY_ALL",
        "native_owner_integration": False, "requires_calibration": True,
        "max_live_sessions": 4096, "max_episode_ticks": 6}
    with (binary.parent/"BUILD_RECEIPT.json").open("x") as stream:
        json.dump(output, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--inherited-receipt", type=Path, required=True)
    args = parser.parse_args()
    built = build(args.build, args.inherited_receipt)
    print(json.dumps({key: built[key] for key in ("binary", "binary_sha256", "binary_bytes", "build_wall_ns")}))
