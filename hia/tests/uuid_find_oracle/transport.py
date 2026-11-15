"""Canary-protected actual HIA calls; no semantic implementation in this host."""
from pathlib import Path
import ctypes
import gzip
import hashlib
import json
import struct

SHORT = 0xFFFFFFFE
INVALID = 0xFFFFFFFF


def identity(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": value.hexdigest()}


def fixture_cases(path):
    with path.open("rb") as stream:
        assert stream.read(8) == b"UUIDv1\0\0"
        count = struct.unpack("<Q", stream.read(8))[0]
        for _ in range(count):
            length = struct.unpack("<Q", stream.read(8))[0]
            data = stream.read(length)
            assert len(data) == length
            data.decode("utf-8")
            yield data
        assert stream.read(1) == b""


class Native:
    def __init__(self, producer, library_dir, trace_path):
        from .admission import admit
        self.build, library_path, inputs = admit(producer, library_dir)
        self.bindings = [{"path": name, **record} for name, record in inputs.items()]
        self.library = ctypes.CDLL(str(library_path))
        self.entry = getattr(self.library, "codex_hia_uuid_find")
        self.entry.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
        self.entry.restype = ctypes.c_uint64
        self.counts = {"calls": 0, "query": 0, "emit": 0, "errors_no_write": 0}
        self.trace_path = trace_path
        self.file = trace_path.open("xb")
        self.trace = gzip.GzipFile(fileobj=self.file, mode="wb", filename="", mtime=0)
        self.trace_digest = hashlib.sha256()
        self.trace_bytes = 0

    def call(self, source, frame, output_capacity, expected_status, *, rows=None, operation=None, category=""):
        # Every advertised region is real, with unaligned pointers and guards.
        prefix = bytes(range(17))
        suffix = bytes(range(239, 256))
        source_bytes = prefix + source + suffix
        workspace_bytes = prefix + frame + suffix
        output_bytes = prefix + b"\xA5" * output_capacity + suffix
        s = ctypes.create_string_buffer(source_bytes, len(source_bytes))
        w = ctypes.create_string_buffer(workspace_bytes, len(workspace_bytes))
        o = ctypes.create_string_buffer(output_bytes, len(output_bytes))
        status = self.entry(ctypes.addressof(s) + 17, len(source), ctypes.addressof(o) + 17,
                            output_capacity, ctypes.addressof(w) + 17, len(frame))
        self.counts["calls"] += 1
        assert status == expected_status, (category, status, expected_status)
        assert s.raw == source_bytes, (category, "source changed")
        assert w.raw == workspace_bytes, (category, "workspace changed")
        after = o.raw
        assert after[:17] == prefix and after[17 + output_capacity:] == suffix, (category, "guard changed")
        payload = after[17:17 + output_capacity]
        if status:
            self.counts["errors_no_write"] += 1
            assert after == output_bytes, (category, "error partially wrote output")
        else:
            assert rows is not None and operation in (0, 1)
            expected_bytes = 64 + 16 * len(rows)
            written = 64 if operation == 0 else expected_bytes
            header = struct.unpack("<8Q", payload[:64])
            assert header == (1, operation, len(source), len(rows), expected_bytes, 64, written, 0), (category, header)
            assert payload[written:] == b"\xA5" * (output_capacity - written)
            if operation:
                actual = list(struct.iter_unpack("<QQ", payload[64:written]))
                assert actual == rows, (category, actual[:5], rows[:5])
                self.counts["emit"] += 1
            else:
                self.counts["query"] += 1
        record = {"call": self.counts["calls"], "category": category, "source_bytes": len(source),
                  "source_sha256": hashlib.sha256(source).hexdigest(), "frame_hex": frame.hex(),
                  "output_capacity": output_capacity, "status": status,
                  "output_sha256": hashlib.sha256(payload).hexdigest(), "input_and_canaries_unchanged": True}
        encoded = (json.dumps(record, separators=(",", ":")) + "\n").encode()
        self.trace.write(encoded)
        self.trace_digest.update(encoded)
        self.trace_bytes += len(encoded)
        return payload

    def valid(self, source, rows, operation, extra=13, category=""):
        required = 64 + 16 * len(rows)
        capacity = (64 if operation == 0 else required) + extra
        return self.call(source, struct.pack("<4Q", 1, operation, 0, 0), capacity, 0,
                         rows=rows, operation=operation, category=category)

    def finish(self):
        self.trace.close()
        self.file.close()
        for record in self.bindings:
            assert identity(Path(record["path"])) == record
        return {"bindings": self.bindings, "counts": self.counts,
                "call_trace_archive": identity(self.trace_path), "uncompressed_trace_bytes": self.trace_bytes,
                "uncompressed_trace_sha256": self.trace_digest.hexdigest(),
                "source_and_artifacts_unchanged": True}
