import hashlib
import json
import pathlib
import difflib

ROOT = pathlib.Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3')
CACHE = ROOT / 'exact-blob-cache'
CACHE.mkdir(exist_ok=True)


def identity(content):
    data = content.encode('utf-8') if isinstance(content, str) else content
    return {
        'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest(),
        'bytes': len(data),
        'sha256': hashlib.sha256(data).hexdigest(),
    }


def original(path, sha):
    data = pathlib.Path(path).read_bytes()
    assert identity(data)['git_blob'] == sha, (path, 'complete original hash')
    return json.loads(data)


def cache(content, expected):
    data = content.encode('utf-8')
    actual = identity(data)
    assert all(actual[key] == expected[key] for key in actual), expected
    destination = CACHE / actual['git_blob']
    if destination.exists():
        assert destination.read_bytes() == data
    else:
        with destination.open('xb') as output:
            output.write(data)
    return actual


baseline = original(ROOT / 'EXACT_55_RUST_OVERLAY.json', '7e777f92ca1d1b98466ecf9a8c0d05afa2c04f55')
original_source = original(ROOT / 'ORIGINAL_AGENTD_SRC_MAP.json', 'a27a9ae3949b8632bbcdbe59189081b200dc5165')['files']
current = {item['path']: dict(item) for item in baseline['rust_files']}
for item in baseline['non_rust_prepared']:
    current[item['path']] = {
        'path': item['path'], 'original_git_blob': item['before']['git_blob'],
        **item['after'], 'last_layer': 'original55-non-rust-preparation',
    }

specifications = [
    ('trusted-material-control', ROOT / 'TRUSTED_MATERIAL_CONTROL_PACKET.json', 'f8a645d5ce03d348a3b9f6cc3ce4d9f0e788f92e'),
    ('same-host-sc', pathlib.Path('/tmp/hepta-36fa-same-host-sc-capabilities-v1/SOURCE_PACKET.json'), '87c6707e499b5a85016198192c2bc3c7ae997e6b'),
    ('version-local', ROOT / 'VERSION_LOCAL_PACKET.json', '3de167eff0444e7dd8f0f32ade0444c1a8ff5925'),
    ('version-local-current', ROOT / 'VERSION_LOCAL_CURRENT_INCREMENT.json', '1f9af98ea25445d7ff732cbbd313399883165fb1'),
    ('same-host-sc-current', pathlib.Path('/tmp/hepta-36fa-same-host-sc-current-increment-v1/SOURCE_PACKET.json'), '484808c24b01b4c2c91b4698b2f31af304821f4e'),
    ('version-local-enum', pathlib.Path('/tmp/hepta-36fa-version-local-read-recovered-v1/purpose-enum-increment-v1/SOURCE_PACKET.json'), '39f9709423e09a445b9221dbdd3767bc9778d6c2'),
    ('selection-private-trait-doc', ROOT / 'S_TRAIT_DOCUMENTATION_INCREMENT.json', '31e260dde49f709ac5aac093304ee572a2621d3b'),
]
packets = []
for name, path, sha in specifications:
    packet = original(path, sha)
    for change in packet['changes']:
        before = change.get('before_text', change.get('before_content'))
        after = change.get('after_text', change.get('after_content'))
        if change['before'] is not None:
            cache(before, change['before'])
        else:
            assert before is None or before == ''
        cache(after, change['after'])
    packets.append((name, sha, packet))


def only_insertion(before, after, addition):
    assert after.count(addition) == 1, 'one complete exact guarded export block'
    assert after.replace(addition, '', 1) == before, 'whole-byte inverse'
    start = after.index(addition)
    assert before[:start] + addition + before[start:] == after
    return start, addition


operations = []
merge = None
for name, sha, packet in packets:
    for change in packet['changes']:
        path = change['path']
        before = change.get('before_text', change.get('before_content'))
        after = change.get('after_text', change.get('after_content'))
        prior = current.get(path)
        prior_sha = prior['git_blob'] if prior else original_source.get(path)
        expected_sha = change['before']['git_blob'] if change['before'] else None
        if name == 'version-local' and path == 'codex-rs/hepta-agentd/src/lib.rs':
            assert expected_sha == 'e4b140b7f9272313df6d243ff38caab4e68b97d8'
            assert prior_sha == '1296cc4e3265f31c2f30f95f589b8d59e1210a52'
            sc = (CACHE / prior_sha).read_text()
            sc_at, sc_insert = only_insertion(before, sc,
                '#[cfg(target_os = "linux")]\npub use learning_iteration_evidence_client::OriginalCircuitSelectionLocalReadbackV1;\n')
            version_at, version_insert = only_insertion(before, after,
                '#[cfg(target_os = "linux")]\npub use circuit_feature_current::OriginalCircuitPublishedLocalReadV1;\n')
            assert sc_at != version_at
            assert 'OriginalCircuitSelectionLocalReadbackV1' in sc_insert
            assert 'OriginalCircuitPublishedLocalReadV1' in version_insert
            assert 'cfg(target_os = "linux")' in sc_insert
            assert 'cfg(target_os = "linux")' in version_insert
            combined = before
            for position, addition in sorted([(sc_at, sc_insert), (version_at, version_insert)], reverse=True):
                combined = combined[:position] + addition + combined[position:]
            assert combined.count(sc_insert) == 1 and combined.count(version_insert) == 1
            assert combined.replace(sc_insert, '', 1).replace(version_insert, '', 1) == before
            actual = cache(combined, identity(combined))
            merge = {
                'path': path, 'original': expected_sha,
                'sc_standalone': prior_sha, 'version_standalone': change['after']['git_blob'],
                'merged': actual, 'insertions': [
                    {'original_character_position': sc_at, 'content': sc_insert},
                    {'original_character_position': version_at, 'content': version_insert},
                ],
                'inverse_restores_all_original_bytes': True,
            }
            (ROOT / 'ROOT_COMBINED_LIB.rs').write_text(combined)
            (ROOT / 'ROOT_COMBINED_LIB.diff').write_text(''.join(difflib.unified_diff(
                before.splitlines(keepends=True), combined.splitlines(keepends=True),
                fromfile='e4b140/lib.rs', tofile='combined/lib.rs')))
        else:
            assert prior_sha == expected_sha, (name, path, prior_sha, expected_sha)
            actual = change['after']
        original_sha = prior.get('original_git_blob') if prior else original_source.get(path)
        current[path] = {'path': path, 'original_git_blob': original_sha, **actual, 'last_layer': name}
        operations.append({'layer': name, 'packet': sha, 'path': path, 'before': prior_sha, 'after': actual['git_blob'], 'root_merge': merge is not None and merge['path'] == path and name == 'version-local'})

for path in baseline['explicit_removals']:
    assert path not in current

entries = sorted(current.values(), key=lambda value: value['path'])
needed = [item for item in entries if not (CACHE / item['git_blob']).exists()]
manifest = {
    'format': 'hepta-exact-composed-provider-local-capability-overlay-v1',
    'status': 'PREPARATION_NOT_FORMATTED_COMPILED_OR_EXECUTED',
    'source_commit': baseline['source_commit'], 'source_tree': baseline['source_tree'],
    'base_55_map': '7e777f92ca1d1b98466ecf9a8c0d05afa2c04f55',
    'original_agentd_map': 'a27a9ae3949b8632bbcdbe59189081b200dc5165',
    'input_packets': [{'layer': name, 'git_blob': sha} for name, sha, _ in packets],
    'all_packet_bytes_and_preimages_verified': True, 'operations': operations,
    'root_lib_merge': merge, 'explicit_removals': baseline['explicit_removals'],
    'rust_files': [item for item in entries if item['path'].endswith('.rs')],
    'non_rust_prepared': [item for item in entries if not item['path'].endswith('.rs')],
    'source_paths': sum(item['path'].endswith('.rs') for item in entries),
    'new_source_behaviors_qualified': False, 'real_qualified_task_chains': 0,
    'formatter_compiler_or_tests_run': False, 'source_ref_changed': False,
    'excluded_pending': ['New Version and S/C mechanism tests', 'Initial Root admission of actual A evidence', 'Three-UID harness mounts and full Fresh/daemon/Root integration', 'Complete registration/CALLERS/source gates', 'Original native gates'],
}
(ROOT / 'COMPOSED_OVERLAY_PENDING_FILES.json').write_text(json.dumps(manifest, indent=2, sort_keys=True)+'\n')
(ROOT / 'NEEDED_EXACT_BLOBS.json').write_text(json.dumps(needed, indent=2, sort_keys=True)+'\n')
print(json.dumps({'rust_paths': manifest['source_paths'], 'non_rust_paths': len(manifest['non_rust_prepared']), 'exact_operations': len(operations), 'root_lib_merge': merge['merged'], 'missing_base_blob_count': len(needed)}))
