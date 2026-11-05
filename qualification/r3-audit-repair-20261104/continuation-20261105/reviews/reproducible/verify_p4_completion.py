import base64
from collections import Counter
import datetime
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path('ci-audit/recovered-20261105/b16-ai395-cold-bootstrap-v1')
COMPLETION = ROOT / 'p4-readonly-completion-v4'
ORIGINALS = ROOT / 'p4-v3-catalog-readonly-export-v1/decoded-verified-v1'
OUTPUT = Path('hepta-audit-fifth/inputs/p4-completion-root-review.json')


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def check(raw, pin):
    actual = identity(raw)
    for key in actual:
        if key in pin:
            assert actual[key] == pin[key], (key, actual[key], pin[key])
    return actual


bundle_raw = (COMPLETION / 'complete-native-compressed-bundle.json').read_bytes()
bundle = json.loads(bundle_raw)
decoded = {}
for asset in bundle['assets']:
    assert asset['encoding'] == 'gzip-mtime0-base64'
    compressed = base64.b64decode(asset['data_base64'], validate=True)
    check(compressed, asset['compressed'])
    raw = gzip.decompress(compressed)
    check(raw, asset['original'])
    assert (COMPLETION / 'originals' / asset['name']).read_bytes() == raw
    assert asset['name'] not in decoded
    decoded[asset['name']] = raw
assert len(decoded) == 14 and sum(map(len, decoded.values())) == bundle['original_bytes'] == 730542
terminal = json.loads(decoded['terminal.json'])
baseline = json.loads(decoded['new-host-build-only-baseline.json'])
prior = json.loads((ORIGINALS / 'terminal.json').read_bytes())
catalog = json.loads((ORIGINALS / '03-full-unfiltered-catalog.stdout.original').read_bytes())
request = json.loads((ORIGINALS / 'request.original.json').read_bytes())
assert terminal['success'] and terminal['errors'] == []
assert not any(terminal[key] for key in ('B_source_applied', 'build_or_list_repeated', 'tests_executed', 'test_qualification'))
assert terminal['original_commands'] == prior['commands'] == baseline['commands']
assert terminal['original_source_guards'] == prior['source_guards'] == baseline['source_guards']
assert baseline['role'] == 'BUILD_ONLY_CURRENT_HOST' and not baseline['tests_executed'] and not baseline['test_qualification']
assert baseline['source_tree'] == terminal['source_tree'] == '4a3374e22e16ce5c764288ad018cd9affadf94ea'
assert baseline['source_commit'] == terminal['source_commit'] == '20fd174ded4e5ce01bda34e4f6d1d74803301f49'
assert baseline['host'] == json.loads((ORIGINALS / 'host.original.json').read_bytes())
assert baseline['environment'] == json.loads((ORIGINALS / 'effective-task-environment.json').read_bytes())
assert baseline['catalog'] == prior['commands'][2]['stdout'] and baseline['metadata'] == prior['commands'][1]['stdout']
assert baseline['tools'] == prior['tools'] == json.loads(decoded['tools-initial.json'])
assert baseline['readonly_completion']['original_commands_not_repeated']
assert baseline['readonly_completion']['original_six_source_guards_unchanged']
assert baseline['future_B_execution_requires_separate_enabled_binding']
check(decoded['new-host-build-only-baseline.json'], terminal['build_only_baseline'])
check((ORIGINALS / 'terminal.json').read_bytes(), terminal['prior_failed_controller_terminal'])
for pin in terminal['records']:
    check(decoded[Path(pin['path']).name], pin)
assert len(terminal['records']) == 13

for sdk in ('openssl', 'libcap'):
    for side in ('initial', 'final'):
        name = f'completion-{side}.{sdk}-sdk-guard.json'
        check(decoded[name], terminal[f'{sdk}_{side}_guard'])
        assert decoded[name] == (ORIGINALS / f'initial.{sdk}-sdk-guard.json').read_bytes()
guards = [json.loads(decoded[f'completion-{side}.guard.json']) for side in ('initial', 'final')]
for guard in guards:
    assert guard['head'] == baseline['source_commit']
    assert guard['head_tree'] == guard['working_tree'] == baseline['source_tree']
    assert not guard['untracked'] and guard['ordinary_index'] == baseline['ordinary_index']
assert guards[0]['guarded_files'] == guards[1]['guarded_files']
assert baseline['ordinary_index']['sha256'] == '6b39b6b27d164001c9b130487d0d7879be5f80e22a4579d06fd472c2bb8d7ac0'
assert set(baseline['locks']) == {'codex-rs/Cargo.lock', 'MODULE.bazel.lock'}
for pin in baseline['locks'].values():
    assert pin in guards[1]['guarded_files']
assert {pin['path'] for pin in baseline['recipe_sources']} == {
    'AGENTS.md', 'codex-rs/rust-toolchain.toml', 'codex-rs/.cargo/config.toml', 'justfile',
    'scripts/run-nextest.py', 'scripts/check-module-bazel-lock.sh', '.bazelrc', 'defs.bzl'}

programs, helpers = baseline['programs_after_catalog'], baseline['helpers_after_catalog']
assert programs == json.loads(decoded['programs-current-after-catalog.json'])
assert helpers == json.loads(decoded['helpers-current-after-catalog.json'])
assert len(programs) == 363 and len(helpers) == 33
assert len({pin['path'] for pin in programs}) == 363 and len({pin['path'] for pin in helpers}) == 33
for pin in programs + helpers:
    assert Path(pin['path']).is_relative_to(baseline['target_directory'])
    assert pin['bytes'] > 0 and len(pin['sha256']) == 64 and len(pin['git_blob']) == 40
    assert int(pin['mode'], 8) & 0o111
for pin in programs:
    suite = catalog['rust-suites'][pin['binary_id']]
    for left, right in [('binary_name', 'binary-name'), ('package_name', 'package-name'),
                        ('kind', 'kind'), ('build_platform', 'build-platform'), ('path', 'binary-path')]:
        assert pin[left] == suite[right]
assert Counter(Path(pin['path']).name for pin in helpers) == Counter(request['expected_helper_basename_roster'])
normal_before = json.loads((ORIGINALS / 'normal-six-before-catalog.json').read_bytes())['artifacts']
assert baseline['normal_helpers_before_catalog'] == normal_before
normal_after = json.loads(decoded['normal-six-current-after-catalog.json'])
assert baseline['normal_helpers_after_catalog'] == normal_after and len(normal_after) == 6
helper_map = {pin['path']: pin for pin in helpers}
changes = []
for before, after in zip(normal_before, normal_after, strict=True):
    assert before['target'] == after['target'] and before['path'] == after['path']
    assert {key: value for key, value in after.items() if key != 'target'} == helper_map[after['path']]
    if (before['bytes'], before['sha256']) != (after['bytes'], after['sha256']):
        changes.append(before['target'])
assert baseline['normal_helper_initial_hashes_preserved_after_catalog'] is (not changes)
assert baseline['case_roster_counts'] == {'eligible': 19506, 'ignored': 57}
assert baseline['case_roster_sha256'] == request['complete_A_case_roster_sha256']
assert terminal['capacity_final']['available_bytes'] >= 64000000000
review = {
    'schema': 'hepta-root-P4-readonly-completion-review-v1',
    'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'verdict': 'ACCEPT_CURRENT_HOST_BUILD_ONLY_BASELINE_FOR_SEPARATELY_BOUND_FOUNDATION',
    'bundle': identity(bundle_raw), 'baseline': identity(decoded['new-host-build-only-baseline.json']),
    'terminal': identity(decoded['terminal.json']),
    'full_original_files': 14, 'full_original_bytes': 730542,
    'reconstruction_methods_preserved': bundle['reconstruction_methods'],
    'verified': {
        'three_successful_original_commands_not_repeated': True,
        'original_failed_controller_unchanged': True,
        'current_program_identity_records': 363, 'current_helper_identity_records': 33,
        'all_current_paths_and_roles_match_complete_catalog': True,
        'original_six_pre_catalog_hash_records_preserved': True,
        'current_six_post_catalog_hashes_match_helpers': True,
        'normal_helpers_changed_during_original_full_catalog': changes,
        'two_sdk_initial_final_guards_match_original_native_bytes': True,
        'source_host_environment_tools_index_locks_and_eight_recipes_bound': True,
        'free_bytes_at_completion': terminal['capacity_final']['available_bytes'],
    },
    'scope_limits': [
        'Current physical file identities were measured by the native read-only completion; cloud independently verifies complete native records and relations.',
        'Historical pre-catalog helper hashes are retained, including real changes caused by the full catalog build.',
        'No native B source or tests have run; future foundation requires its exact input and launcher binding.',
        'BUILD_ONLY is not test qualification or closure of B16.',
    ],
    'tests_executed': False, 'test_qualification': False,
}
OUTPUT.write_text(json.dumps(review, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'path': str(OUTPUT), **identity(OUTPUT.read_bytes()), 'verdict': review['verdict'],
                  'changed_normal_helpers': changes}))
