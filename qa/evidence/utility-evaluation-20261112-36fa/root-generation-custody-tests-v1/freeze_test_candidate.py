"""Freeze source bytes and static metadata only. Never compile or execute Rust."""
import base64
import difflib
import hashlib
import json
from pathlib import Path
import re

ROOT = Path('/tmp/hepta-36fa-root-generation-custody-tests-v1')
PRODUCTION = Path('/tmp/hepta-36fa-root-generation-custody-coordinator-v1')
SOURCE = 'codex-rs/hepta-agentd/src/'
PARENT = SOURCE + 'circuit_q24_task_test_support.rs'
SUPPORT = SOURCE + 'neuron_generation_initial_root_custody_support_tests.rs'
TESTS = SOURCE + 'neuron_generation_initial_root_custody_tests.rs'
MOUNT = b'\n#[path = "neuron_generation_initial_root_custody_support_tests.rs"]\nmod root_initial_custody;\n'

def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def save(name, value):
    raw = (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()
    path = ROOT / name
    if path.exists():
        assert path.read_bytes() == raw, f'frozen artifact differs: {name}'
    else:
        path.write_bytes(raw)
    return pin(raw)

old = (ROOT / 'before' / PARENT).read_bytes()
assert pin(old)['git_blob'] == '661ec1c609ba0af1188dad00dd2910c7de4d2020'
assert (ROOT / 'after' / PARENT).read_bytes() == old + MOUNT
production_raw = (PRODUCTION / 'PRODUCTION_PACKET.json').read_bytes()
assert pin(production_raw)['git_blob'] == '3ffcac56096eb06214963ab1fdc5898e2b7eebb2'
production = json.loads(production_raw)
for change in production['source_changes']:
    raw = (PRODUCTION / 'after' / change['path']).read_bytes()
    assert pin(raw) == change['after']
    assert raw == base64.b64decode(change['after_base64'], validate=True)

graph = json.loads(Path('/tmp/hepta-36fa-full-candidate-graph-v1/CANDIDATE_FILE_GRAPH.json').read_bytes())
by_path = {r['path']: r for r in graph['files']}
assert by_path[PARENT]['git_blob'] == pin(old)['git_blob']
assert SUPPORT not in by_path and TESTS not in by_path
remote_refs = json.loads((ROOT / 'REMOTE_SOURCE_REFERENCES.json').read_bytes())
for ref in remote_refs:
    row = by_path[ref['path']]
    assert all(row[k] == ref[k] for k in ['bytes', 'sha256', 'git_blob'])

changes = []
patch = []
for path in sorted([PARENT, SUPPORT, TESTS]):
    before_path = ROOT / 'before' / path
    before = before_path.read_bytes() if before_path.exists() else None
    after = (ROOT / 'after' / path).read_bytes()
    changes.append({'path': path, 'mode': '100644',
                    'before': pin(before) if before is not None else None,
                    'before_text': before.decode() if before is not None else None,
                    'after': pin(after), 'after_text': after.decode()})
    patch.extend(difflib.unified_diff((before or b'').decode().splitlines(True),
                 after.decode().splitlines(True), fromfile='a/' + path if before is not None else '/dev/null',
                 tofile='b/' + path))
patch_text = ''.join(patch)
patch_path = ROOT / 'SOURCE_DELTA.patch'
if patch_path.exists():
    assert patch_path.read_text() == patch_text
else:
    patch_path.write_text(patch_text)

test_source = (ROOT / 'after' / TESTS).read_text()
support_source = (ROOT / 'after' / SUPPORT).read_text()
names = re.findall(r'^async fn (root_initial_custody_[a-z_]+)\(', test_source, re.M)
assert len(names) == 5 and len(set(names)) == 5
assert test_source.count('#[tokio::test') == 5
assert test_source.count('#[ignore = ') == 5
assert not re.search(r'\bassert(?:_eq|_ne)?!', test_source + support_source)
assert 'RootAuthorityDirectory::open(root_directory.path())?' in support_source
assert 'prepare_agentd_generation_initial_v1(' in support_source
assert '.providers.current' not in support_source + test_source
assert 'PreparedAgentdGenerationInitialV1::from_parts' not in support_source + test_source
assert 'CurrentStore::from_test_store' not in support_source + test_source
assert 'timeout(Duration::from_secs(5), worker).await???;' in support_source
assert 'let cleanup = session.finish().await;\n    result.and(cleanup)' in test_source
prefix = 'runtime::tests::circuit_task_ingress::q24_tests::support::root_initial_custody::tests::'
inventory = {'format': 'hepta-root-local-custody-test-inventory-v1',
 'status': 'PREPARED_NOT_COMPILED_OR_EXECUTED', 'test_count': len(names),
 'test_fqns': [prefix + n for n in names],
 'requires_original_root_ignored_selection': True, 'selected_or_executed': False,
 'mechanism_only': True, 'production_dependency': pin(production_raw),
 'module_path_sources': [r for r in remote_refs if r['path'].split('/')[-1] in
  ['runtime.rs', 'runtime_tests.rs', 'circuit_task_ingress_tests.rs', 'circuit_q24_task_ingress_tests.rs']],
 'parent_mount': {'path': PARENT, 'before': pin(old), 'after': pin(old + MOUNT), 'appended_utf8': MOUNT.decode()},
 'original_root_case_inventory': 'Not edited; Root must separately review/register these five ignored cases.'}
save('TEST_INVENTORY.json', inventory)
packet = {'format': 'hepta-original-root-local-custody-test-proposal-v1',
 'status': 'FROZEN_MECHANISM_TEST_CANDIDATE_PENDING_INDEPENDENT_REVIEW',
 'base_commit': '0c59aaca0b4932507f068c723f73da2f96729b3d',
 'production_dependency': pin(production_raw), 'source_changes': changes,
 'source_deletions': [], 'tests_added': len(names), 'original_tests_deleted': 0,
 'format_compile_test_H_calls': 0, 'active_source_or_ref_writes': 0,
 'scope': 'Five Root-only initial-custody mechanism cases; one original test parent append, two new test modules. No maintenance repair or production source is changed.'}
packet_pin = save('SOURCE_PACKET.json', packet)
static = {'format': 'hepta-root-local-custody-pure-byte-review-v1',
 'checks': {'parent_complete_prefix_equal': True, 'remove_exact_mount_restores_parent': True,
  'production_dependency_four_postimages_unchanged': True, 'five_ignored_root_cases_identified': True,
  'consumed_current_uses_original_root_factory': True, 'fixture_current_not_passed': True,
  'existing_signed_ingress_and_task_factory_used': True, 'no_panic_assertions_in_new_cases': True,
  'normal_result_path_explicitly_joins_before_returning_body_error': True},
 'pure_check_only': True, 'rust_compilation_or_execution': False,
 'limits': ['No actual post-CAS ACK-loss injection.',
  'No discarded-process cold recovery entry in v1; an independent v2 is required.',
  'Artifact, FinalUse and AuthBus use existing engineering fixture owners/issuers.',
  'Async cancellation has no completed-join evidence.',
  'No real useful task result, independent evaluation, or Root deployment claim.'],
 'source_packet': packet_pin, 'delta': pin(patch_text.encode()),
 'assertion_counts': {'ensure': test_source.count('anyhow::ensure!('),
                      'bail': test_source.count('anyhow::bail!(')}}
save('STATIC_REVIEW.json', static)
source_map = {c['path']: c['after']['git_blob'] for c in changes}
save('SOURCE_MAP.json', source_map)
metadata = ['SOURCE_PACKET.json', 'SOURCE_DELTA.patch', 'TEST_INVENTORY.json',
            'STATIC_REVIEW.json', 'SOURCE_MAP.json', 'REMOTE_SOURCE_REFERENCES.json',
            'REVIEW.md', 'freeze_test_candidate.py']
archive = []
for name in metadata + ['after/' + p for p in sorted(source_map)]:
    raw = (ROOT / name).read_bytes()
    assert len(raw) <= 512000
    archive.append({'name': name, 'path': str(ROOT / name), **pin(raw), 'chars': len(raw.decode())})
save('ARCHIVE_INPUTS.json', archive)
print(json.dumps({'source_packet': packet_pin, 'changes': len(changes), 'tests_added': len(names),
                  'source_map': source_map, 'archive_payload_count': len(archive)}, indent=2))
