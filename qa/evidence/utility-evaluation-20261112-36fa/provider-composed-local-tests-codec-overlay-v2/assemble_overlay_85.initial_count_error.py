import hashlib
import json
import pathlib
import datetime

ROOT = pathlib.Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3')
CACHE = ROOT / 'exact-blob-cache'


def identity(content):
    data = content.encode('utf-8') if isinstance(content, str) else content
    return {'git_blob': hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest(),
            'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def load_original(name, expected):
    data = (ROOT/name).read_bytes()
    assert identity(data)['git_blob'] == expected, (name, 'exact Git preimage')
    return json.loads(data)


def remember(content, expected):
    data = content.encode('utf-8')
    actual = identity(data)
    assert all(actual[key] == expected[key] for key in actual), expected
    path = CACHE/actual['git_blob']
    if path.exists():
        assert path.read_bytes() == data
    else:
        with path.open('xb') as output:
            output.write(data)


base = load_original('EXACT_COMPOSED_OVERLAY_76.json', 'f4066cf562953650ae7a10129c9a90d496630fca')
agentd = load_original('ORIGINAL_AGENTD_SRC_MAP.json', 'a27a9ae3949b8632bbcdbe59189081b200dc5165')['files']
ledger = load_original('ORIGINAL_LEDGER_SRC_MAP.json', 'd0e417f969579fc1b724876ddf0e18dc041378d8')['files']
assert not set(agentd).intersection(ledger)
originals = {**agentd, **ledger}
current = {item['path']: dict(item) for item in base['rust_files']+base['non_rust_prepared']}
specs = [
    ('version-local-tests', 'VERSION_LOCAL_TEST_PACKET.json', '00c44402b24c92e344f1bd29a5e578fdfadaf940'),
    ('version-explicit-typed-receivers', 'VERSION_LOCAL_TYPED_CALL_INCREMENT.json', 'ebe3964d9db89eb8949a1d58f7d86ef99e4808d2'),
    ('same-host-sc-tests', 'SC_LOCAL_TEST_PACKET.json', '60c3d1ba12fdf43fd3e06ae5b3c6965e636e84d9'),
    ('selection-local-private-module', 'SELECTION_LOCAL_SOURCE_SPLIT_PACKET.json', '14966fb66ec1521c263323cf1db140251d141300'),
    ('original-ledger-snapshot-codec', 'ORIGINAL_LEDGER_SNAPSHOT_CODEC_PACKET.json', '3a7aee950bc6da48b4162f4f5215c4c5d18396b8'),
    ('ledger-codec-explicit-local-use', 'LEDGER_CODEC_LOCAL_USE_INCREMENT.json', '487e202226d32f9b7e98238703f66015fec59aae'),
]
operations = []
for layer, filename, sha in specs:
    packet = load_original(filename, sha)
    for change in packet['changes']:
        path = change['path']
        before = change.get('before_text', change.get('before_content'))
        after = change.get('after_text', change.get('after_content'))
        expected_before = change['before']['git_blob'] if change['before'] else None
        prior = current.get(path)
        actual_before = prior['git_blob'] if prior else originals.get(path)
        assert actual_before == expected_before, (layer, path, actual_before, expected_before)
        if change['before']:
            remember(before, change['before'])
        else:
            assert before is None or before == ''
        remember(after, change['after'])
        original_sha = prior.get('original_git_blob') if prior else originals.get(path)
        current[path] = {'path': path, 'original_git_blob': original_sha,
                         **change['after'], 'last_layer': layer}
        operations.append({'layer': layer, 'packet': sha, 'path': path,
                           'before': actual_before, 'after': change['after']['git_blob']})

entries = sorted(current.values(), key=lambda item: item['path'])
rust = [entry for entry in entries if entry['path'].endswith('.rs')]
nonrust = [entry for entry in entries if not entry['path'].endswith('.rs')]
assert len(rust) == 85 and len(nonrust) == 2, (len(rust), len(nonrust))
destination = ROOT/'overlay-local-tests-codec-v2'
verified = []
for entry in entries:
    data = (CACHE/entry['git_blob']).read_bytes()
    actual = identity(data)
    assert all(actual[key] == entry[key] for key in actual)
    target = destination/entry['path']
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        assert target.read_bytes() == data
    else:
        with target.open('xb') as output:
            output.write(data)
    assert target.read_bytes() == data
    verified.append({'path': entry['path'], **actual})
assert sorted(str(p.relative_to(destination)) for p in destination.rglob('*') if p.is_file()) == sorted(current)
for removed in base['explicit_removals']:
    assert removed not in current and not (destination/removed).exists()

manifest = {
    'format': 'hepta-exact-composed-provider-local-tests-codec-overlay-v2',
    'status': 'PREPARATION_NOT_FORMATTED_COMPILED_OR_EXECUTED',
    'source_commit': base['source_commit'], 'source_tree': base['source_tree'],
    'base_76_map': 'f4066cf562953650ae7a10129c9a90d496630fca',
    'original_agentd_map': 'a27a9ae3949b8632bbcdbe59189081b200dc5165',
    'original_ledger_map': 'd0e417f969579fc1b724876ddf0e18dc041378d8',
    'input_packets': [{'layer': layer, 'git_blob': sha} for layer, _, sha in specs],
    'all_packet_preimages_and_postimages_verified': True,
    'operations': operations, 'rust_files': rust, 'non_rust_prepared': nonrust,
    'source_paths': len(rust), 'local_overlay_directory': str(destination),
    'local_full_bytes_verified': True, 'explicit_removals': base['explicit_removals'],
    'unchanged_root_lib_merge': base['root_lib_merge'],
    'new_mechanism_test_methods': {'version_local': 7, 'selection_consumer_local': 7, 'pure_ledger_codec': 10},
    'test_method_counts_are_source_inventory_not_passes': True,
    'full_repository_materialized': False, 'format_compile_or_behavioral_tests_run': False,
    'source_ref_changed': False, 'qualification': False, 'real_qualified_task_chains': 0,
    'excluded_pending': ['First Root admission of actual A and original freeze',
                         'Full three-UID Fresh/daemon/Root orchestration and registration',
                         'Complete final CALLERS/protection and original source gates',
                         'Original formatting, lint, native and changed-ledger test scopes'],
}
(ROOT/'EXACT_COMPOSED_OVERLAY_85.json').write_text(json.dumps(manifest, indent=2, sort_keys=True)+'\n')
review = {'format': 'hepta-root-overlay85-local-byte-verification-v2',
          'observed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'checked_count': len(verified), 'checked': verified,
          'scope': '87 changed-source files only; not a full checkout or qualification',
          'new_layer_operations': len(operations), 'all_local_bytes_match': True,
          'no_extra_paths': True, 'source_ref_changed': False, 'qualification': False}
(ROOT/'LOCAL_OVERLAY_85_VERIFICATION.json').write_text(json.dumps(review, indent=2, sort_keys=True)+'\n')
print(json.dumps({'rust_files': len(rust), 'non_rust_files': len(nonrust),
                  'new_operations': len(operations), 'map': identity((ROOT/'EXACT_COMPOSED_OVERLAY_85.json').read_bytes()),
                  'local_directory': str(destination), 'qualification': False}))
