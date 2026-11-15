"""Independent transport observer for the complete native unified-diff ABI.

No line splitting, Myers, Compact, grouping, or formatting algorithm lives here.
Expected strings and line counts come from the complete original similar crate.
"""
from __future__ import annotations

from collections import Counter
import ctypes
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import struct
from threading import Lock

INVALID, SHORT, INVALID_UTF8 = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD
MAX = (1 << 64) - 1
COMPILER_SHA = "76fe758bc49499046169a5b4798c31d57366344c23530b35bc489e4008639273"
CRATE_ARCHIVE_SHA = "bbbb5d9659141646ae647b42fe094daf6c6192d1620870b449d9557f748b2daa"
HEADER_NAMES = (
    "revision", "output_capacity", "workspace_capacity", "plan_bytes",
    "rendered_bytes", "fragments", "fragment_offset", "literal_offset",
    "literal_bytes", "old_lines", "new_lines", "semantic", "operand_a",
    "operand_b", "policy", "reserved",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def binding(path: Path) -> dict:
    path = Path(path).resolve()
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}


def validate_binding(value: dict) -> Path:
    path = Path(value["path"])
    assert sha256(path) == value["sha256"], ("file hash differs", str(path))
    if "bytes" in value:
        assert path.stat().st_size == value["bytes"], ("file size differs", str(path))
    return path


def words(values) -> bytes:
    return struct.pack(f"<{len(values)}Q", *values)


def descriptor(operation: int, old_len: int, new_len: int, context: int, policy: int) -> bytes:
    return words((operation, old_len, new_len, context, policy, 0, 0, 0))


def changed_word(frame: bytes, index: int, value: int) -> bytes:
    return frame[:8 * index] + words((value,)) + frame[8 * (index + 1):]


def expected_capacities(old_lines: int, new_lines: int) -> tuple[int, int]:
    # Protocol capacity arithmetic, not a diff implementation.
    count = old_lines + new_lines
    return 512 + 352 * count, 1024 + 256 * count


from .original import validate_original_corpus


@dataclass
class Result:
    status: int
    header: dict | None
    rendered: bytes | None
    output: bytes
    request: bytes


class Native:
    def __init__(self, library_path: Path, symbol: str, source_path: Path,
                 artifact_report: Path, contract_path: Path, development: bool = False):
        from .admission import admit, require
        require(not development, "Only genuine complete canonical builds are accepted.")
        self.library_path = Path(library_path).resolve()
        self.source_path = Path(source_path).resolve()
        self.artifact_report = Path(artifact_report).resolve()
        self.contract_path = Path(contract_path).resolve()
        self.symbol, self.development = symbol, False
        self.bindings = admit(self.library_path, symbol, self.source_path,
                              self.artifact_report, self.contract_path) + [binding(Path(__file__))]
        self.admission_scope = (
            "Canonical full native bootstrap, source/contract/lock/driver/helper, actual raw "
            "and namespaced objects, hia.o archive member, library and all three compiler "
            "generations bound before invoking the real namespaced entry."
        )
        self.library = ctypes.CDLL(str(self.library_path))
        self.function = getattr(self.library, symbol)
        self.function.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
        self.function.restype = ctypes.c_uint64
        self.counts = Counter()
        self.lock = Lock()
        self.last_case = None
        self.trace_path = None

    def unchanged(self):
        for item in self.bindings:
            validate_binding(item)
        return True

    def call(self, source: bytes, frame: bytes, output_capacity: int,
             workspace_capacity: int | None = None, expected_status: int = 0,
             guard: int = 17, label: str = "") -> Result:
        if workspace_capacity is None:
            workspace_capacity = len(frame)
        assert 0 <= output_capacity <= 64 * 1024 * 1024
        assert 0 <= workspace_capacity <= 64 * 1024 * 1024
        assert 1 <= guard <= 64
        src = (ctypes.c_ubyte * (len(source) + 2 * guard)).from_buffer_copy(
            b"\xcc" * (len(source) + 2 * guard))
        workspace_extent = max(len(frame), workspace_capacity)
        work = (ctypes.c_ubyte * (workspace_extent + 2 * guard)).from_buffer_copy(
            b"\x5a" * (workspace_extent + 2 * guard))
        out = (ctypes.c_ubyte * (max(128, output_capacity) + 2 * guard)).from_buffer_copy(
            b"\xa5" * (max(128, output_capacity) + 2 * guard))
        src[guard:guard + len(source)] = source
        work[guard:guard + len(frame)] = frame
        before = bytes(src), bytes(work), bytes(out)
        call_info = {
            "label": label, "source_bytes": len(source),
            "source_sha256": hashlib.sha256(source).hexdigest(),
            "frame_hex": frame[:64].hex(), "output_capacity": output_capacity,
            "workspace_capacity": workspace_capacity, "guard": guard,
        }
        with self.lock:
            self.last_case = call_info
            if self.trace_path is not None:
                with Path(self.trace_path).open("a") as stream:
                    stream.write(json.dumps(call_info, sort_keys=True) + "\n")
        status = self.function(ctypes.byref(src, guard), len(source),
                               ctypes.byref(out, guard), output_capacity,
                               ctypes.byref(work, guard), workspace_capacity)
        with self.lock:
            self.counts["native_calls"] += 1
        assert status == expected_status, (label, status, expected_status, call_info)
        assert bytes(src) == before[0], ("source/canary changed", label)
        after_work, after_out = bytes(work), bytes(out)
        if status:
            assert after_work == before[1] and after_out == before[2], ("transport error wrote bytes", label)
            with self.lock:
                self.counts["error_no_write_cases"] += 1
                self.counts[f"status_{status}"] += 1
            return Result(status, None, None, b"", frame)

        assert len(frame) >= 64
        operation, old_len, new_len, context, policy, *reserved = struct.unpack_from("<8Q", frame)
        header = dict(zip(HEADER_NAMES, struct.unpack_from("<16Q", after_out, guard)))
        assert header["revision"] == 2 and header["reserved"] == 0
        assert header["policy"] == policy
        caps = expected_capacities(header["old_lines"], header["new_lines"])
        assert (header["output_capacity"], header["workspace_capacity"]) == caps
        assert after_out[:guard] == before[2][:guard] and after_work[:guard] == before[1][:guard]
        assert after_work[guard:guard + 64] == frame[:64], ("descriptor changed", label)
        if operation in (0, 2):
            zero = ("plan_bytes", "rendered_bytes", "fragments", "fragment_offset", "literal_offset",
                    "literal_bytes", "semantic", "operand_a", "operand_b")
            assert all(header[key] == 0 for key in zero), ("inspect ran semantic/plan work", label, header)
            assert after_work == before[1], ("inspect workspace changed", label)
            assert after_out[guard + 128:] == before[2][guard + 128:], ("inspect output tail changed", label)
            with self.lock:
                self.counts["inspect_calls"] += 1
            return Result(0, header, None, after_out[guard:guard + 128], frame)
        assert operation in (1, 3)
        assert output_capacity >= caps[0] and workspace_capacity >= caps[1]
        assert after_work[guard + caps[1]:] == before[1][guard + caps[1]:], ("scratch tail changed", label)
        if header["semantic"]:
            assert 1 <= header["semantic"] <= 6
            assert header["plan_bytes"] == 128
            zero = ("rendered_bytes", "fragments", "fragment_offset", "literal_offset", "literal_bytes")
            assert all(header[key] == 0 for key in zero), ("semantic exposed partial result", label, header)
            assert after_out[guard + 128:] == before[2][guard + 128:], ("semantic output tail changed", label)
            with self.lock:
                self.counts["semantic_panics"] += 1
            return Result(0, header, None, after_out[guard:guard + 128], frame)
        assert header["operand_a"] == header["operand_b"] == 0
        assert header["fragment_offset"] == 128
        assert header["literal_offset"] == 128 + 32 * header["fragments"]
        assert header["plan_bytes"] == header["literal_offset"] + header["literal_bytes"]
        assert 128 <= header["plan_bytes"] <= caps[0]
        assert after_out[guard + header["plan_bytes"]:] == before[2][guard + header["plan_bytes"]:], ("plan output tail changed", label)
        plan = after_out[guard:guard + header["plan_bytes"]]
        literal = plan[header["literal_offset"]:]
        parts = []
        for i in range(header["fragments"]):
            kind, offset, size, zero = struct.unpack_from("<4Q", plan, 128 + 32 * i)
            assert kind in (0, 1) and zero == 0
            pool = source if kind == 0 else literal
            assert offset <= len(pool) and size <= len(pool) - offset, ("fragment outside pool", label, i)
            part = pool[offset:offset + size]
            part.decode("utf-8")
            parts.append(part)
        rendered = b"".join(parts)
        assert len(rendered) == header["rendered_bytes"]
        with self.lock:
            self.counts["plan_calls"] += 1
            self.counts["rendered_bytes_observed"] += len(rendered)
        return Result(0, header, rendered, plan, frame)

    def valid_pair(self, old: bytes, new: bytes, context: int, policy: int,
                   trusted: bool, old_lines: int, new_lines: int,
                   label: str = "", extra_capacity: int = 0, guard: int = 17):
        source = old + new
        operation = 2 if trusted else 0
        query = self.call(source, descriptor(operation, len(old), len(new), context, policy),
                          128 + extra_capacity, label=label + ":inspect", guard=guard)
        assert query.header["old_lines"] == old_lines and query.header["new_lines"] == new_lines
        expected_out, expected_work = expected_capacities(old_lines, new_lines)
        plan = self.call(source, descriptor(operation + 1, len(old), len(new), context, policy),
                         expected_out + extra_capacity, expected_work + extra_capacity,
                         label=label + ":plan", guard=guard)
        for key in ("revision", "output_capacity", "workspace_capacity", "old_lines", "new_lines", "policy", "reserved"):
            assert query.header[key] == plan.header[key], ("inspect/plan mismatch", label, key)
        return query, plan


def compare_outcome(case: dict, reference: dict, result: Result):
    expected = reference["formatted"]
    header = result.header
    if expected["ok"]:
        assert header["semantic"] == 0, ("unexpected native panic", case["id"], header)
        assert result.rendered == bytes.fromhex(expected["bytes_hex"]), (
            "formatted bytes differ", case["id"], case.get("name"),
            result.rendered[:200].hex(), expected["bytes_hex"][:400],
        )
        return
    assert header["semantic"] != 0, ("missing original panic", case["id"])
    message = bytes.fromhex(expected["panic_hex"]).decode()
    code, a, b = header["semantic"], header["operand_a"], header["operand_b"]
    if message == "attempt to multiply with overflow":
        assert code == 1 and (a, b) == (case["context"], 2)
    elif message.startswith("index out of bounds: the len is "):
        assert code == 3
        assert message == f"index out of bounds: the len is {a} but the index is {b}"
        assert b >= a
    elif message == "attempt to add with overflow":
        assert code in (2, 4)
        assert a + b > ((1 << 32) - 1 if code == 2 else MAX)
    elif message == "attempt to subtract with overflow":
        assert code == 5 and a < b
    elif message == "capacity overflow":
        assert code == 6
    else:
        raise AssertionError(("unmapped original semantic panic", case["id"], message))
