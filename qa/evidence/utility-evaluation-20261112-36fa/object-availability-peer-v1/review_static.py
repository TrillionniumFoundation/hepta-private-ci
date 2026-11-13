#!/usr/bin/env python3
"""Pure offline observer review: only its three pure Merkle helpers are evaluated."""
from pathlib import Path
import ast
import hashlib
import json
import pathlib

OUT = Path(__file__).resolve().parent
ROOT = Path('/tmp/hepta-36fa-cc57-isolated-recovery-plan-v1')


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def main():
    script = (ROOT / 'OBJECT_AVAILABILITY.HOLD.py').read_bytes()
    request_raw = (ROOT / 'REQUEST.HOLD.json').read_bytes()
    plan_raw = (ROOT / 'PLAN.HOLD.md').read_bytes()
    assert pin(script)['git_blob'] == '2063cdf273dc9c848b373b152ed455ee1e0d6f14'
    assert pin(request_raw)['git_blob'] == '04c4ce7cec0528da1492934a6d859b77798f6a03'
    request = json.loads(request_raw)
    assert set(request) == {'host', 'executable', 'args', 'cwd', 'idempotency_key', 'timeout_seconds'}
    assert request['args'] == ['-B', '-c', script.decode()]
    assert request['host'] == 'desktop' and request['executable'] == '/usr/bin/python3'
    assert request['cwd'] == '/home/qian-qi' and request['timeout_seconds'] == 60
    assert request['idempotency_key'] == 'hepta-utility-36fa-cc57-snapshot-objects-readonly-v1'
    parsed = ast.parse(script)
    constants = {}
    for node in parsed.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                constants[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    helpers = [node for node in parsed.body if isinstance(node, ast.FunctionDef)
               and node.name in {'check', 'oid', 'expected_objects'}]
    assert len(helpers) == 3
    namespace = {'pathlib': pathlib, 'hashlib': hashlib, 'TREE': constants['TREE'],
                 'HEAD': constants['HEAD'], 'COMMIT': constants['COMMIT']}
    exec(compile(ast.Module(body=helpers, type_ignores=[]), '<three-pure-merkle-helpers>', 'exec'), namespace)
    inventory_path = Path('/tmp/hepta-36fa-source-repair-canonical-packet-v1/CANONICAL_CLEAN_INVENTORY.expected.json')
    inventory_raw = inventory_path.read_bytes()
    assert pin(inventory_raw)['sha256'] == constants['INVENTORY_RAW']['sha256']
    assert len(inventory_raw) == constants['INVENTORY_RAW']['bytes']
    inventory = json.loads(inventory_raw)
    objects, trees = namespace['expected_objects'](inventory)
    assert len(objects) == 16439 and len(trees) == 1828
    missing = {row['path']: row for row in inventory['files'] if row['path'] in constants['MISSING_PATHS']}
    assert len(missing) == 7 and sum(row['bytes'] for row in missing.values()) == 18176884
    required = set(trees) | {constants['HEAD']} | {row['working_blob'] for row in missing.values()}
    assert len(required) == 1836
    commit_path = Path('/tmp/hepta-36fa-source-repair-canonical-packet-v1/CANONICAL_COMMIT.raw')
    commit_raw = commit_path.read_bytes()
    assert len(commit_raw) == constants['COMMIT']['bytes']
    assert hashlib.sha256(commit_raw).hexdigest() == constants['COMMIT']['sha256']
    assert namespace['oid']('commit', commit_raw) == constants['HEAD']
    headers = commit_raw.split(b'\n\n', 1)[0].splitlines()
    assert [x for x in headers if x.startswith(b'tree ')] == [('tree ' + constants['TREE']).encode()]
    assert [x for x in headers if x.startswith(b'parent ')] == [('parent ' + constants['PARENT']).encode()]
    environment_path = Path('/tmp/hepta-36fa-checkpoint1867-recovery/runtime-v2-environment.original.json')
    environment_raw = environment_path.read_bytes()
    assert pin(environment_raw)['git_blob'] == '8b62ac16f554c1f34ee72974637752f5a3b58aec'
    git_original = json.loads(environment_raw)['tool_and_material_files']['tool_git']
    assert git_original['nlink'] == 1 and git_original['uid'] == 0 and git_original['mode'] == 0o755
    assert {key: git_original[key] for key in ('bytes', 'sha256')} == constants['GIT_PIN']
    report = {
        'format': 'hepta-cc57-object-availability-independent-peer-v1',
        'status': 'NO_BLOCKING_FINDING_FOR_EXACT_READONLY_OBSERVER',
        'subject': {'script': pin(script), 'request': pin(request_raw), 'plan': pin(plan_raw)},
        'offline_inputs': {'inventory': {'path': str(inventory_path), **pin(inventory_raw)},
                           'commit_raw': {'path': str(commit_path), **pin(commit_raw)},
                           'historical_runtime_environment': {'path': str(environment_path), **pin(environment_raw)}},
        'request': {'six_exact_fields': True, 'inline_script_equal': True, 'no_env_payload': True,
                    'outer_timeout_seconds': 60, 'action_deadline_seconds': 45,
                    'key': request['idempotency_key']},
        'independent_merkle': {'tree': constants['TREE'], 'leaf_count': 15188,
                               'unique_blob_objects': 14610, 'unique_tree_objects': 1828,
                               'unique_snapshot_objects_with_commit': 16439,
                               'required_full_body_objects': 1836,
                               'seven_archive_blob_bytes': 18176884,
                               'commit_type': 'commit', 'commit_oid': constants['HEAD'],
                               'commit_bytes': 916, 'parent': constants['PARENT']},
        'bounded_code_review': [
            'Only retained canonical inventory, four fixed old Git metadata files, the original Git executable and exact Git objects are read. No current physical working source payload is read by this observer.',
            'Fixed path inputs use real directory ancestors, O_RDONLY/O_NOFOLLOW, regular-file ownership, exact sizes/hashes and before/after stable stat. Index bytes are hashed but never emitted.',
            'Git inherited identity/object/config override variables are rejected. Prefix retains --no-optional-locks and disables fsmonitor/untrackedCache.',
            'Only for-each-ref, cat-file --batch-check and cat-file --batch are invoked. No restore/reset/read-tree/update-index/update-ref/hash-object/write-tree/fetch, shell or Cargo invocation is present.',
            'Expected B7 tree bodies are derived with canonical Git entry ordering from the exact 13d3 inventory. Repeated blob/tree identities must agree.',
            'Every metadata row is paired with its requested OID, exact type and size. Missing/wrong-type/wrong-size outcomes remain explicit, not silently omitted.',
            'Available selected bodies are fully checked for exact header, byte count, separator, raw Git SHA, SHA256, tree bytes, and original commit tree/ordered parent headers.',
            'Anonymous memfds carry request and stderr bytes; no source or evidence file is opened for writing. Stdout is the only retained result transport.',
            'Select/read/wait use the remaining 45-second action budget. Ordinary Git observations use at most min(15,remaining). Finally kills and waits only for this observer\'s own cat-file child, with bounded 5-second cleanup and explicit unknown child-terminal if cleanup cannot observe completion.',
            'Completed status requires the four old metadata records, exact existing ref output, index raw bytes, absent lookup paths and Git executable observations to agree before/after. It does not require old worktree cleanliness or erase the known ref.',
        ],
        'system_git_single_link_observation': {
            'existing_actual_record_supports_nlink_1': True,
            'observation': git_original,
            'interpretation': 'An original detailed ENV_READY observation supplies nlink=1, unlike the five-field projection alone. It is historical evidence; the observer must still check the current executable and can fail if it changed. No new H lookup or extra condition was invented by this peer.',
        },
        'failure_and_success_scope': {
            'normal_exit_means_observation_completed_only': True,
            'missing_objects_may_yield_completed_with_availability_false': True,
            'materialization_requires_separate_explicit_approval_and_actual_proof': True,
            'qualification_not_executed_or_approved_by_this_review': True,
            'old_1cd4_failure_preserved': True,
            'no_writer_attribution_from_timestamps_or_hashes': True,
        },
        'limitations': [
            'Only the exact one-snapshot closure is considered; no full parent history or fsck assertion.',
            'All 1828 trees, seven archive blobs and cc57 commit are fully hashed only if they are locally available; unavailable entries remain false. Other blob bodies are metadata-only in this observer.',
            'The observer does not certify the current 15181 physical source files; later materialization must fully reread them.',
            'No proposed observer top-level/native path was executed by this peer. Only three pure AST-extracted Merkle helpers were evaluated against local immutable bytes.',
        ],
        'H_calls': 0, 'tests_or_qualification_executed': False,
        'source_index_ref_control_mutations': False, 'blocking_findings': [],
    }
    raw = (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
    with (OUT / 'REVIEW.json').open('xb') as stream:
        stream.write(raw)
    print(json.dumps({'review': str(OUT / 'REVIEW.json'), **pin(raw)}, sort_keys=True))


if __name__ == '__main__':
    main()
