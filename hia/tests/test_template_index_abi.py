#!/usr/bin/env python3
"""Exercise the real B3 index ABI, including buffers larger than the seed cap."""

import argparse
import ctypes
import hashlib
import itertools
import json
import mmap
import random
import resource
import struct
import time
from pathlib import Path


HEADER = 128
NODE = 64
MAX = (1 << 64) - 1
INVALID = 0xFFFFFFFF
SHORT = 0xFFFFFFFE
CANARY = bytes([0xA7]) * 32


def word(data, at):
    return struct.unpack_from("<Q", data, at)[0]


def put(data, at, value):
    struct.pack_into("<Q", data, at, value)


class Native:
    def __init__(self, library):
        self.library = ctypes.CDLL(str(library))
        self.entry = self.library.codex_hia_template_index
        self.entry.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
        self.entry.restype = ctypes.c_uint64
        self.calls = 0
        self.errors = 0
        self.ordered_pages = 0
        self.query_windows = 0

    def invoke(self, keys, workspace, command, a=0, b=0, c=0, *, output=None,
               workspace_length=None, keys_length=None, error=None):
        # Each allocation is independently owned; this ABI does not admit aliases.
        if output is None:
            output = bytearray(32)
        for index, value in enumerate((command, a, b, c)):
            if 40 + index * 8 <= len(workspace):
                put(workspace, 32 + index * 8, value)
        before_workspace = bytes(workspace) if error is not None else None
        before_output = bytes(output) if error is not None else None
        guarded_workspace = bytearray(CANARY) + workspace + CANARY
        guarded_output = bytearray(CANARY) + output + CANARY
        w = (ctypes.c_ubyte * len(guarded_workspace)).from_buffer(guarded_workspace)
        o = (ctypes.c_ubyte * len(guarded_output)).from_buffer(guarded_output)
        extent = len(workspace) if workspace_length is None else workspace_length
        source_extent = len(keys) if keys_length is None else keys_length
        status = self.entry(keys, source_extent, ctypes.addressof(o) + 32, len(output),
                            ctypes.addressof(w) + 32, extent)
        self.calls += 1
        assert guarded_workspace[:32] == guarded_workspace[-32:] == CANARY
        assert guarded_output[:32] == guarded_output[-32:] == CANARY
        workspace[:] = guarded_workspace[32:-32]
        output[:] = guarded_output[32:-32]
        if error is not None:
            assert status == error, (status, error, command, a, b, c)
            assert bytes(workspace) == before_workspace
            assert bytes(output) == before_output
            self.errors += 1
            return None
        assert 32 <= status <= len(output), (status, command, a, b, c)
        return status, struct.unpack_from("<4Q", output), output

    def insert_fast(self, keys, workspace, begin, end, *, keys_length=None):
        # Fast bulk path reuses real allocations; the checked/error path above
        # surrounds each buffer with canaries and verifies call atomicity.
        for index, value in enumerate((0, begin, end, 0)):
            put(workspace, 32 + index * 8, value)
        output = (ctypes.c_ubyte * 32)()
        w = (ctypes.c_ubyte * len(workspace)).from_buffer(workspace)
        status = self.entry(keys, len(keys) if keys_length is None else keys_length,
                            output, 32, w, len(workspace))
        self.calls += 1
        assert status == 32, (status, begin, end, word(workspace, 0))
        return struct.unpack("<4Q", output)

    def ordered(self, workspace):
        output = bytearray(32 + 8 * 1024)
        cursor, seen, ids = MAX, 0, []
        while True:
            status, (event, cursor, count, seen), output = self.invoke(
                b"", workspace, 1, cursor, seen, output=output)
            assert event == 2 and count <= 1024 and status == 32 + 8 * count
            ids.extend(struct.unpack_from(f"<{count}Q", output, 32))
            assert seen == len(ids)
            self.ordered_pages += 1
            if cursor == 0:
                assert len(ids) == word(workspace, 0)
                return ids
            assert count and len(ids) < word(workspace, 0)

    def find(self, keys, workspace, query, mark=False):
        command, offset, requests = 3 if mark else 2, 0, set()
        while True:
            chunk = query[offset:offset + 4096]
            output = bytearray(32) + chunk
            _, (event, value, b, c), _ = self.invoke(
                keys, workspace, command, len(query), offset, len(chunk), output=output)
            assert b == c == 0
            self.query_windows += 1
            if event == 3:
                return value
            if event == 4:
                assert value == 0
                return None
            assert event == 5 and value < len(query)
            request = (word(workspace, 64), value)
            assert request not in requests
            requests.add(request)
            command, offset = 4, value


def allocation(data):
    return (ctypes.c_ubyte * len(data)).from_buffer_copy(data)


def inspect_tree(workspace, keys, names):
    count, root, head = (word(workspace, offset) for offset in (0, 8, 16))
    assert count == len(names)
    visited, ordered = set(), []

    def visit(link, parent):
        if link == 0:
            return 0
        assert 1 <= link <= count and link not in visited
        visited.add(link)
        node = struct.unpack_from("<8Q", workspace, HEADER + (link - 1) * NODE)
        left, right, actual_parent, height, _, used, begin, size = node
        assert actual_parent == parent and used in (0, 1)
        assert begin <= len(keys) and size <= len(keys) - begin
        assert bytes(keys[begin:begin + size]) == names[link - 1]
        lh = visit(left, link)
        ordered.append(link - 1)
        rh = visit(right, link)
        assert abs(lh - rh) <= 1 and height == 1 + max(lh, rh)
        return height

    height = visit(root, 0)
    assert len(visited) == count
    expected = sorted(range(count), key=names.__getitem__)
    assert ordered == expected
    link, chained = head, []
    while link:
        assert 1 <= link <= count and len(chained) < count
        chained.append(link - 1)
        link = word(workspace, HEADER + (link - 1) * NODE + 32)
    assert chained == expected
    del visit
    return height


def structural_cases(native):
    rows = []
    orders = list(itertools.permutations(range(4)))
    for order in orders:
        names = [bytes([index]) for index in order]
        keys = allocation(b"".join(names))
        workspace = bytearray(HEADER + NODE * len(names))
        for index in range(len(names)):
            assert native.insert_fast(keys, workspace, index, index + 1) == (0, index, 0, 0)
            inspect_tree(workspace, keys, names[:index + 1])
        assert native.ordered(workspace) == sorted(range(4), key=names.__getitem__)
    for size in (255, 256, 257, 4097, 65535, 65536, 65537):
        for order in ("ascending", "descending", "shuffled"):
            values = list(range(size))
            if order == "descending":
                values.reverse()
            elif order == "shuffled":
                random.Random(0x486961 + size).shuffle(values)
            names = [f"key{value:08}".encode() for value in values]
            key_bytes = b"".join(names)
            keys = allocation(key_bytes)
            workspace = bytearray(HEADER + NODE * size)
            start = time.monotonic()
            for index in range(size):
                begin = 11 * index
                assert native.insert_fast(keys, workspace, begin, begin + 11) == (0, index, 0, 0)
            height = inspect_tree(workspace, keys, names)
            ids = native.ordered(workspace)
            assert ids == sorted(range(size), key=names.__getitem__)
            for index in (0, size // 2, size - 1):
                before = bytes(workspace)
                assert native.insert_fast(keys, workspace, 11 * index, 11 * (index + 1)) == (1, index, 0, 0)
                assert workspace[:32] == before[:32] and workspace[64:] == before[64:]
                assert native.find(keys, workspace, names[index]) == index
                assert native.find(keys, workspace, names[index], mark=True) == index
            rows.append({"size": size, "order": order, "height": height,
                         "node_buffer_bytes": len(workspace), "seconds": time.monotonic() - start})
    return rows


def invalid_cases(native):
    keys = allocation(b"bac")
    good = bytearray(HEADER + 4 * NODE)
    for index in range(3):
        assert native.insert_fast(keys, good, index, index + 1) == (0, index, 0, 0)
    for length in range(128):
        native.invoke(keys, bytearray(length), 0, error=INVALID)
    for length in range(32):
        native.invoke(keys, bytearray(good), 0, 0, 1, output=bytearray(length), error=SHORT)
    for offset, values in ((0, (5, MAX)), (8, (0, 4, MAX)), (16, (0, 4, MAX)),
                           (24, (4, MAX)), (96, (1, 2, MAX)), (104, (2, MAX)),
                           (112, (1, MAX)), (120, (1, MAX))):
        for value in values:
            bad = bytearray(good)
            put(bad, offset, value)
            native.invoke(keys, bad, 0, 0, 1, error=INVALID)
    for command, a, b, c in ((MAX, 0, 0, 0), (6, 0, 0, 0), (0, 2, 1, 0),
                             (0, 0, 4, 0), (0, MAX, MAX, 0), (0, 0, 1, 1),
                             (4, 1, 0, 1), (1, MAX, 1, 0), (1, 0, 0, 0),
                             (1, 1, 3, 0), (1, MAX, 0, 1), (5, 1, 0, 0),
                             (2, 1, 2, 0), (2, 1, 0, 0), (2, 1, 0, 2),
                             (2, MAX, MAX, 1), (2, MAX, 0, 4097)):
        native.invoke(keys, bytearray(good), command, a, b, c,
                      output=bytearray(32 + min(c, 4097)), error=INVALID)
    native.invoke(keys, bytearray(good), 2, 1, 0, 1, error=SHORT)
    native.invoke(keys, bytearray(good), 1, MAX, error=SHORT)
    native.invoke(keys, bytearray(good), 0, 0, 1, workspace_length=HEADER + 3 * NODE - 1,
                  error=INVALID)
    for field, values in ((0, (1, 4)), (8, (1, 4)), (16, (1, 4)), (24, (0, 3, 96, 255)),
                           (32, (1, 4)), (40, (2, 255)), (48, (4, 255)), (56, (4, 255))):
        for value in values:
            bad = bytearray(good)
            put(bad, HEADER + field, value)
            native.invoke(keys, bad, 0, 0, 1, error=INVALID)
    for field, value, query in ((0, 4, b"a"), (8, 4, b"c"), (0, 1, b"a"),
                                 (8, 1, b"c"), (40, 2, b"b"), (48, 4, b"b"),
                                 (56, 4, b"b")):
        for command in (2, 3):
            bad = bytearray(good)
            put(bad, HEADER + field, value)
            native.invoke(keys, bad, command, len(query), 0, len(query),
                          output=bytearray(32) + query, error=INVALID)
    assert native.invoke(keys, bytearray(good), 2, MAX, 0, 1,
                         output=bytearray(32) + b"b")[1] == (4, 0, 0, 0)
    # Valid-prefix query continuation errors must preserve the prior phase,
    # visited path, usage marks, and output, even when the next window is bad.
    long = b"x" * 8193
    large_keys = allocation(long)
    pending = bytearray(HEADER + NODE)
    native.insert_fast(large_keys, pending, 0, len(long))
    result = native.invoke(large_keys, pending, 3, len(long), 0, 4096,
                           output=bytearray(32) + long[:4096])
    assert result[1] == (5, 4096, 0, 0)
    for command, a, b, c in ((0, 0, 1, 0), (1, MAX, 0, 0), (5, 0, 0, 0),
                             (4, len(long) + 1, 4096, 1), (4, len(long), 4095, 1),
                             (4, len(long), 4096, 0), (4, len(long), MAX, 1)):
        native.invoke(large_keys, bytearray(pending), command, a, b, c,
                      output=bytearray(33), error=INVALID)


def long_and_growth_cases(native):
    names = [b"", b"x" * (2 * 1024 * 1024) + b"a", b"x" * (2 * 1024 * 1024) + b"b",
             "\U0001f600".encode(), "\u00e9".encode(), b"z"]
    data = b"".join(names)
    keys = allocation(data)
    workspace = bytearray(HEADER)
    position = 0
    for index, name in enumerate(names):
        workspace.extend(bytes(NODE))
        end = position + len(name)
        assert native.insert_fast(keys, workspace, position, end, keys_length=end) == (0, index, 0, 0)
        position = end
    inspect_tree(workspace, keys, names)
    expected = sorted(range(len(names)), key=names.__getitem__)
    assert native.ordered(workspace) == expected
    for index in expected:
        reply = native.invoke(b"", workspace, 5)
        assert reply[1] == (6, index, 0, 0)
        assert native.find(keys, workspace, names[index]) == index
        assert native.find(keys, workspace, names[index], mark=True) == index
    assert native.invoke(b"", workspace, 5)[1] == (4, 0, 0, 0)
    assert native.find(keys, workspace, b"x" * (2 * 1024 * 1024) + b"c") is None
    return {"borrowed_key_bytes": len(data), "longest_query_bytes": max(map(len, names))}


def wide_offset_case(native):
    # Demand-zero virtual memory provides a real contiguous >4 GiB borrow;
    # only the few key pages are touched, not 4 GiB of physical RAM.
    size = (1 << 32) + 4096
    names = [b"b", b"a", b"c"]
    with mmap.mmap(-1, size, flags=mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS) as mapping:
        keys = (ctypes.c_ubyte * size).from_buffer(mapping)
        workspace = bytearray(HEADER + NODE * len(names))
        for index, name in enumerate(names):
            begin = (1 << 32) + 8 * index
            mapping[begin:begin + len(name)] = name
            assert native.insert_fast(keys, workspace, begin, begin + len(name)) == (0, index, 0, 0)
        inspect_tree(workspace, keys, names)
        assert native.ordered(workspace) == [1, 0, 2]
        for index, name in enumerate(names):
            assert native.find(keys, workspace, name, mark=True) == index
        assert native.invoke(b"", workspace, 5)[1] == (4, 0, 0, 0)
        del keys
    scalar = b"x" * 4095 + "\U0001f600".encode()
    keys = allocation(scalar)
    workspace = bytearray(HEADER + NODE)
    native.insert_fast(keys, workspace, 0, len(scalar))
    assert native.find(keys, workspace, scalar, mark=True) == 0
    return {"virtual_borrow_bytes": size, "key_offsets_exceed_u32": True,
            "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    native = Native(args.library.resolve())
    report = {"status": "running", "library_sha256": hashlib.sha256(args.library.read_bytes()).hexdigest(),
              "borrow_contract": "three distinct live allocations; no retained pointer; fresh nodes zero-filled",
              "source_sha256": hashlib.sha256(Path(__file__).parents[1].joinpath("template_index.hepta").read_bytes()).hexdigest()}
    try:
        invalid_cases(native)
        report["trees"] = structural_cases(native)
        report["long_inputs"] = long_and_growth_cases(native)
        report["wide_offset"] = wide_offset_case(native)
        report["status"] = "passed"
    except BaseException as error:
        report["status"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        report.update(calls=native.calls, error_no_write=native.errors,
                      ordered_pages=native.ordered_pages, query_windows=native.query_windows)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("status", "calls", "error_no_write", "ordered_pages", "query_windows")}))


if __name__ == "__main__":
    main()
