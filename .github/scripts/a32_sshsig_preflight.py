"""Standalone hash-bound query observation, independent of whole-source admission."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

PROBE_SHA256 = '87e828968f2a4d34751e84fa3f31e1b393643038ecd634b1c82d0938d071b20b'
IDENTITY_ENV = {'source_sha': 'SOURCE_SHA', 'run_id': 'GITHUB_RUN_ID', 'run_attempt': 'GITHUB_RUN_ATTEMPT', 'lane': 'QUALIFICATION_LANE'}


def execute_probe(path, output):
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != PROBE_SHA256:
        raise RuntimeError('standalone token probe hash mismatch; no execution')
    output.mkdir(parents=True, exist_ok=False)
    target = output / 'token.json'
    receipt = {'schema': 'a32.sshsig-independent-preflight.v1', 'probe_sha256': PROBE_SHA256,
               'source_admitted': False, 'native_functional_qualification': False,
               'identity': {key: os.environ[value] for key, value in IDENTITY_ENV.items()},
               'same_process_query_only': True, 'exit_code': None}
    namespace = {'__name__': 'hash_bound_token_preflight', '__file__': str(path)}
    pending = None
    try:
        exec(compile(data, str(path), 'exec'), namespace)
        receipt['exit_code'] = namespace['main'](['--output', str(target)])
        receipt['token_sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
    except BaseException as error:
        pending = error
        receipt['error'] = repr(error)
    try:
        with (output / 'receipt.json').open('x', encoding='utf-8') as stream:
            json.dump(receipt, stream, indent=2); stream.write('\n')
    except BaseException as error:
        if pending is None:
            pending = error
        else:
            pending.add_note('preflight receipt write also failed: ' + repr(error))
    if pending is not None:
        raise pending
    return receipt['exit_code']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.output.resolve().is_relative_to(root):
        raise RuntimeError('independent preflight must be outside source checkout')
    return execute_probe(root / '.github/scripts/a32_sshsig_token_probe.py', args.output.resolve())


if __name__ == '__main__':
    raise SystemExit(main())
