"""Verify compiled Rust transport against actual continuation of the Python engine."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parents[1]
sys.path.insert(0, str(WORKSPACE))
from rrsnn_v2.audit.exact_rollout import ExactIndependentRollout
from rrsnn_v2.audit.validate_exact_adapter import execute_continuation


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bits_equal(left, right):
    if isinstance(left, dict):
        return set(left) == set(right) and all(bits_equal(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(bits_equal(a, b) for a, b in zip(left, right))
    if isinstance(left, float):
        return struct.pack('>d', left) == struct.pack('>d', float(right))
    return left == right


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--use-prebuilt', action='store_true',
                        help='Use the delivered binary without a local Cargo target directory.')
    args = parser.parse_args()
    binary_source = ROOT / 'rust_bridge/target/release/rrsnn-offline-replay-bridge'
    binary = ROOT / 'bin/rrsnn-offline-replay-bridge'
    binary.parent.mkdir(exist_ok=True)
    if not args.use_prebuilt:
        shutil.copy2(binary_source, binary)
    build_report = json.loads((ROOT / 'rust_build_report.json').read_text())
    if sha256(binary) != build_report['binary_sha256']:
        raise RuntimeError('Binary does not match the recorded compiled bridge')
    fixture_file = ROOT / 'rust_bridge/fixtures/exact_replay_fixture.json'
    fixture = json.loads(fixture_file.read_text())
    if fixture['numpy_version'] != np.__version__:
        raise RuntimeError('Use the NumPy implementation pinned by the fixture')
    output = ROOT / 'replay_results'
    output.mkdir(exist_ok=True)
    context = {
        'upstreamSourceCommit': 'f8c9419df6ddeb36ff8b522a50219981fb8d9345',
        'engineSourceSha256': sha256(WORKSPACE / 'rrsnn_v2/audit/exact_rollout.py'),
        'modelArtifactSha256': None,
        'numpyVersion': np.__version__, 'instanceId': 'offline.engine.fixture.1',
        'logicalSequence': 1, 'previousPayloadSha256': None,
    }
    context_file = output / 'context.json'
    context_file.write_text(json.dumps(context, indent=2) + '\n')
    commands = []

    def run(*arguments, rejection=False):
        result = subprocess.run([str(binary), *map(str, arguments)], capture_output=True, text=True)
        commands.append({'arguments': list(map(str, arguments)), 'exit_code': result.returncode,
                         'stdout': result.stdout, 'stderr': result.stderr})
        if (result.returncode == 0) == rejection:
            raise AssertionError('Unexpected Rust CLI acceptance/rejection')
        return result

    run('check', fixture_file)
    roundtrip_file = output / 'rust_roundtrip_fixture.json'
    run('roundtrip', fixture_file, roundtrip_file)
    restored_fixture = json.loads(roundtrip_file.read_text())
    assert bits_equal(fixture, restored_fixture)
    envelope_file = output / 'event_checkpoint_envelope.json'
    payload_file = output / 'verified_payload.json'
    run('pack', fixture_file, context_file, envelope_file)
    run('unpack', envelope_file, payload_file)
    envelope = json.loads(envelope_file.read_text())
    raw_payload = envelope['canonicalPayloadJson'].encode()
    assert hashlib.sha256(b'rrsnn.offline.event-payload.v2\0' + raw_payload).hexdigest() == envelope['payloadSha256']
    payload = json.loads(payload_file.read_text())
    assert payload['context'] == context
    assert bits_equal(payload['checkpoint'], fixture['checkpoint_at_split'])
    assert bits_equal(payload['pendingInputs'], fixture['continuation'])
    checks = []
    for route, state, continuation in [
        ('rust_fixture_roundtrip', restored_fixture['checkpoint_at_split'], restored_fixture['continuation']),
        ('rust_envelope_unpack', payload['checkpoint'], payload['pendingInputs']),
    ]:
        engine = ExactIndependentRollout.from_checkpoint(state)
        events = execute_continuation(engine, continuation)
        final = engine.checkpoint()
        assert bits_equal(events, fixture['expected_continuation_events'])
        assert bits_equal(final, fixture['expected_final'])
        checks.append({'route': route, 'events_identical': True,
                       'final_physical_and_rng_state_bitwise_identical': True,
                       'continuation_spikes': len(events)})
    altered = dict(envelope)
    altered['canonicalPayloadJson'] = '{}'
    altered_file = output / 'tampered_envelope.json'
    altered_file.write_text(json.dumps(altered) + '\n')
    run('unpack', altered_file, output / 'must_not_exist.json', rejection=True)
    assert not (output / 'must_not_exist.json').exists()
    elevated = dict(envelope)
    elevated['productionActivationAllowed'] = True
    elevated_file = output / 'invalid_authority_envelope.json'
    elevated_file.write_text(json.dumps(elevated) + '\n')
    run('unpack', elevated_file, output / 'must_not_exist.json', rejection=True)
    report = {
        'schema': 'rrsnn.rust-python-checkpoint-resume-validation.v1',
        'all_passed': True, 'rust_build_passed': json.loads((ROOT / 'rust_build_report.json').read_text())['all_passed'],
        'fixture_sha256': sha256(fixture_file), 'binary_sha256': sha256(binary),
        'engine_source_sha256': context['engineSourceSha256'],
        'validator_source_sha256': sha256(__file__), 'numpy_version': np.__version__,
        'complete_pcg64_state_preserved': True, 'physical_f64_bits_preserved': True,
        'known_input_order_preserved': True, 'checks': checks,
        'payload_bytes': len(raw_payload), 'envelope_file_bytes': envelope_file.stat().st_size,
        'payload_sha256': envelope['payloadSha256'],
        'tampering_rejected': True, 'authority_forgery_rejected': True,
        'commands': commands, 'official_owner_executed': False,
        'rust_recomputed_brownian_physics': False,
        'hepta_workspace_compiled': False,
        'production_activation_allowed': False,
        'limits': [
            'One actually generated synthetic two-component engine trajectory, not a production trace.',
            'Rust validates and transports a bounded complete checkpoint; Python/NumPy supplies the stochastic continuation.',
            'The SHA-256 envelope detects alteration relative to its digest, but is not an authenticated owner receipt.',
            'Resource ledgers, maturity obligations and coupled event queues need their separate owner snapshots.',
            'The research envelope is unregistered and does not change any existing Hepta V1 contract.',
        ],
    }
    (ROOT / 'rust_replay_validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: report[k] for k in ['all_passed', 'binary_sha256', 'checks', 'payload_bytes',
                                           'tampering_rejected', 'authority_forgery_rejected']}, indent=2))


if __name__ == '__main__':
    main()
