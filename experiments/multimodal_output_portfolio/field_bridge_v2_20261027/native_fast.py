"""In-process, bounded, target-free transport for the unchanged native kernel.

NativeFastBridge.tick_pair is receipt-compatible with V1. native_features_fast
also offers a compact path with the same integer state, optional complete JSON
receipts, and separate timings. Neither interface accepts labels or evaluators.
"""

from contextlib import nullcontext
import ctypes as ct
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from ..field_bridge_20261027.controls import _observations

Q24 = 1 << 24
SOURCE_PIN = "63f198ad85cfa2aa579032256355f446cfe793a0"
DIGEST_NAMES = ("checkpoint_before", "checkpoint_after", "temporal_digest", "activation_digest",
                "eligibility_digest", "config_digest", "input_digest")


class Request(ct.Structure):
    _fields_ = [("case", ct.c_uint8 * 256), ("readback", ct.c_uint8 * 32),
                ("first", ct.c_int64 * 8), ("second", ct.c_int64 * 8),
                ("case_len", ct.c_uint32), ("feature_count", ct.c_uint32),
                ("next_present", ct.c_uint32), ("reset", ct.c_uint32)]


class TickOutput(ct.Structure):
    _fields_ = [(name, ct.c_int64 * 20) for name in ("drive", "activation", "eligibility", "threshold")]
    _fields_ += [("digests", (ct.c_uint8 * 32) * 7), ("native_ns", ct.c_uint64),
                 ("sequence", ct.c_uint64), ("bounded_bytes", ct.c_uint64),
                 ("active_fraction_ppm", ct.c_uint32), ("projection_count", ct.c_uint32),
                 ("requires_calibration", ct.c_uint32), ("grants_any", ct.c_uint32)]


class Response(ct.Structure):
    _fields_ = [("ticks", TickOutput * 2), ("ffi_run_ns", ct.c_uint64)]


def prepare_request(*, case, readback_digest, features_q24, next_features_q24=None,
                    reset_before_readout=False):
    """Validate Python values before constructing fixed-width ABI buffers."""
    if not isinstance(case, str) or not 1 <= len(case.encode("utf-8")) <= 256:
        raise ValueError("Case must contain 1..256 UTF-8 bytes")
    features = list(features_q24)
    if not 1 <= len(features) <= 8 or any(type(v) is not int or not -Q24 <= v <= Q24 for v in features):
        raise ValueError("Features must contain 1..8 integer Q24 values in [-1,1]")
    if (not isinstance(readback_digest, str) or len(readback_digest) != 64
            or any(c not in "0123456789abcdef" for c in readback_digest)):
        raise ValueError("Public digest must be exactly 64 lowercase hexadecimal characters")
    if type(reset_before_readout) is not bool:
        raise ValueError("Reset must be explicitly boolean")
    second = [] if next_features_q24 is None else list(next_features_q24)
    if next_features_q24 is not None and (len(second) != len(features) or any(
            type(v) is not int or not -Q24 <= v <= Q24 for v in second)):
        raise ValueError("Next public observation must match the first bounded feature shape")
    request = Request()
    encoded = case.encode("utf-8")
    request.case[:len(encoded)] = encoded
    request.readback[:] = bytes.fromhex(readback_digest)
    request.first[:len(features)] = features
    request.second[:len(second)] = second
    request.case_len, request.feature_count = len(encoded), len(features)
    request.next_present, request.reset = int(next_features_q24 is not None), int(reset_before_readout)
    return request


class NativeFastBridge:
    def __init__(self, binary, expected_sha256=None):
        self.binary = Path(binary).resolve()
        with self.binary.open("rb") as source:
            self.binary_sha256 = hashlib.file_digest(source, "sha256").hexdigest()
        if expected_sha256 is not None and self.binary_sha256 != expected_sha256:
            raise ValueError("Native library hash differs from its build receipt")
        self.library = ct.CDLL(str(self.binary))
        for name, restype in (("hepta_field_abi_version", ct.c_uint32),
                              ("hepta_field_request_size", ct.c_size_t),
                              ("hepta_field_response_size", ct.c_size_t)):
            function = getattr(self.library, name)
            function.argtypes, function.restype = [], restype
        if (self.library.hepta_field_abi_version() != 2
                or self.library.hepta_field_request_size() != ct.sizeof(Request)
                or self.library.hepta_field_response_size() != ct.sizeof(Response)):
            raise ValueError("Native ABI version or struct layout mismatch")
        self.function = self.library.hepta_field_tick_pair
        self.function.argtypes, self.function.restype = [ct.POINTER(Request), ct.POINTER(Response)], ct.c_int
        self.request_count = 0

    def execute(self, request):
        """Execute a validated/prepared ABI request; the native side validates again."""
        if not isinstance(request, Request):
            raise TypeError("Expected a bounded Request ABI buffer")
        output = Response()
        started = time.perf_counter_ns()
        status = self.function(ct.byref(request), ct.byref(output))
        elapsed = time.perf_counter_ns() - started
        if status:
            raise ValueError(f"Native bounded request failed with status {status}")
        if any(tick.grants_any != 0 or tick.requires_calibration != 1 for tick in output.ticks):
            raise RuntimeError("Native receipt changed the original authority posture")
        self.request_count += 1
        return output, elapsed

    def receipt(self, request, output, elapsed):
        ticks = []
        for stage, tick in enumerate(output.ticks):
            row = dict(stage=stage, sequence=int(tick.sequence), logical_clock_micros=stage + 1,
                       fresh_public_observation=stage == 0 or bool(request.next_present),
                       drive_q24=list(tick.drive), activation_q24=list(tick.activation),
                       eligibility_q24=list(tick.eligibility), threshold_q24=list(tick.threshold),
                       native_ns=int(tick.native_ns), active_fraction_ppm=int(tick.active_fraction_ppm),
                       projection_count=int(tick.projection_count),
                       checkpoint_bounded_bytes=int(tick.bounded_bytes), requires_calibration=True,
                       authority="DENY_ALL", native_owner_integration=False)
            row.update({name: bytes(tick.digests[index]).hex() for index, name in enumerate(DIGEST_NAMES)})
            ticks.append(row)
        return dict(schema="hepta.parameter-field-bridge.native.v1",
                    case=bytes(request.case[:request.case_len]).decode("utf-8"), source_pin=SOURCE_PIN,
                    feature_count=int(request.feature_count), next_public_observation_provided=bool(request.next_present),
                    ticks=ticks, checkpoint_reset_intervention=bool(request.reset), original_sparse_tick_calls=2,
                    native_owner_integration=False, binary_sha256=self.binary_sha256,
                    bridge_roundtrip_ns=elapsed, ffi_run_ns=int(output.ffi_run_ns), transport="in_process_c_abi_v2")

    def tick_pair(self, **values):
        request = prepare_request(**values)
        output, elapsed = self.execute(request)
        return self.receipt(request, output, elapsed)

    def tick_pairs(self, requests):
        return [self.tick_pair(**values) for values in requests]

    def close(self):
        """No child process, retained native checkpoint, or open file to close."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


def native_features_fast(bridge, x0, x1, case_prefix, reset=False, receipt_path=None):
    """Return exact V1 N x 40 state via compact ABI, optionally preserving receipts.

    The measurement boundary includes public input validation, hashing, encoding,
    original kernel execution, and state conversion. Full receipts, JSON, and
    buffered file writes are included when receipt_path is supplied. No fsync is
    claimed. Logging can be omitted only if the caller retains equivalent inputs
    and decision provenance elsewhere; replay is never inferred from timings.
    """
    started, cpu_started = time.perf_counter_ns(), time.process_time_ns()
    x0, x1 = _observations(x0, x1)
    if not isinstance(case_prefix, str) or not case_prefix or len(case_prefix.encode()) > 230:
        raise ValueError("Case prefix must contain 1..230 UTF-8 bytes")
    if type(reset) is not bool:
        raise ValueError("Reset must be explicitly boolean")
    path = Path(receipt_path) if receipt_path is not None else None
    summary_path = path.with_name(path.name + ".summary.json") if path is not None else None
    if path is not None:
        if path.exists() or summary_path.exists():
            raise ValueError("Refusing to replace existing native feature evidence")
        path.parent.mkdir(parents=True, exist_ok=True)
    output_features = np.empty((len(x0), 40), dtype=np.float64)
    native_ns = ffi_ns = abi_ns = prepare_ns = decode_ns = serialize_ns = io_ns = 0
    with path.open("x", encoding="utf-8") if path is not None else nullcontext() as log:
        for index, (first, second) in enumerate(zip(x0, x1, strict=True)):
            step_started = time.perf_counter_ns()
            public_digest = hashlib.sha256(np.stack((first, second)).astype("<f8", copy=False).tobytes()).hexdigest()
            values = dict(case=f"{case_prefix}:{index:08d}", readback_digest=public_digest,
                          features_q24=np.rint((2 * first - 1) * Q24).astype(np.int64).tolist(),
                          next_features_q24=np.rint((2 * second - 1) * Q24).astype(np.int64).tolist(),
                          reset_before_readout=reset)
            request = prepare_request(**values)
            prepare_ns += time.perf_counter_ns() - step_started
            result, elapsed = bridge.execute(request)
            abi_ns += elapsed
            ffi_ns += int(result.ffi_run_ns)
            native_ns += sum(tick.native_ns for tick in result.ticks)
            step_started = time.perf_counter_ns()
            last = result.ticks[1]
            output_features[index, :20] = np.ctypeslib.as_array(last.activation)
            output_features[index, 20:] = np.ctypeslib.as_array(last.eligibility)
            output_features[index] /= Q24
            decode_ns += time.perf_counter_ns() - step_started
            if log is not None:
                step_started = time.perf_counter_ns()
                receipt = bridge.receipt(request, result, elapsed)
                line = json.dumps(dict(schema="hepta.field-bridge.public-feature-receipt.v1",
                                       case_index=index, public_feature_sha256=public_digest,
                                       public_feature_byte_encoding="2x8 little-endian float64 row-major, first then second",
                                       request=values, native=receipt), sort_keys=True, allow_nan=False) + "\n"
                serialize_ns += time.perf_counter_ns() - step_started
                step_started = time.perf_counter_ns()
                log.write(line)
                io_ns += time.perf_counter_ns() - step_started
    summary = dict(schema="hepta.field-bridge-v2.native-feature-batch.v1", rows=len(x0), feature_width=40,
                   original_sparse_tick_calls=2 * len(x0), native_ns=native_ns, ffi_run_ns=ffi_ns,
                   bridge_roundtrip_ns=abi_ns, feature_batch_wall_ns=time.perf_counter_ns() - started,
                   feature_batch_python_cpu_ns=time.process_time_ns() - cpu_started,
                   prepare_ns=prepare_ns, decode_ns=decode_ns, receipt_serialization_ns=serialize_ns,
                   receipt_buffered_write_ns=io_ns, reset_before_readout=reset, target_accesses=0,
                   authority="DENY_ALL", native_owner_integration=False, transport="in_process_c_abi_v2",
                   complete_receipts_written=path is not None,
                   feature_matrix_sha256=hashlib.sha256(output_features.astype("<f8", copy=False).tobytes()).hexdigest())
    bridge.last_feature_batch = summary
    if summary_path is not None:
        with summary_path.open("x", encoding="utf-8") as destination:
            json.dump(summary, destination, indent=2, sort_keys=True, allow_nan=False)
            destination.write("\n")
    return output_features
