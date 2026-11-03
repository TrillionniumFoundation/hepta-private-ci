"""Bounded read-only Bazel9 ExecLogEntry wire decoder; no commands are executed."""
import collections
import hashlib
import io
import json
from pathlib import Path
import time
import zipfile
import zstandard

ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT / '1421-windows-release-execution.zip'
LIMIT = 256 * 1024**2
MAX_MESSAGE = 16 * 1024**2
START = time.monotonic()


def varint(data, offset):
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise ValueError('truncated protobuf varint')
        byte = data[offset]
        offset += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, offset
    raise ValueError('oversized protobuf varint')


def fields(data):
    output = collections.defaultdict(list)
    offset = 0
    while offset < len(data):
        tag, offset = varint(data, offset)
        number, wire = tag >> 3, tag & 7
        if wire == 0:
            value, offset = varint(data, offset)
        elif wire == 2:
            size, offset = varint(data, offset)
            if size > MAX_MESSAGE or offset + size > len(data):
                raise ValueError('invalid protobuf field bound')
            value = data[offset:offset + size]
            offset += size
        elif wire in (1, 5):
            size = 8 if wire == 1 else 4
            value = data[offset:offset + size]
            offset += size
        else:
            raise ValueError(f'unsupported wire type {wire}')
        output[number].append(value)
    return output


def first(message, key, default=None):
    return message.get(key, [default])[0]


def file_value(data):
    message = fields(data)
    digest = fields(first(message, 2, b''))
    size = first(digest, 2, 0)
    if size >= 2**63:
        raise ValueError('negative/oversized file length')
    return first(message, 1, b'').decode(), first(digest, 1, b'').decode(), size


entries = {}
unique = {}
counts = collections.Counter()
invocation = {}
bytes_read = 0
missing = []
with zipfile.ZipFile(ARCHIVE) as archive:
    infos = archive.infolist()
    assert len(infos) == 1 and infos[0].file_size < 16 * 1024**2
    with archive.open(infos[0]) as compressed:
        with zstandard.ZstdDecompressor().stream_reader(compressed) as decompressed:
            stream = io.BufferedReader(decompressed)
            while True:
                if time.monotonic() - START > 60 or counts['entries'] >= 1_000_000:
                    raise ValueError('analysis time/entry bound exceeded')
                first_byte = stream.read(1)
                if not first_byte:
                    break
                header = bytearray(first_byte)
                while header[-1] >= 128:
                    if len(header) >= 10:
                        raise ValueError('invalid message delimiter')
                    byte = stream.read(1)
                    if not byte:
                        raise ValueError('truncated delimiter')
                    header.extend(byte)
                size, _ = varint(header, 0)
                bytes_read += len(header) + size
                if size > MAX_MESSAGE or bytes_read > LIMIT:
                    raise ValueError('decompression/message bound exceeded')
                data = stream.read(size)
                if len(data) != size:
                    raise ValueError('truncated message')
                message = fields(data)
                counts['entries'] += 1
                identity = first(message, 1, 0)
                if 2 in message:
                    item = fields(message[2][0])
                    invocation = {'hash_function': first(item, 1, b'').decode(),
                                  'workspace': first(item, 2, b'').decode(),
                                  'id': first(item, 4, b'').decode()}
                elif 3 in message:
                    entries[identity] = [file_value(message[3][0])]
                    counts['file_entries'] += 1
                elif 4 in message:
                    item = fields(message[4][0])
                    directory = first(item, 1, b'').decode()
                    entries[identity] = [(directory + '/' + path, digest, size)
                                         for path, digest, size in map(file_value, item.get(2, []))]
                    counts['directory_entries'] += 1
                elif 5 in message:
                    entries[identity] = []
                elif 7 in message:
                    spawn = fields(message[7][0])
                    counts['spawns'] += 1
                    mnemonic = first(spawn, 8, b'').decode()
                    cacheable = bool(first(spawn, 14, 0))
                    success = first(spawn, 9, 0) == 0 and not first(spawn, 10, b'')
                    counts['cacheable_spawns'] += cacheable
                    if not cacheable or not success or mnemonic == 'TestRunner':
                        continue
                    counts['eligible_successful_non_test_spawns'] += 1
                    for encoded in spawn.get(6, []):
                        output = fields(encoded)
                        reference = first(output, 5, 0)
                        if not reference:
                            counts['invalid_output_paths'] += 1
                            continue
                        if reference not in entries:
                            missing.append(reference)
                            continue
                        for path, digest, size in entries[reference]:
                            if not digest and size:
                                raise ValueError('nonempty output has no digest')
                            if digest:
                                key = (digest, size)
                                unique.setdefault(key, {'digest': digest, 'bytes': size,
                                                        'path': path, 'mnemonic': mnemonic})
by_mnemonic = collections.Counter()
for value in unique.values():
    by_mnemonic[value['mnemonic']] += value['bytes']
result = {'archive_sha256': hashlib.sha256(ARCHIVE.read_bytes()).hexdigest(),
          'schema': 'https://raw.githubusercontent.com/bazelbuild/bazel/9.0.0/src/main/protobuf/spawn.proto',
          'invocation': invocation, 'decoded_bytes': bytes_read, 'counts': dict(counts),
          'missing_output_references': missing, 'unique_output_digests': len(unique),
          'unique_eligible_output_bytes': sum(item['bytes'] for item in unique.values()),
          'bytes_by_first_observed_mnemonic': dict(by_mnemonic),
          'largest_outputs': sorted(unique.values(), key=lambda item: item['bytes'], reverse=True)[:20],
          'elapsed_seconds': time.monotonic() - START,
          'limits': 'Windows release lane only; excludes action-result/tree metadata, failed/noncacheable/test spawns and non-spawn outputs. Not Linux size or measured disk-cache occupancy.'}
(ROOT / 'windows-release-output-size.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({key: value for key, value in result.items() if key not in ('largest_outputs',)}, indent=2))
