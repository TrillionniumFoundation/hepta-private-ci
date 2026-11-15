"""Record real native calls with complete disjoint buffers and canaries."""
from pathlib import Path
import collections
import ctypes
import gzip
import hashlib
import json
import shutil
import struct
from .raw_reference import reference


def identity(path):
    data = path.read_bytes()
    return {'path': str(path), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


class Runner:
    def __init__(self, root, library, output):
        self.root, self.output = root, output
        self.counts, self.categories = collections.Counter(), collections.Counter()
        self.maximum_source = self.maximum_output = self.trace_bytes = 0
        self.trace_hash = hashlib.sha256()
        self.library = ctypes.CDLL(str(library))
        self.native = self.library.codex_hia_template_render
        self.native.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
        self.native.restype = ctypes.c_uint64
        self.trace = gzip.GzipFile(filename=str(output / 'trace.jsonl.gz'), mode='xb', mtime=0, compresslevel=6)

    def check(self, source, operation, capacity, category, workspace=None):
        if workspace is None:
            workspace = struct.pack('<4Q', 1, operation, 0, 0)
        status, payload = reference(source, workspace, capacity)
        guard = b'\xD7' * 17
        source_initial, workspace_initial = guard + source + guard, guard + workspace + guard
        output_initial = guard + b'\xA5' * capacity + guard
        source_buffer = ctypes.create_string_buffer(source_initial, len(source_initial))
        workspace_buffer = ctypes.create_string_buffer(workspace_initial, len(workspace_initial))
        output_buffer = ctypes.create_string_buffer(output_initial, len(output_initial))
        actual = self.native(ctypes.addressof(source_buffer) + 17, len(source),
                             ctypes.addressof(output_buffer) + 17, capacity,
                             ctypes.addressof(workspace_buffer) + 17, len(workspace))
        observed = output_buffer.raw
        assert actual == status, (category, self.counts['calls'], operation, actual, status, source.hex()[:1200])
        assert source_buffer.raw == source_initial and workspace_buffer.raw == workspace_initial
        expected = guard + payload + b'\xA5' * (capacity - len(payload)) + guard
        assert observed == expected, (category, self.counts['calls'], operation, observed.hex()[:1600], expected.hex()[:1600])
        self.counts['calls'] += 1
        self.counts['operation_' + str(operation)] += 1
        self.counts['status_' + str(actual)] += 1
        if actual:
            self.counts['nonzero_entire_output_unchanged'] += 1
        elif struct.unpack_from('<Q', payload, 40)[0]:
            self.counts['semantic_errors'] += 1
        self.categories[category] += 1
        self.maximum_source = max(self.maximum_source, len(source))
        self.maximum_output = max(self.maximum_output, len(payload))
        row = {'i': self.counts['calls'], 'category': category, 'source': source.hex(),
               'workspace': workspace.hex(), 'capacity': capacity, 'status': actual,
               'output_including_guards': observed.hex(), 'source_workspace_and_guards_unchanged': True}
        raw = (json.dumps(row, separators=(',', ':')) + '\n').encode()
        self.trace.write(raw); self.trace_hash.update(raw); self.trace_bytes += len(raw)
        if self.counts['calls'] % 512 == 0:
            if shutil.disk_usage(self.root).free < 12 * 1024 * 1024:
                raise RuntimeError('live free-space reserve fell below 12 MiB')
            if (self.output / 'trace.jsonl.gz').stat().st_size > 8 * 1024 * 1024:
                raise RuntimeError('trace exceeded declared 8 MiB budget')

    def finish(self):
        self.trace.close()
        digest, size, lines = hashlib.sha256(), 0, 0
        with gzip.open(self.output / 'trace.jsonl.gz', 'rb') as stream:
            for line in stream:
                digest.update(line); size += len(line); lines += 1
        assert digest.hexdigest() == self.trace_hash.hexdigest() and size == self.trace_bytes and lines == self.counts['calls']
        return {'counts': dict(self.counts), 'categories': dict(self.categories),
                'maximum_source_bytes': self.maximum_source, 'maximum_written_bytes': self.maximum_output,
                'trace': identity(self.output / 'trace.jsonl.gz'), 'uncompressed_trace_bytes': size,
                'uncompressed_trace_sha256': digest.hexdigest(), 'trace_crc_and_full_readback_verified': True}
