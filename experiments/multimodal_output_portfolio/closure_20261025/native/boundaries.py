"""Probe recovery and absent evidence on copies of a completed development run."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from .build import sha
from .run import RECOVERY_KEYS, write


def main(args):
    args.output.mkdir(parents=True, exist_ok=False)
    original = args.study / 'state'
    descriptor = args.study / 'descriptor.json'
    expected = json.loads((args.study / 'results.json').read_text())['process_status'][-1]
    evidence = []
    cases = ('intact_after_segment_rollover', 'binary_identity', 'truncated_controller',
             'controller_digest', 'missing_segment', 'swapped_segments', 'ndu_frontier')
    for case in cases:
        state = args.output / case
        shutil.copytree(original, state)
        if case == 'binary_identity':
            path = state / 'identity.json'
            value = json.loads(path.read_text()); value['binary'] = '0' * 64
            path.write_text(json.dumps(value))
        elif case == 'truncated_controller':
            path = state / 'control.jsonl'; path.write_bytes(path.read_bytes()[:-1])
        elif case == 'controller_digest':
            path = state / 'control.jsonl'
            path.write_bytes(path.read_bytes().replace(b'"authority":"deny_all"', b'"authority":"tampered"', 1))
        elif case == 'missing_segment':
            (state / 'neuron-0000.journal').unlink()
        elif case == 'swapped_segments':
            first, second = state / 'neuron-0000.journal', state / 'neuron-0001.journal'
            a, b = first.read_bytes(), second.read_bytes(); first.write_bytes(b); second.write_bytes(a)
        elif case == 'ndu_frontier':
            path = state / 'control.jsonl'
            lines = path.read_text().splitlines()
            record = json.loads(lines[-1]); record['event']['modulator'] = '0' * 64
            payload = json.dumps(record['event'], sort_keys=True, separators=(',', ':')).encode()
            record['digest'] = hashlib.sha256(b'hepta.closure.online-event.v1'
                                             + bytes.fromhex(record['previous']) + payload).hexdigest()
            lines[-1] = json.dumps(record, sort_keys=True, separators=(',', ':'))
            path.write_text('\n'.join(lines) + '\n')
        process = subprocess.run([str(args.binary), str(descriptor), sha(descriptor), str(state), 'resume'],
                                 input='{"kind":"shutdown"}\n', text=True, capture_output=True, timeout=20)
        accepted = process.returncode == 0
        if accepted != (case == 'intact_after_segment_rollover'):
            raise AssertionError((case, process.returncode, process.stdout, process.stderr))
        if accepted:
            actual = json.loads(process.stdout.splitlines()[0])['status']
            if {k: actual[k] for k in RECOVERY_KEYS} != {k: expected[k] for k in RECOVERY_KEYS}:
                raise AssertionError('Full ordered-segment recovery changed the frontier')
        evidence.append({'case': case, 'accepted': accepted, 'returncode': process.returncode,
                         'stdout': process.stdout, 'stderr': process.stderr})
    for case, field in (('missing_verification', 'verification_path'), ('missing_observer', 'observer_path'),
                        ('changed_weights', 'weights_path')):
        value = json.loads(descriptor.read_text())
        value[field] = str(args.output / (case + '.absent'))
        if case == 'changed_weights':
            Path(value[field]).write_text('{}')
        spec = args.output / (case + '.json'); write(spec, value)
        process = subprocess.run([str(args.binary), str(spec), sha(spec), str(args.output / (case + '.state')), 'new'],
                                 input='', text=True, capture_output=True, timeout=20)
        if process.returncode == 0 or process.stdout:
            raise AssertionError('Absent or changed evidence admitted an owner')
        evidence.append({'case': case, 'accepted': False, 'returncode': process.returncode,
                         'stdout': process.stdout, 'stderr': process.stderr})
    write(args.output / 'results.json', {'schema': 'hepta.closure.native-boundaries.v1',
                                        'source_run': str(args.study), 'binary_sha256': sha(args.binary),
                                        'cases': evidence, 'all_expected_outcomes_observed': True,
                                        'production_trust_credentials_generated': False})
    print(json.dumps({'cases': len(evidence), 'all_expected_outcomes_observed': True}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('binary', 'study', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    main(parser.parse_args())
