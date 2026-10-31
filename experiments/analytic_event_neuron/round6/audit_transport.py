"""Independent archive inventory, numeric PNG decoding and acquired-history audit."""

import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import struct
import zipfile

import numpy as np
from PIL import Image


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    return sha(Path(path).read_bytes())


def digest(value):
    return sha(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())


class Checks:
    def __init__(self):
        self.count = 0
        self.maxima = {}

    def require(self, condition, label):
        self.count += 1
        if not condition:
            raise AssertionError(label)

    def close(self, actual, expected, label, tolerance=3e-11):
        actual, expected = np.asarray(actual, float), np.asarray(expected, float)
        self.require(actual.shape == expected.shape, label + ':shape')
        self.require(np.isfinite(actual).all() and np.isfinite(expected).all(), label + ':finite')
        error = float(np.max(np.abs(actual - expected))) if actual.size else 0.0
        self.maxima[label] = max(self.maxima.get(label, 0.0), error)
        self.require(error <= tolerance, f'{label}:error={error:.17g}, tolerance={tolerance}')


class Archive:
    def __init__(self, directory, receipt, checks):
        self.path = Path(directory) / receipt['path']
        manifest_path = self.path.with_suffix('.manifest.json')
        checks.require(file_sha(self.path) == receipt['sha256'], 'archive digest')
        checks.require(self.path.stat().st_size == receipt['bytes'], 'archive length')
        checks.require(file_sha(manifest_path) == receipt['manifest_sha256'], 'archive manifest digest')
        self.files = json.loads(manifest_path.read_text())['files']
        self.archive = zipfile.ZipFile(self.path)
        names = self.archive.namelist()
        checks.require(len(names) == len(set(names)) == len(self.files), 'unique complete archive inventory')
        checks.require(set(names) == set(self.files), 'archive manifest names')
        checks.require(len(names) == receipt['verified_files'], 'archive file count')
        self.original_bytes = 0
        for member in self.archive.infolist():
            path = PurePosixPath(member.filename)
            checks.require(not member.is_dir() and not path.is_absolute() and '..' not in path.parts
                           and (member.external_attr >> 16) & 0o170000 != 0o120000, 'safe regular archive member')
            expected = self.files[member.filename]
            checks.require(member.file_size == expected['bytes'], 'archive member declared length')
            raw = self.archive.read(member.filename)
            checks.require(len(raw) == expected['bytes'] and sha(raw) == expected['sha256'], 'archive member original bytes')
            self.original_bytes += len(raw)

    def read(self, name):
        return self.archive.read(name)

    def json(self, name):
        return json.loads(self.read(name))

    def close(self):
        self.archive.close()


def png_value(raw):
    """Read all complementary pixel blocks, then assemble IEEE754 bits manually."""
    with Image.open(io.BytesIO(raw)) as picture:
        if picture.format != 'PNG' or picture.size != (256, 32) or picture.mode != 'L':
            raise ValueError('Unexpected numeric PNG format')
        pixels = np.asarray(picture).copy()
    integer = 0
    for index in range(64):
        top = pixels[:16, 4 * index:4 * index + 4]
        bottom = pixels[16:, 4 * index:4 * index + 4]
        level = int(top[0, 0])
        if level not in (0, 255) or not np.all(top == level) or not np.all(bottom == 255 - level):
            raise ValueError('Corrupt numeric PNG bit or complementary check block')
        integer = 2 * integer + int(level == 255)
    value = struct.unpack('>d', integer.to_bytes(8, 'big'))[0]
    if not math.isfinite(value):
        raise ValueError('Nonfinite decoded transport value')
    return value


def transport_records(archive, prefix, checks):
    raw = archive.read(prefix + '/readbacks/TRANSPORT_RECEIPTS.jsonl')
    records = [json.loads(line) for line in raw.splitlines()]
    values = {}
    for row in records:
        checks.require(row['private_target_supplied'] is False, 'target-free transport receipt')
        checks.require(row['began_ns'] <= row['written_ns'] <= row['readback_ns'], 'transport execution order')
        checks.require(row['stage'] not in values, 'transport stage uniqueness')
        if row['kind'] == 'observation':
            data = archive.read(prefix + '/readbacks/' + row['path'])
            checks.require(sha(data) == row['sha256'], 'observation readback digest')
            document = json.loads(data)
            checks.require(document['schema'] == 'hepta.analytic-event.public-observation.v1', 'observation schema')
            value = float(document['value'])
        else:
            checks.require(row['kind'] == 'delivery', 'declared transport operation')
            text = archive.read(prefix + '/readbacks/' + row['text_path'])
            image = archive.read(prefix + '/readbacks/' + row['image_path'])
            checks.require(sha(text) == row['text_sha256'] and sha(image) == row['image_sha256'], 'delivery byte identity')
            value = png_value(image)
            checks.require(struct.pack('>d', value) == struct.pack('>d', float(text))
                           == struct.pack('>d', row['prediction']), 'PNG text and recorded value match bitwise')
        checks.require(math.isfinite(value), 'finite acquired value')
        values[row['stage']] = value
    return values, records, sha(raw)


def acquired_public(values, second, checks):
    checks.require(values['residual'] == values['sensor'] - values['initial'], 'actual first residual arithmetic')
    public = {'initial': values['initial'], 'residuals': [values['residual']],
              'variances': [values['sensor_variance']],
              **{name: values[name] for name in ('repair_cost', 'wait_cost', 'wait_variance')}}
    if second:
        checks.require(values['wait_residual'] == values['wait_sensor'] - values['initial'], 'actual paid residual arithmetic')
        public['residuals'].append(values['wait_residual'])
        public['variances'].append(values['wait_variance'])
    return public


def broker_records(directory, expected_count, checks, *, legacy_terminal_timestamp=False):
    root = Path(directory) / 'broker'
    start = [json.loads(line) for line in (root / 'BROKER_START.jsonl').read_text().splitlines()]
    checks.require(len(start) == 1, 'single broker data acquisition')
    checks.require(start[0]['data_sha256'] == file_sha(Path(directory) / 'DATA.npz'), 'broker loaded actual private data bytes')
    records = [json.loads(line) for line in (root / 'BROKER_TRANSCRIPT.jsonl').read_text().splitlines()]
    previous, state_hash, timestamp, groups, previous_state = '0' * 64, digest(None), -1, {}, None
    for sequence, record in enumerate(records, 1):
        body = {key: value for key, value in record.items() if key != 'sha256'}
        checks.require(digest(body) == record['sha256'] and record['previous_sha256'] == previous, 'broker hash chain')
        checks.require(record['request_id'] == sequence == record['request']['id'], 'broker sequence')
        checks.require(record['state_before_sha256'] == state_hash, 'broker state predecessor')
        checks.require(record['state_after_sha256'] == digest(record['state']), 'broker state digest')
        checks.require(record['response']['ok'] and record['response']['state_sha256'] == record['state_after_sha256'], 'accepted completed broker operation')
        checks.require(record['recorded_ns'] >= timestamp, 'broker monotone time')
        if record['operation'] != 'close':
            state = record['state']
            groups.setdefault((state['index'], state['arm']), []).append(record)
            durable = state['durable_readback_ns']
            if legacy_terminal_timestamp and record['operation'] == 'finish':
                checks.require(previous_state is not None and durable == previous_state['durable_readback_ns'],
                               'known old development terminal metadata retains previous timestamp')
                durable = record['response']['result']['final_readback_ns']
            checks.require(durable <= record['recorded_ns'], 'durable readback before response')
            checks.require(all(r['readback_ns'] <= durable for r in record['transport_records']), 'readback before durability receipt')
        previous, state_hash, timestamp = record['sha256'], record['state_after_sha256'], record['recorded_ns']
        previous_state = record['state']
    checks.require(records[-1]['operation'] == 'close', 'explicit final broker close')
    checks.require(records[-1]['response']['result'] == {'complete': True, 'finished_cases': expected_count}, 'all broker cases terminated')
    checks.require(len(groups) == expected_count, 'broker case inventory')
    return groups, start[0]
