"""Execute original signer CLIs with disposable keys and independent verification."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

import cryptography
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.backends.openssl.backend import backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, mldsa

SOURCE_NAMES = [
    'codex-rs/hepta-supervisor/src/final_use_signing.rs',
    *['codex-rs/hepta-supervisor/src/bin/' + name + '.rs' for name in (
        'hepta-final-use-signer', 'hepta-final-use-approver',
        'hepta-final-use-revocation-signer')],
    'codex-rs/hepta-contracts/src/final_use.rs',
    'codex-rs/hepta-contracts/src/final_use_control.rs',
    'codex-rs/hepta-contracts/src/pq_auth.rs',
]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sources(repo):
    return {name: digest(repo / name) for name in SOURCE_NAMES}


def compact(value):
    return json.dumps(value, separators=(',', ':'), ensure_ascii=False).encode()


def invoke(arguments, data):
    return subprocess.run(arguments, input=data, capture_output=True, timeout=10)


def run(args):
    if not __debug__:
        raise RuntimeError("run this verification without Python optimization flags")
    if os.name != 'posix':
        raise RuntimeError("this custody verification requires the Unix signer backend")
    repo = args.repo_root.resolve()
    binary_directory = args.binary_directory.resolve()
    oracle = args.canonical_oracle.resolve()
    report_path = args.report.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    start_sources = sources(repo)
    harness_hash = digest(__file__)
    oracle_hash = digest(oracle)
    binary_names = ['hepta-final-use-signer', 'hepta-final-use-approver',
                    'hepta-final-use-revocation-signer']
    binary_hashes = {name: digest(binary_directory / name) for name in binary_names}
    public_result = invoke([str(oracle)], compact([
        {'mode': 'sign', 'test_seed': seed, 'message': ''} for seed in (61, 62, 63)
    ]))
    assert public_result.returncode == 0, public_result.stderr.decode(errors='replace')
    public = json.loads(public_result.stdout)
    assert len(public) == 3
    cases = []
    oracle_verifications = []


    def refused(label, command, data):
        result = invoke(command, data)
        assert result.returncode != 0 and result.stdout == b'', (label, result.returncode)
        cases.append({'name': label, 'result': 'REJECTED', 'exit_code': result.returncode})


    def accepted(label, command, data, field, domain, public_info=None, classic_seed=None):
        result = invoke(command, data)
        assert result.returncode == 0, (label, result.stderr.decode(errors='replace'))
        signed = json.loads(result.stdout)
        message = domain + compact(signed[field])
        signature = bytes(signed['signature'])
        if public_info is not None:
            assert len(signature) == 3309
            spki = bytes.fromhex(public_info['spki'])
            key = serialization.load_der_public_key(spki)
            assert isinstance(key, mldsa.MLDSA65PublicKey)
            assert hashlib.sha256(b'TRNM/PoN/PQKey/v1\0' + spki).hexdigest() == public_info['key_id']
            key.verify(signature, message)
            oracle_verifications.append({'mode': 'verify', 'spki': public_info['spki'],
                'key_id': public_info['key_id'], 'message': message.hex(), 'signature': signature.hex()})
            try:
                key.verify(signature, b'wrong-domain\0' + message)
            except InvalidSignature:
                pass
            else:
                raise AssertionError(label + ': domain substitution accepted')
        else:
            assert len(signature) == 64
            ed25519.Ed25519PrivateKey.from_private_bytes(bytes([classic_seed]) * 32).public_key().verify(signature, message)
        cases.append({'name': label, 'result': 'ACCEPTED_AND_INDEPENDENTLY_VERIFIED',
                      'schema': signed[field]['schema_version'], 'signature_bytes': len(signature),
                      'stdout_bytes': len(result.stdout)})
        return signed


    with tempfile.TemporaryDirectory(prefix='hepta-pq-cli-') as directory:
        root = Path(directory)
        keys = []
        for seed in (61, 62, 63):
            path = root / ('seed-' + str(seed))
            path.write_bytes(bytes([seed]) * 32)
            path.chmod(0o600)
            keys.append(path)
        signer = [str(binary_directory / binary_names[0]), 'sign', '--key', str(keys[0])]
        approver = [str(binary_directory / binary_names[1]), 'approve', '--approver-id', 'operator', '--key', str(keys[1])]
        revoker = [str(binary_directory / binary_names[2]), 'sign', '--distributor-id', 'distributor', '--key', str(keys[2]),
                   '--issued-at-unix-ms', '1000', '--expires-at-unix-ms', '20000']
        commands = [signer, approver, revoker]
        pq = [command + ['--pq-key-id', info['key_id']] for command, info in zip(commands, public)]
        grant = {'schema_version': 2, 'signer_id': 'issuer', 'authority_epoch': 1,
                 'grant_id': 'cli-grant', 'nonce': [7] * 32,
                 'binding': {'subject_id': 'agent', 'destination_id': 'provider',
                             'request_sha256': [1] * 32, 'scope_sha256': [2] * 32,
                             'payload_sha256': [3] * 32},
                 'not_before_unix_ms': 1000, 'expires_at_unix_ms': 20000}
        grant_input = compact(grant)
        signed_grant = accepted('pq-grant', pq[0], grant_input, 'grant',
                               b'hepta.kernel.authority.final-use.pq.v2\0', public[0])
        assert signed_grant['grant'] == grant
        approval = accepted('pq-operator-approval', pq[1], grant_input, 'approval',
                            b'hepta.kernel.authority.final-use-approval.pq.v2\0', public[1])
        assert approval['approval']['schema_version'] == 2
        assert bytes(approval['approval']['grant_sha256']) == hashlib.sha256(
            b'hepta.kernel.authority.final-use.pq.v2\0' + compact(signed_grant['grant'])).digest()
        head = {'authority_epoch': 1, 'revision': 2, 'revoked_grant_ids': ['revoked-2', 'revoked-1']}
        update = accepted('pq-revocation-feed', pq[2], compact(head), 'update',
                          b'hepta.kernel.authority.revocation-feed.pq.v3\0', public[2])
        assert update['update']['schema_version'] == 3
        assert update['update']['head']['revoked_grant_ids'] == ['revoked-1', 'revoked-2']
        maximum_head = dict(head, revoked_grant_ids=[f'revoked-{n:03d}' for n in range(256)])
        accepted('pq-revocation-capacity-256', pq[2], compact(maximum_head), 'update',
                 b'hepta.kernel.authority.revocation-feed.pq.v3\0', public[2])
        too_many = dict(head, revoked_grant_ids=[f'revoked-{n:03d}' for n in range(257)])
        refused('pq-revocation-over-capacity', pq[2], compact(too_many))

        classical_grant = dict(grant, schema_version=1)
        accepted('classical-grant-compatible', signer, compact(classical_grant), 'grant',
                 b'hepta.kernel.authority.final-use.v1\0', classic_seed=61)
        accepted('classical-approval-compatible', approver, compact(classical_grant), 'approval',
                 b'hepta.kernel.authority.final-use-approval.v1\0', classic_seed=62)
        accepted('classical-feed-compatible', revoker, compact(head), 'update',
                 b'hepta.kernel.authority.revocation-feed.v2\0', classic_seed=63)
        for index, role in ((0, 'issuer'), (1, 'operator')):
            refused(role + '-classic-proposal-in-pq-mode', pq[index], compact(classical_grant))
            refused(role + '-pq-proposal-without-pq-mode', commands[index], grant_input)
            refused(role + '-unknown-grant-schema', pq[index], compact(dict(grant, schema_version=3)))
        for index, role in enumerate(('issuer', 'operator', 'feed')):
            data = compact(head) if index == 2 else grant_input
            refused(role + '-wrong-pinned-key', commands[index] + ['--pq-key-id', '00' * 32], data)
            refused(role + '-malformed-pin', commands[index] + ['--pq-key-id', '0' * 63], data)
            refused(role + '-unknown-flag', commands[index] + ['--not-a-profile', public[index]['key_id']], data)
        refused('grant-over-input-cap', pq[0], b' ' * 16385)
        refused('approval-over-input-cap', pq[1], b' ' * 16385)
        refused('feed-over-input-cap', pq[2], b' ' * (8 * 1024 * 1024 + 1))
        refused('unknown-grant-field', pq[0], compact(dict(grant, unauthorized=True)))
        refused('duplicate-grant-field', pq[0], b'{"schema_version":2,' + grant_input[1:])
        for label, content, mode in [('short-seed', bytes([61]) * 31, 0o600),
                                      ('long-seed', bytes([61]) * 33, 0o600),
                                      ('group-readable-seed', bytes([61]) * 32, 0o640)]:
            path = root / label
            path.write_bytes(content)
            path.chmod(mode)
            command = list(pq[0])
            command[3] = str(path)
            refused(label, command, grant_input)
        link = root / 'symlink-seed'
        link.symlink_to(keys[0])
        command = list(pq[0])
        command[3] = str(link)
        refused('symlink-seed', command, grant_input)
        original = root / 'hardlink-source'
        original.write_bytes(bytes([61]) * 32)
        original.chmod(0o600)
        link = root / 'hardlink-seed'
        os.link(original, link)
        command = list(pq[0])
        command[3] = str(link)
        refused('multiply-linked-seed', command, grant_input)
        fifo = root / 'fifo-seed'
        os.mkfifo(fifo, 0o600)
        command = list(pq[0])
        command[3] = str(fifo)
        refused('fifo-seed-does-not-block', command, grant_input)

    oracle_results = invoke([str(oracle)], compact(oracle_verifications))
    assert oracle_results.returncode == 0
    assert json.loads(oracle_results.stdout) == [{'accepted': True}] * len(oracle_verifications)
    end_sources = sources(repo)
    assert end_sources == start_sources, 'source drift during CLI execution'
    assert binary_hashes == {name: digest(binary_directory / name) for name in binary_names}, 'binary drift'
    assert harness_hash == digest(__file__), 'harness drift'
    assert oracle_hash == digest(oracle), 'oracle drift'
    report = {'result': 'PASS', 'cryptography': cryptography.__version__,
              'independent_backend': backend.openssl_version_text(),
              'binary_sha256': binary_hashes, 'source_sha256': end_sources,
              'harness_sha256': harness_hash, 'oracle_sha256': oracle_hash,
              'cases': cases, 'case_count': len(cases),
              'pq_outputs_cross_verified_by_canonical_oracle': len(oracle_verifications),
              'source_drift': [], 'elapsed_seconds': time.time() - started,
              'limits': ['Disposable deterministic keys and exact ASCII fixtures only.',
                         'CLI issuance and refusal are not production key-custody qualification.',
                         'This does not execute an application FinalUse consumer or establish whole-Hepta PQ readiness.']}
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ('result', 'case_count', 'pq_outputs_cross_verified_by_canonical_oracle', 'elapsed_seconds')}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[3],
        help="checkout used to build the binaries (defaults to this checkout)",
    )
    parser.add_argument("--binary-directory", type=Path, required=True)
    parser.add_argument("--canonical-oracle", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
