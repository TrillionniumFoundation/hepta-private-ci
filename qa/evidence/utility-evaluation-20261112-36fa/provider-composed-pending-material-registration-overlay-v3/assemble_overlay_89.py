#!/usr/bin/env python3
"""Compose exact prepared layers; this does not execute or qualify candidate code."""
import datetime
import hashlib
import json
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3')
OUT = ROOT / 'overlay-pending-material-registration-v3'


def identity(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


def read_packet(path, expected):
    data = path.read_bytes()
    assert identity(data)['git_blob'] == expected, str(path)
    return json.loads(data)


base = read_packet(ROOT / 'EXACT_COMPOSED_OVERLAY_86.json', '3f7d40d4933669da33d2aef3491efb431c5771ae')
directories = json.loads((ROOT / 'REGISTRATION_CANONICAL_PREIMAGE_DIRECTORIES.json').read_bytes())
canonical = {e['path']: e['sha'] for directory in directories['actual_gets'] for e in directory['entries']}
files = {}
content = {}
for row in base['rust_files'] + base['non_rust_prepared']:
    path = row['path']
    data = (ROOT / 'overlay-local-tests-codec-v2' / path).read_bytes()
    assert all(identity(data)[k] == row[k] for k in identity(data)), path
    files[path] = dict(row)
    content[path] = data

layers = [
    ('original-decision-outcome-retention', ROOT / 'first-material-successor/RETENTION_SOURCE_PACKET.json', 'd656853ee0fb0e4bf7aedbd371916607d7dcb619'),
    ('first-pending-material-admission', ROOT / 'first-material-successor/PENDING_SOURCE_PACKET.json', '641999aa0c288941e17d343c3fabeb48b93e0eae'),
    ('preheld-material-deadline-cleanup', ROOT / 'first-material-successor/DEADLINE_SOURCE_PACKET.json', '7e7469819f3729305d6da386d6ae000e157b5925'),
    ('provider-registration-root86', ROOT / 'registration-86-git-reconstruction/SOURCE_PACKET.json', 'fab488b846bb1b1ef7a42b9b30be5773054e1a6a'),
]
operations = []
for name, location, expected in layers:
    packet = read_packet(location, expected)
    for change in packet.get('changes', packet.get('source_changes', [])):
        path = change['path']
        assert change['mode'] == '100644', path
        before = change.get('before')
        before_text = change.get('before_text', change.get('before_content'))
        after_text = change.get('after_text', change.get('after_content'))
        if before is None:
            assert before_text in (None, ''), path
            assert path not in files and path not in canonical, path
            original = None
        else:
            assert identity(before_text.encode()) == before, path
            if path in files:
                assert content[path] == before_text.encode(), path
                assert files[path]['git_blob'] == before['git_blob'], path
                original = files[path].get('original_git_blob')
            else:
                assert name == 'provider-registration-root86', path
                assert canonical.get(path) == before['git_blob'], path
                original = before['git_blob']
        after = after_text.encode()
        assert identity(after) == change['after'], path
        content[path] = after
        files[path] = dict(change['after'], path=path, original_git_blob=original, last_layer=name)
        operations.append({'layer': name, 'packet': expected, 'path': path,
                           'before': before, 'after': change['after'], 'exact_preimage_and_postimage_verified': True})

for path, data in content.items():
    dest = OUT / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        assert dest.read_bytes() == data, path
    dest.write_bytes(data)
    assert identity(dest.read_bytes()) == identity(data), path

rows = [files[path] for path in sorted(files)]
rust = [row for row in rows if row['path'].endswith('.rs')]
nonrust = [row for row in rows if not row['path'].endswith('.rs')]


def classify(group):
    return {
        'new': sum(r.get('original_git_blob') is None for r in group),
        'modified': sum(r.get('original_git_blob') is not None and r['original_git_blob'] != r['git_blob'] for r in group),
        'unchanged_original': sum(r.get('original_git_blob') == r['git_blob'] for r in group),
    }


assert len(rust) == 89 and len(nonrust) == 20 and len(operations) == 28
assert classify(rust) == {'new': 46, 'modified': 42, 'unchanged_original': 1}
assert classify(nonrust) == {'new': 2, 'modified': 18, 'unchanged_original': 0}
result = {
    'format': 'hepta-exact-composed-pending-material-registration-overlay-v3',
    'status': 'Prepared exact source coverage; not formatted, compiled, tested, deployed or qualified',
    'source_commit': base['source_commit'], 'source_tree': base['source_tree'],
    'base_86_map': '3f7d40d4933669da33d2aef3491efb431c5771ae',
    'layers': [{'name': name, 'packet': sha} for name, _, sha in layers],
    'operations': operations,
    'rust_files': rust, 'non_rust_prepared': nonrust,
    'rust_source_coverage': len(rust), 'non_rust_source_coverage': len(nonrust),
    'rust_classification': classify(rust), 'non_rust_classification': classify(nonrust),
    'explicit_removals': base['explicit_removals'],
    'local_overlay_directory': str(OUT),
    'local_full_bytes_verified': True, 'all_packet_preimages_and_postimages_verified': True,
    'canonical_newly_covered_preimages_checked_against_actual_complete_directory_gets': True,
    'conditional_inventory_arithmetic_only': {
        'tracked_or_physical_full_source_files': 15188 + 48 - 1,
        'rust_source_files': 6619 + 46 - 1,
        'meaning': 'Conditional on the unchanged full cc57 source and the explicit old helper removal; this is not a physical full-repository inventory or full caller scan.'
    },
    'qa_preservation_scope': {
        'relative_to_frozen_root86_inputs': {'existing_methods': 590, 'raw_text_unchanged': 587, 'explicit_migrations': 3},
        'relative_to_canonical_cc57': {'existing_methods': 590, 'raw_text_unchanged': 586, 'explicit_migrations': 4},
        'prior_layer_difference': 'Root86 input 822326 already changed test_existing_ci_really_selects_root_cases_neuron_and_full_caller_proof before the registration packet.',
        'new_source_closure_methods_prepared': 14,
        'none_of_these_counts_is_a_test_execution_result': True
    },
    'current_blockers': [
        'Full three-UID pre-held task/configuration and A/T custody wiring are not implemented by this overlay.',
        'VersionFixture uses test Current/FileCAS and a fixture issuer. A production RootAuthorityDirectory/Current owner cannot be manufactured by a UID60001 child or recreated from JSON; the original Root custody and typed cross-process interface still require explicit engineering.',
        'No original E/D/T through actual Root, independent B, new C or daemon/Root cold recovery has run for this prepared source.',
        'Original fmt, scoped fix, full source closure and unchanged native tests still require a fresh exact materialization and available original runtime resources.'
    ],
    'full_repository_materialized': False, 'format_compile_or_behavioral_tests_run': False,
    'source_ref_changed': False, 'qualification': False, 'real_qualified_task_chains': 0,
    'written_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
}
(ROOT / 'EXACT_COMPOSED_OVERLAY_89.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
print(json.dumps({'map': identity((ROOT / 'EXACT_COMPOSED_OVERLAY_89.json').read_bytes()),
                  'paths': len(rows), 'rust': len(rust), 'non_rust': len(nonrust),
                  'rust_classification': classify(rust), 'non_rust_classification': classify(nonrust)}))
