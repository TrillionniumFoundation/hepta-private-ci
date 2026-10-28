"""Read-only, KB-scale review of the V6 preparation format; no model execution."""

import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import time
from unittest.mock import patch

import numpy as np

ROOT = Path('/workspace/scratch/e8a4dc33549f/hepta')
DIRECTORY = ROOT / 'experiments/multimodal_output_portfolio/field_bridge_v6_preparation_20261028'
sys.path.insert(0, str(ROOT))
from experiments.multimodal_output_portfolio.field_bridge_v6_preparation_20261028 import budget, codec


def identity(path):
    raw = path.read_bytes()
    return {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def decode(raw):
    return codec.loads(raw, hashlib.sha256(raw).hexdigest(), len(raw))


def repack(header, payload, *, canonical=True):
    encoded = codec.canonical(header) if canonical else json.dumps(header, indent=2).encode()
    return codec.MAGIC + struct.pack('>Q', len(encoded)) + encoded + payload


def expect_rejection(raw, fragment):
    try:
        decode(raw)
    except ValueError as error:
        assert fragment in str(error), str(error)
        return {'outer_sha_recomputed': True, 'error': str(error)}
    raise AssertionError('Malformed envelope was accepted')


def main():
    started = time.time_ns()
    sources_before = [identity(DIRECTORY / name) for name in ('codec.py', 'budget.py', 'branch_state.py', 'tests.py')]
    checks = {}
    value = {1: (None, True, -0.0), '1': [np.asarray([-0.0, 1.5], dtype='>f4'), np.asarray([1, 256], dtype='>i2')]}
    raw = codec.dumps(value)
    restored = decode(raw)
    assert codec.dumps(restored) == raw
    assert restored['1'][0].dtype.str == '>f4' and restored['1'][1].dtype.str == '>i2'
    assert restored['1'][0].tobytes() == value['1'][0].tobytes()
    assert struct.pack('>d', restored[1][2]) == struct.pack('>d', -0.0)
    checks['typed_literal_roundtrip'] = {'passed': True, 'bytes': len(raw), 'big_endian_array_dtypes_preserved': True, 'signed_zero_bits_preserved': True}

    original = codec.dumps([np.asarray([1, 2], dtype=np.uint8), np.asarray([3, 4], dtype=np.uint8)])
    prefix = len(codec.MAGIC) + 8
    length = struct.unpack('>Q', original[len(codec.MAGIC):prefix])[0]
    header = json.loads(original[prefix:prefix + length])
    payload = original[prefix + length:]
    changed = copy.deepcopy(header)
    changed['arrays'][0]['sha256'] = '0' * 64
    checks['false_inner_hash'] = expect_rejection(repack(changed, payload), 'Array bytes differ')
    checks['corrupt_payload_with_new_outer_identity'] = expect_rejection(repack(header, bytes([payload[0] ^ 1]) + payload[1:]), 'Array bytes differ')
    changed = copy.deepcopy(header)
    changed['tree'][1][1][1] = 0
    checks['duplicate_array_reference'] = expect_rejection(repack(changed, payload), 'Duplicate or invalid array reference')
    changed = copy.deepcopy(header)
    changed['tree'][1].pop()
    checks['unused_array_payload'] = expect_rejection(repack(changed, payload), 'Noncanonical or unused envelope data')
    checks['noncanonical_metadata'] = expect_rejection(repack(header, payload, canonical=False), 'Noncanonical or unused envelope data')

    with tempfile.TemporaryDirectory(prefix='v6-independent-kb-', dir=ROOT.parent) as temporary:
        sample = Path(temporary) / 'sample.state'
        saved = codec.save(sample, value, len(raw))
        measured = budget.measured_envelope(sample, len(raw))
        assert measured['bytes'] == len(raw) == measured['measurement']['file_bytes']
        assert measured['sha256'] == saved['sha256']
        with patch.object(Path, 'open', side_effect=AssertionError('Oversized sample must be rejected before opening')):
            try:
                budget.measured_envelope(sample, len(raw) - 1)
            except ValueError as error:
                assert 'artifact cap' in str(error)
            else:
                raise AssertionError('Oversized sample accepted')
        checks['actual_sample_identity_and_pre_read_cap'] = {'passed': True, 'bytes': len(raw), 'sha256': saved['sha256'], 'oversize_rejected_before_open': True}

    requested = json.loads((DIRECTORY / 'BUDGET_PLAN.json').read_text())
    plan = budget.estimate(requested['artifacts'], retained_failed_archive_bytes=requested['retained_failed_archive_bytes'], buffer_bytes=requested['buffer_bytes'], directory_inode_bound=requested['directory_inode_bound'])
    gate = budget.disk_gate(ROOT.parent, plan)
    assert plan['unit_profiles_complete'] is False and len(plan['missing_artifact_bounds']) == 9
    assert plan['raw_with_failure_bound_bytes'] is None and plan['required_f_bavail_bytes'] is None
    assert plan['actual_measured_units'] == {}
    assert gate['capacity_passed'] is False and gate['research_start_permitted'] is False
    checks['real_candidate_budget_remains_unknown'] = {'passed': True, 'plan': plan, 'actual_disk_observation': gate}
    assert 'torch' not in sys.modules
    sources_after = [identity(DIRECTORY / name) for name in ('codec.py', 'budget.py', 'branch_state.py', 'tests.py')]
    assert sources_before == sources_after
    result = {
        'schema': 'hepta.field-bridge.v6-preparation.independent-probe.1',
        'started_unix_ns': started, 'completed_unix_ns': time.time_ns(),
        'status': 'PASS_SCOPED_PREPARATION_CHECKS', 'sources': sources_before,
        'sources_unchanged_during_probe': True, 'checks': checks,
        'runtime': {'python': sys.version, 'executable': sys.executable, 'numpy': np.__version__, 'torch_imported': False},
        'resource_boundary': {'model_calls': 0, 'training_microsteps': 0, 'rust_builds': 0, 'downloads': 0, 'raw_uploads': 0, 'largest_temporary_sample_bytes': len(raw), 'temporary_samples_removed': True},
        'new_research_registration': False, 'new_scientific_execution': False, 'admission': False,
    }
    destination = ROOT.parent / 'v6_preparation_independent_probe_20261028.json'
    with destination.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'receipt': identity(destination), 'check_groups': len(checks), 'status': result['status'], 'f_bavail_bytes': gate['f_bavail_bytes']}))


if __name__ == '__main__':
    main()
