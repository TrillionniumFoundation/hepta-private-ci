"""Fixed AOT CPU computation and typed DENY_ALL execution proposal.

Only an independently trusted OS execution owner may ever perform side effects.
This module intentionally does not expose any side effect or executable writer.
"""

from __future__ import annotations
import ctypes
from dataclasses import dataclass
from pathlib import Path
import subprocess
import stat
import time
from fabric import Denied, digest, q24_dot, sha


REVIEWED_SOURCE_SHA256 = "83337012fc1f8efab4dc6cbdb4fa5fedfc6f10774e3acb2b4bbaa189a483bb30"


@dataclass(frozen=True)
class CellProgram:
    source_digest: str
    model_digest: str
    generation: int
    opcode: str
    requested_effect: bool = False

    def validate(self) -> None:
        digest(self.source_digest)
        digest(self.model_digest)
        if self.generation <= 0 or self.opcode != "PURE_Q24_DOT16" or self.requested_effect:
            raise Denied("unsupported opcode or unapproved external effect")


@dataclass(frozen=True)
class NativeObservation:
    numeric_result: int
    input_digest: str
    program_digest: str
    authority: str = "DENY_ALL"


def compile_reviewed_source(source: Path, output: Path) -> dict[str, object]:
    """Compile only the exact bundled, reviewable C source; never generated user code."""
    canonical = Path(__file__).with_name("q24_native.c")
    if source.is_symlink() or source.resolve(strict=True) != canonical.resolve(strict=True):
        raise Denied("unregistered compiler source")
    if sha(source.read_bytes()) != REVIEWED_SOURCE_SHA256:
        raise Denied("source bytes no longer match reviewed AOT kernel")
    if output.is_symlink() or not output.parent.exists() or output.exists():
        raise Denied("output must be new and non-symlinked")
    if stat.S_IMODE(output.parent.stat().st_mode) & 0o077:
        raise Denied("native output directory must be private")
    t0 = time.perf_counter_ns()
    subprocess.run(["gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-fPIC",
                    "-shared", str(source), "-o", str(output)], check=True, timeout=30)
    compile_ns = time.perf_counter_ns() - t0
    output.chmod(0o500)
    return {"source_sha256": sha(source.read_bytes()),
            "binary_sha256": sha(output.read_bytes()),
            "compile_ns": compile_ns, "kind": "reviewed_aot_cpu_only"}


class NativeMotorShadow:
    def __init__(self, lib_path: Path, expected_binary_sha256: str):
        if not lib_path.is_file() or lib_path.is_symlink() or sha(lib_path.read_bytes()) != digest(expected_binary_sha256):
            raise Denied("native library not verified")
        self._lib = ctypes.CDLL(str(lib_path))
        self._func = self._lib.hepta_q24_dot16
        self._func.argtypes = [ctypes.POINTER(ctypes.c_int32), ctypes.POINTER(ctypes.c_int32),
                               ctypes.c_uint32, ctypes.POINTER(ctypes.c_int64)]
        self._func.restype = ctypes.c_int

    def run(self, program: CellProgram, features: tuple[int, ...],
            weights: tuple[int, ...]) -> NativeObservation:
        program.validate()
        expected = q24_dot(features, weights)  # independent pure reference, no effect
        n = len(features)
        f_array = (ctypes.c_int32 * n)(*features)
        w_array = (ctypes.c_int32 * n)(*weights)
        result = ctypes.c_int64()
        if self._func(f_array, w_array, n, ctypes.byref(result)) != 0 or result.value != expected:
            raise Denied("native numerical mismatch")
        raw = b"".join(v.to_bytes(4, "big", signed=True) for v in features + weights)
        lineage = (program.source_digest + program.model_digest + str(program.generation) + program.opcode).encode()
        return NativeObservation(result.value, sha(raw), sha(lineage))
