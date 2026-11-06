"""Cloud-only packaging of an exact, unexecuted archival Git request."""
from pathlib import Path
import ast
import base64
import hashlib
import json
import re
import zlib

HERE = Path(__file__).resolve().parent
WORK = HERE.parent.parent
REMOTE_TOOLS = '/home/qian-qi/work/hepta-actual-elf-git-transport-tools-20261105-93bfc-01'
KEY = '93bfc-hepta-h1-h2-h3-orphan-archive-git-transport-01'
CONFIG_ROOT = '/home/qian-qi/work/hepta-audit-ledger-fixture-fix-20261103/.git/'
CONFIGS = {
    CONFIG_ROOT + 'config': '24452f7031356ffbc08ab7fb9657efa5b67fb0b16b2a2ce704ec99d1514267b8',
    CONFIG_ROOT + 'worktrees/hepta-audit-provider-recovery-fix-20261103/config.worktree': 'bfefdfeb2bf56f4a5282c172fe3a69b4075e13fe3bf3cd54f6611bafa461c276',
    **{CONFIG_ROOT + 'worktrees/' + name + '/config.worktree': '443a5f645c23c3d0c0aa09f634b2ad111d46ef61946b598a2fb311678ab47454'
       for name in ('source1', 'source-h2', 'source-h3')},
}
EXPECTED = {
    'H1': ('034f518dc2bd8fd350d2cb7a322056300051c538382370089104a727f6c1341b', 32, 'export_retained_elfs.py'),
    'H2': ('d991a50f630e509278c20d5fe9f6ca0e53d1006852d954109d268375978407c1', 62, 'export_h2_retained_images.py'),
    'H3': ('93d7bf08914054e4bcf05f17eea3cd5ef36fac9bbf0d1e601dda59084e758cd3', 68, 'export_h3_retained_images.py'),
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def write(name, value):
    raw = value if isinstance(value, bytes) else encoded(value)
    (HERE / name).write_bytes(raw)
    return {'path': name, 'bytes': len(raw), 'sha256': sha(raw)}


def metadata_assignment(raw):
    nodes = [node for node in ast.walk(ast.parse(raw)) if isinstance(node, ast.Assign)
             and any(isinstance(target, ast.Name) and target.id == 'metadata_files' for target in node.targets)]
    assert len(nodes) == 1 and isinstance(nodes[0].value, ast.Dict)
    keys = [ast.unparse(key) for key in nodes[0].value.keys]
    assert keys == ["'export-plan.json'", "'exporter.py'", "plan['phase'] + '/original-source-map.json'", "'owned-release-proof.json'"]
    return ast.unparse(nodes[0])


def main():
    repo_raw = (HERE / 'repository-readonly.raw.json').read_bytes()
    repo = json.loads(repo_raw)['structuredContent']
    assert str(repo['id']) == '1320694176' and repo['repository_full_name'] == 'TrillionniumFoundation/hepta-private-ci'
    assert repo['visibility'] == 'public'
    archives, audit, paths = [], [], ['transport-index.json']
    total_raw = total_text = total_parts = 0
    for phase, (completion_sha, count, exporter_name) in EXPECTED.items():
        local = WORK / 'w1' / (phase.lower() + '-elf-export')
        completion_raw = (local / (phase + '-export-completion.json')).read_bytes()
        assert sha(completion_raw) == completion_sha
        actual = json.loads(completion_raw)
        plan_raw = (local / (phase + '-export-plan.json')).read_bytes()
        plan = json.loads(plan_raw)
        exporter_raw = (local / exporter_name).read_bytes()
        assert sha(plan_raw) == actual['plan_sha256']
        assert sha(exporter_raw) == actual['exporter_sha256']
        mapping = base64.b64decode(plan['source_map']['data_base64'], validate=True)
        assert len(mapping) == plan['source_map']['bytes'] and sha(mapping) == plan['source_map']['sha256']
        map_json = json.loads(mapping)
        assert map_json['source_commit'] == plan['source_commit'] and map_json['source_tree'] == plan['source_tree']
        release_phase = 'H3' if phase == 'H3' else 'H2'
        release_raw = (WORK / 'w1' / (release_phase + '-owned-release-probe') / 'proof.json').read_bytes()
        assert sha(release_raw) == plan['release_prerequisite']['sha256'] == actual['release_proof_sha256']
        root = plan['output_directory']
        assert root == '/home/qian-qi/work/hepta-' + phase.lower() + '-actual-elf-export-20261105-93bfc-01'
        assert actual['archive_path'] == root + '/' + plan['archive_name']
        assert actual['status'] == 'COMPLETE' and len(actual['parts']) == count
        offset = 0
        for number, part in enumerate(actual['parts']):
            assert part['index'] == number and part['offset'] == offset
            assert part['name'] == plan['archive_name'] + '.part-' + str(number).zfill(4)
            assert 0 < part['bytes'] <= 4194304 and re.fullmatch('[0-9a-f]{64}', part['sha256'])
            offset += part['bytes']
            total_text += 4 * ((part['bytes'] + 2) // 3)
            paths.append('archives/' + phase + '/parts/' + part['name'] + '.b64')
        assert offset == actual['archive_bytes']
        total_raw += offset
        total_parts += count
        metadata = {
            'export-plan.json': {'bytes': len(plan_raw), 'sha256': sha(plan_raw)},
            'exporter.py': {'bytes': len(exporter_raw), 'sha256': sha(exporter_raw)},
            phase + '/original-source-map.json': {'bytes': len(mapping), 'sha256': sha(mapping)},
            'owned-release-proof.json': {'bytes': len(release_raw), 'sha256': sha(release_raw)},
        }
        members = list(metadata) + ['export-index.json']
        for row in plan['files']:
            assert row['name'] == phase + '/elf/' + row['sha256'] + '.elf'
            members.append(row['name'])
        for row in plan.get('partial_prefixes', []):
            assert row['name'] == phase + '/partial/' + row['sha256'] + '.prefix-reference.json'
            assert row['complete_executable'] is False and row['completed_process_binding'] is False
            members.append(row['name'])
        assert len(members) == len(set(members))
        actual_h3_index_checked = False
        if phase == 'H3':
            index_raw = (local / 'H3-actual-export-index.json').read_bytes()
            assert sha(index_raw) == actual['archive_index_sha256']
            assert json.loads(index_raw)['embedded_metadata_files'] == metadata
            actual_h3_index_checked = True
        audit.append({
            'phase': phase, 'completion_sha256': completion_sha,
            'exporter_sha256': sha(exporter_raw), 'export_plan_sha256': sha(plan_raw),
            'four_embedded_metadata_files': metadata,
            'metadata_assignment_ast': metadata_assignment(exporter_raw),
            'source_map_keys': sorted(map_json), 'source_map_raw_sha256': sha(mapping),
            'allowed_archive_members': sorted(members),
            'actual_h3_index_metadata_independently_matches': actual_h3_index_checked,
            'credential_or_configuration_body_files_in_member_allowlist': False,
            'inspection_scope': 'Fixed exporter AST, raw plan/map/release bytes and exact member allowlist. ELF bytes are already approved retained binaries; this is not a generic secret scan or a new native claim.',
        })
        transport_completion = 'archives/' + phase + '/' + phase + '-export-completion.json'
        paths.append(transport_completion)
        archives.append({
            'phase': phase, 'source_root': root, 'completion_path': root + '/completion.json',
            'part_root': root, 'archive_path': actual['archive_path'],
            'completion_bytes': len(completion_raw), 'completion_sha256': completion_sha,
            'archive_bytes': actual['archive_bytes'], 'archive_sha256': actual['archive_sha256'],
            'archive_index_sha256': actual['archive_index_sha256'], 'parts': actual['parts'],
            'source_commit': plan['source_commit'], 'source_tree': plan['source_tree'],
            'original_native_outcome': actual['original_run_outcome'], 'capture_limits': actual['capture_limits'],
            'transport_completion_path': transport_completion,
            'remote_path_provenance': 'Exact completed exporter output_directory, archive_path, output/completion.json and output/part.name; cloud filenames are not used as remote paths.',
        })
    assert (total_parts, total_raw, total_text, len(paths)) == (162, 670306272, 893742124, 166)
    audit_record = write('metadata-allowlist-audit.json', {
        'schema': 'exact-existing-archive-member-scope-audit-v1', 'cloud_only': True,
        'repo_id': '1320694176', 'repo_visibility': 'public', 'archives': audit,
        'remote_archive_reexecution_or_recompression': False,
        'operator_key_files_or_credential_files_added': False,
    })
    plan = {
        'schema': 'actual-archive-orphan-git-transport-plan-v1', 'frozen': True,
        'publication_authorized': True,
        'authorization_scope': 'Root confirmed this existing public repository and these already approved ELF archives/metadata are within the session evidence-delivery authorization. This frozen request still requires separate root dispatch/window release; preparing it performs no upload.',
        'dispatch_status': 'NOT_DISPATCHED_REQUIRES_ROOT_RELEASE',
        'repository': 'TrillionniumFoundation/hepta-private-ci',
        'repository_visibility': {'repository_id': '1320694176', 'required': 'public', 'observed': 'public',
            'source_rpc_sha256': sha(repo_raw), 'public_read_does_not_prove_credentials_or_write_access': True},
        'destination_ref': 'refs/heads/evidence/actual-elf-transport-20261105-93bfc-01',
        'expected_ref_before': None, 'orphan_data_only': True,
        'route': 'canonical-base64-no-newline-per-original-part',
        'commit_date': '2026-11-05T23:59:13+00:00',
        'fixed_source': {'path': '/home/qian-qi/work/hepta-pq-effect-v4-20261105-93bfcf/source-h3',
                         'commit': '6db78eca53a5acdda0d96873d3f4cd65863426f0',
                         'tree': 'e91f5994017fc5d2cfe58d405a20ee6ad9376772',
                         'guard_sha256': 'e55f5ca1200b2c9fc5af4158c42f460e71f3815166a962a5b892acfe9477b1d1',
                         'tracked_files': 11840, 'tracked_bytes': 183410043},
        'protected_configurations': CONFIGS,
        'credential_bridge_sha256': sha((HERE / 'credential_get_only.py').read_bytes()),
        'script_sha256': sha((HERE / 'run_archive_transport.py').read_bytes()),
        'metadata_allowlist_audit': audit_record,
        'limits': {'outer_seconds': 1200, 'push_seconds': 900, 'ls_remote_seconds': 60,
                   'max_parts': total_parts, 'max_part_raw_bytes': 4194304,
                   'total_raw_bytes': total_raw, 'total_envelope_bytes': total_text},
        'budget_scope': 'A separate post-native archival transport component. No native timeout, test result, capture or learning budget is changed. Bootstrap, hashing, Git packing, one push and readback all consume the outer 1200 seconds.',
        'auth_policy': 'HTTPS only: reuse the existing HTTPS source origin and its existing HTTP settings/get-only helper. SSH, other protocols, credential writes/logging, new accounts, interactive auth, redirected destinations and hook suppression are rejected. Public ls-remote is not write/auth proof.',
        'uncertain_push_policy': 'Persist fsynced push-intent before the single empty-lease push. One exact-ref reconciliation only; never automatically retry. A ref confirmation still requires full independent cloud byte readback.',
        'archives': archives, 'expected_transport_paths': sorted(paths),
        'transport_tree_blob_count': 166,
        'no_pr_or_learning_or_native_or_existing_ref_mutation': True,
    }
    plan_record = write('transport-plan.json', plan)
    names = ['run_archive_transport.py', 'credential_get_only.py', 'transport-plan.json']
    expected = {name: sha((HERE / name).read_bytes()) for name in names}
    bundle = {'schema': 'sha-pinned-three-file-transport-bundle-v1', 'files': {
        name: base64.b64encode((HERE / name).read_bytes()).decode('ascii') for name in names}}
    bundle_raw = encoded(bundle)
    bundle_record = write('transport-bundle.json', bundle_raw)
    compressed = base64.b64encode(zlib.compress(bundle_raw, 9)).decode('ascii')
    bootstrap = f'''# Exact, reviewed archive-transport bootstrap; no source/credential/config edits.
import base64,hashlib,json,os,sys,zlib
from pathlib import Path
if sys.flags.optimize:
    raise RuntimeError('Optimization cannot disable bootstrap integrity assertions')
EXPECTED = {expected!r}
BUNDLE_SHA256 = {sha(bundle_raw)!r}
BUNDLE_BYTES = {len(bundle_raw)!r}
ENCODED = {compressed!r}
TOOLS = Path({REMOTE_TOOLS!r})
decoder=zlib.decompressobj()
raw=decoder.decompress(base64.b64decode(ENCODED,validate=True),BUNDLE_BYTES+1)
assert decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail
assert len(raw)==BUNDLE_BYTES and hashlib.sha256(raw).hexdigest()==BUNDLE_SHA256
bundle=json.loads(raw)
assert set(bundle['files'])==set(EXPECTED)
TOOLS.mkdir(mode=0o700,exist_ok=False)
for name in EXPECTED:
    data=base64.b64decode(bundle['files'][name],validate=True)
    assert hashlib.sha256(data).hexdigest()==EXPECTED[name]
    with (TOOLS/name).open('xb') as out:
        out.write(data);out.flush();os.fsync(out.fileno())
fd=os.open(TOOLS,os.O_RDONLY|os.O_DIRECTORY)
os.fsync(fd);os.close(fd)
os.execv('/usr/bin/python3',['/usr/bin/python3','-B',str(TOOLS/'run_archive_transport.py'),
    '--plan',str(TOOLS/'transport-plan.json'),'--expected-plan-sha256',EXPECTED['transport-plan.json'],
    '--expected-script-sha256',EXPECTED['run_archive_transport.py']])
'''.encode()
    bootstrap_record = write('bootstrap.py', bootstrap)
    request_record = write('launch-request.json', {
        'host': 'desktop', 'executable': '/usr/bin/python3', 'args': ['-B', '-'],
        'cwd': '/home/qian-qi/work', 'env': {'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONOPTIMIZE': '0'},
        'stdin': bootstrap.decode(), 'timeout_seconds': 1200, 'idempotency_key': KEY,
    })
    readme = f'''# Exact H1/H2/H3 archive transport request (not dispatched)

Target: `TrillionniumFoundation/hepta-private-ci` (ID 1320694176), **public**.
The approved content is existing retained ELF archives and their frozen metadata.
No operator-root files, credential files or configuration bodies are selected.
The four embedded metadata files per archive are explicitly audited in
`metadata-allowlist-audit.json`; the original index and ELF/member scope stay intact.

One new orphan data branch: `{plan['destination_ref']}`. It has 166 exact files:
162 original part envelopes, three original completion JSONs, one transport index.
Each original part becomes canonical base64 UTF-8 with **no newline** under
`archives/H1|H2|H3/parts/<original-name>.b64`. No split or recompression occurs.
Original data totals 670,306,272 bytes; envelopes total 893,742,124 bytes.
The biggest actual envelope is 5,592,408 bytes, already verified by root using
the connector and bounded local receiver; that separate probe is not a push result.

Remote completion paths are `<original-export-root>/completion.json`; original
parts are direct children of that same root. Cloud completion filenames differ.
The script reads/hash-checks original archives and parts, creates a new isolated
bare repository, hashes the exact 166-path tree and creates one parentless commit.
It fsyncs `prepared-data-commit.json` and `push-intent.json` before one empty-lease
push. Failure/unknown gets only the same-ref readback, never another push/account.
Public read reachability does not prove credentials or permission to push.

Existing HTTPS helper responses stay in memory; approve/store/erase are not
forwarded. Existing HTTPS authorization headers may also be used. This route is
HTTPS-only; an SSH origin is rejected with no protocol or identity fallback.
Embedded HTTPS userinfo and unexpected rewritten destinations are rejected.
Inherited nonempty hooks configuration or existing local hooks cause a failure for
review; hooks are not silently disabled. Five original Git configurations and
the entire fixed source are checked before and after. No source/CI/PR is changed.

The frozen request's new archival limit is 1200 seconds, including bootstrap and
the single push (at most 900 seconds). It does not change any native gate budget.
Root must approve this exact request and release the operational window before
dispatch. No desktop operation or upload has been performed by this package.
Afterward a confirmed ref still needs full independent cloud bytes/member verification.
H1/H2/H3 original failures and capture limitations remain unchanged.
'''.encode()
    write('README.md', readme)
    records = []
    for name in ['run_archive_transport.py','credential_get_only.py','test_transport_controls.py',
                 'build_transport_package.py','repository-readonly.raw.json','metadata-allowlist-audit.json',
                 'transport-plan.json','transport-bundle.json','bootstrap.py','launch-request.json','README.md']:
        raw = (HERE / name).read_bytes()
        records.append({'path': name, 'bytes': len(raw), 'sha256': sha(raw)})
    result = write('delivery-manifest.json', {'schema': 'unexecuted-archive-transport-delivery-v1',
        'status': 'FROZEN_FOR_ROOT_AND_INDEPENDENT_REVIEW_NOT_DISPATCHED', 'files': records,
        'idempotency_key': KEY, 'plan': plan_record, 'bundle': bundle_record,
        'bootstrap': bootstrap_record, 'request': request_record,
        'remote_operations': 0, 'push_attempts': 0, 'source_or_native_credit': False})
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
