#!/usr/bin/env python3
"""Freeze exact existing publication evidence and replay only offline verifiers."""

import base64
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile


WORKSPACE = Path('/workspace/scratch/07dd58cc9630')
PACKAGE = Path(__file__).resolve().parent
SNAPSHOT = PACKAGE / 'root'
CANDIDATE = Path('architecture-audit/b11-host-neither-observation-candidate-20261105/v3')
PUBLICATION = Path('hepta-audit-fifth/b11-observation-launcher-v3-publication')
ROOT_VERIFIER = Path('hepta-audit-fifth/verify_b11_observation_launcher_v3_publication.py')


def identity(body):
    return {'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest()}


def put(relative, body):
    target = SNAPSHOT / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    assert not target.exists() or target.read_bytes() == body
    target.write_bytes(body)


def normalize_candidate_replay(raw):
    value = json.loads(raw)
    for command in value['patch_roundtrip']:
        command['argv'] = [('<RESTORED_ROOT>/' + CANDIDATE.as_posix() + '/full.patch')
                           if arg.endswith('/' + CANDIDATE.as_posix() + '/full.patch') else arg
                           for arg in command['argv']]
    return value


def main():
    assert not SNAPSHOT.exists(), 'Do not overwrite a frozen snapshot'
    SNAPSHOT.mkdir(parents=True)
    candidate = WORKSPACE / CANDIDATE
    registry_raw = (candidate / 'delivery/registry.actual.json').read_bytes()
    assert identity(registry_raw)['git_blob'] == '24dfb6b7f3cd9b9374221390c3337a3d5acb420a'
    registry = json.loads(registry_raw)
    assert registry['listed_objects'] == 25 and registry['B11'] == 'OPEN'
    transport = json.loads((candidate / 'delivery/transport-manifest.json').read_bytes())
    parts = []
    for part in transport['base64_parts']:
        raw = (candidate / 'delivery/full-GET-originals' / (part['git_blob'] + '.json')).read_bytes()
        text = json.loads(raw)['content']
        actual = identity(text.encode())
        assert all(actual[key] == part[key] for key in actual)
        parts.append(text.strip())
    archive = base64.b64decode(''.join(parts), validate=True)
    assert identity(archive)['sha256'] == '4bf8ae10ffea2f083d50092211eaf8d239ad28cfe48652a150f76858f079f8bf'
    expected = {row['path']: row for row in transport['members']}
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as bundle:
        assert len(bundle.getmembers()) == 71
        for member in bundle.getmembers():
            assert member.isfile() and not member.name.startswith('/') and '..' not in Path(member.name).parts
            body = bundle.extractfile(member).read()
            actual = identity(body)
            assert all(actual[key] == expected[member.name][key] for key in actual)
            put(CANDIDATE / member.name, body)
    for name in ['registry.actual.json', 'registry.actual.receipt.json', 'registry.full-GET.original.json']:
        put(CANDIDATE / 'delivery' / name, (candidate / 'delivery' / name).read_bytes())

    publication_files = sorted((WORKSPACE / PUBLICATION).glob('*'))
    assert len(publication_files) == 11 and all(path.is_file() for path in publication_files)
    originals = publication_files + [WORKSPACE / ROOT_VERIFIER,
        WORKSPACE / 'hepta-audit-fifth/verify_main_format_retention_publication.py',
        WORKSPACE / 'hepta-audit-fifth/verify_b11_launcher_publication.py',
        WORKSPACE / 'hepta-audit-fifth/b11-host-neither-publication/intended-full-tree.json']
    captured = []
    for path in originals:
        body = path.read_bytes()
        relative = path.relative_to(WORKSPACE)
        put(relative, body)
        captured.append({'path': relative.as_posix(), **identity(body)})
    original_root_proof = (SNAPSHOT / PUBLICATION / 'root-tree-proof.json').read_bytes()
    proof = json.loads(original_root_proof)
    publication = proof['actual_publication']
    assert publication['source_commit'] == '87b8603f21e52063ed54ce89cba26756a3efaab7'
    assert publication['actual_PR_merge'] == '09960fe697c9c181e4a7d624e29b49360877b687'
    assert publication['tree'] == '9a804c7b6e0dd554cdb435f41e06c5c689fffaaf'
    assert proof['B11'] == 'OPEN'

    runs = []
    with tempfile.TemporaryDirectory(prefix='b11-v3-publication-restored-') as temporary:
        restored = Path(temporary) / 'root'
        shutil.copytree(SNAPSHOT, restored)
        commands = [
            [sys.executable, str(restored / ROOT_VERIFIER), '--root', str(restored)],
            [sys.executable, str(restored / CANDIDATE / 'independent-review/verify_independent.py'), str(restored / CANDIDATE)],
        ]
        for index, command in enumerate(commands):
            result = subprocess.run(command, cwd=restored, capture_output=True, check=False, timeout=60)
            (PACKAGE / f'replay-{index}.stdout.original.json').write_bytes(result.stdout)
            (PACKAGE / f'replay-{index}.stderr.original.txt').write_bytes(result.stderr)
            runs.append({'argv': command, 'exit_code': result.returncode,
                         'stdout': identity(result.stdout), 'stderr': identity(result.stderr)})
            assert result.returncode == 0 and result.stderr == b''
        assert (restored / PUBLICATION / 'root-tree-proof.json').read_bytes() == original_root_proof
        assert (restored / PUBLICATION / 'intended-full-tree.json').read_bytes() == (SNAPSHOT / PUBLICATION / 'intended-full-tree.json').read_bytes()
        assert normalize_candidate_replay((restored / PUBLICATION / 'candidate-static-root-replay.json').read_bytes()) == normalize_candidate_replay((SNAPSHOT / PUBLICATION / 'candidate-static-root-replay.json').read_bytes())
        assert (PACKAGE / 'replay-1.stdout.original.json').read_bytes() == (SNAPSHOT / CANDIDATE / 'independent-review/verification.stdout.json').read_bytes()
    for row in captured:
        actual = identity((WORKSPACE / row['path']).read_bytes())
        assert all(actual[key] == row[key] for key in actual)
    files = [{'path': path.relative_to(SNAPSHOT).as_posix(), **identity(path.read_bytes())}
             for path in sorted(SNAPSHOT.rglob('*')) if path.is_file()]
    assert len(files) == 89
    (PACKAGE / 'snapshot-manifest.json').write_text(json.dumps({
        'schema': 'b11-v3-publication-frozen-inputs', 'members': files,
        'candidate_registry_actual': '24dfb6b7f3cd9b9374221390c3337a3d5acb420a',
        'all_root_originals_preserved': captured, 'member_count': len(files),
        'snapshot_role': 'Complete portable input root for the original --root verifier. No product execution.'
    }, ensure_ascii=False, indent=2) + '\n')
    receipt = {
        'schema': 'b11-v3-publication-independent-restore-replay',
        'decision': 'ACTUAL_SOURCE_PUBLICATION_BOUND_NO_NATIVE_QUALIFICATION',
        'snapshot_members': len(files), 'candidate_original_archive_members': 71,
        'root_original_files': len(publication_files), 'root_scripts_and_parent_tree': 4,
        'root_verifier': identity((SNAPSHOT / ROOT_VERIFIER).read_bytes()),
        'restore_runs': runs, 'root_tree_proof_byte_identical': True,
        'full_intended_tree_byte_identical': True,
        'candidate_static_replay_equal_except_restore_path_in_git_apply_arguments': True,
        'independent_candidate_replay_stdout_byte_identical': True,
        'source_commit': publication['source_commit'], 'tree': publication['tree'],
        'parent': publication['parent'], 'actual_merge': publication['actual_PR_merge'],
        'actual_merge_parents': publication['actual_PR_merge_parents'],
        'actual_ref_readback_equal': publication['leased_ref_readback_equal'],
        'actual_full_PR_body_readback_equal': publication['full_PR_body_readback_equal'],
        'original_PR_body_preserved': publication['previous_PR_body_preserved_as_dated_history'],
        'changed_paths': proof['changed_paths'], 'unchanged_source_leaves': 10588,
        'all_root_original_bytes_unchanged_after_replay': True,
        'product_or_native_commands_executed': False, 'new_network_read': False,
        'ref_mutation_performed': False, 'B11': 'OPEN'
    }
    (PACKAGE / 'ROOT_REPLAY.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'members': len(files), 'source_commit': publication['source_commit'],
        'root_replay_exit': runs[0]['exit_code'], 'independent_replay_exit': runs[1]['exit_code'],
        'root_proof_byte_identical': True, 'B11': 'OPEN'}, indent=2))


if __name__ == '__main__':
    main()
