"""Freeze the reviewed AWS port and its existing execution evidence.

This script does not build, test, modify the production workspace, or fetch data.
"""

from pathlib import Path
import datetime
import difflib
import hashlib
import json
import re
import shutil
import tomllib


ROOT = Path('/workspace/scratch/95988d8d3ab1')
WORK = ROOT / 'ndu-dependency-remediation/aws-login-port'
HERE = Path(__file__).resolve().parent
EVIDENCE = HERE / 'evidence'
TESTED = WORK / 'proposed/codex-rs/third_party/aws-config-1.8.12'
VENDOR = WORK / 'candidate-root/codex-rs/third_party/aws-config-1.8.12'
UPSTREAM = WORK / 'upstream-002/source/aws-config-1.8.12'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def file_record(path, relative_to):
    return {'path': str(path.relative_to(relative_to)), 'bytes': path.stat().st_size, 'sha256': sha(path)}


EVIDENCE.mkdir(exist_ok=True)
handoff = json.loads((WORK / 'CANDIDATE_HANDOFF.json').read_text())
for record in handoff['candidate_files']:
    assert sha(WORK / 'candidate-root' / record['path']) == record['sha256']
pretest = json.loads((WORK / 'test-003-source.json').read_text())
assert all(sha(TESTED / row['path']) == row['sha256'] for row in pretest)
fixtures = json.loads((WORK / 'fixture-restoration-001/RESTORATION.json').read_text())
assert len(fixtures['files']) == 235
assert all(sha(VENDOR / 'test-data' / row['path']) == row['sha256'] for row in fixtures['files'])

old_manifest = tomllib.loads((UPSTREAM / 'Cargo.toml').read_text())
new_manifest = tomllib.loads((VENDOR / 'Cargo.toml').read_text())
assert old_manifest['features'] == new_manifest['features']
assert old_manifest['dependencies']['rand'] == new_manifest['dependencies']['rand']
normal_changes = {
    key: {'old': value, 'new': new_manifest['dependencies'].get(key)}
    for key, value in old_manifest['dependencies'].items()
    if value != new_manifest['dependencies'].get(key)
}
assert set(normal_changes) == {'p256'}
source_records = []
for old in sorted((UPSTREAM / 'src').rglob('*')):
    if old.is_file():
        relative = old.relative_to(UPSTREAM)
        source_records.append({
            'path': str(relative), 'upstream_sha256': sha(old),
            'candidate_sha256': sha(VENDOR / relative),
            'unchanged': old.read_bytes() == (VENDOR / relative).read_bytes(),
        })
old_rust = [row for row in source_records if row['path'].endswith('.rs')]
assert len(old_rust) == 62
assert [row['path'] for row in old_rust if not row['unchanged']] == ['src/login/dpop.rs']

old_lock = tomllib.loads((WORK / 'WORKSPACE_LOCK_BEFORE.toml').read_text())['package']
lock = tomllib.loads((TESTED / 'Cargo.lock').read_text())['package']
old_aws = {(p['name'], p['version']) for p in old_lock if p['name'].startswith('aws-')}
new_aws = {(p['name'], p['version']) for p in lock if p['name'].startswith('aws-')}
assert not old_aws - new_aws
assert len(old_aws & new_aws) == 22
old_rand = {(p['name'], p['version']) for p in old_lock if p['name'] == 'rand' and p['version'].startswith('0.8.')}
new_rand = {(p['name'], p['version']) for p in lock if p['name'] == 'rand'}
assert old_rand == new_rand
chain = {name: [p for p in lock if p['name'] == name] for name in ('p256', 'elliptic-curve', 'crypto-bigint', 'ecdsa', 'signature', 'rand', 'rand_core')}
assert [p['version'] for p in chain['p256']] == ['0.14.0']
assert [p['version'] for p in chain['elliptic-curve']] == ['0.14.3']
assert [p['version'] for p in chain['crypto-bigint']] == ['0.7.10']

upstream_receipts = []
for group in ('upstream-002', 'upstream-003'):
    upstream_receipts.extend(json.loads((WORK / group / 'FETCH_RECEIPTS.json').read_text()))
write_json(EVIDENCE / 'VENDOR_PROVENANCE.json', {
    'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'official_archive_receipts': upstream_receipts,
    'aws_git_commit': fixtures['source_commit'],
    'official_fixture_tree_git_sha1': fixtures['directory_tree_sha1'],
    'official_fixture_files': fixtures['files'],
    'existing_source_files': source_records,
    'existing_rust_files': 62,
    'unchanged_existing_rust_files': 61,
    'only_modified_existing_rust_file': 'src/login/dpop.rs',
    'normal_dependency_changes': normal_changes,
    'all_upstream_feature_definitions_identical': True,
    'original_rand_constraint_and_resolved_version_unchanged': True,
    'upstream_license_and_cargo_toml_orig_unchanged': all(
        (UPSTREAM / name).read_bytes() == (VENDOR / name).read_bytes()
        for name in ('LICENSE', 'Cargo.toml.orig', '.cargo_vcs_info.json')
    ),
    'original_upstream_cargo_lock': file_record(UPSTREAM / 'Cargo.lock', WORK),
    'production_vendor_omits_upstream_and_standalone_test_locks': True,
    'production_vendor_omits_standalone_nextest_config': True,
    'vendor_files': handoff['candidate_files'],
})
write_json(EVIDENCE / 'ISOLATED_LOCK_GRAPH.json', {
    'scope': 'Full standalone upstream aws-config package, default features plus credentials-login; not the full first-party workspace lock.',
    'lock_sha256': sha(TESTED / 'Cargo.lock'),
    'baseline_workspace_lock_sha256': sha(WORK / 'WORKSPACE_LOCK_BEFORE.toml'),
    'chain_packages': chain,
    'all_22_preexisting_aws_package_versions_retained': True,
    'retained_aws_packages': sorted(old_aws & new_aws),
    'additional_upstream_dev_only_aws_package': sorted(new_aws - old_aws),
    'crypto_bigint_0_5_absent_in_this_lock': True,
    'full_workspace_and_bazel_locks_verified': False,
})

attempts = []
expected = {
    'test-003.log': (19, 19, 0, 226),
    'test-004-all-providers.log': (244, 241, 3, 1),
    'test-005-environment-check.log': (3, 2, 1, 242),
    'test-006-all-providers.log': (244, 242, 2, 1),
}
for name in ('test-001.log', 'test-002.log', *expected):
    content = (WORK / name).read_text()
    result = {'log': name, 'sha256': sha(WORK / name)}
    if name in expected:
        run, passed, failed, skipped = expected[name]
        summary = re.search(r'Summary \[[^\]]+\] (\d+) tests run: (\d+) passed,(?: (\d+) failed,)? (\d+) skipped', content)
        assert summary, name
        actual = tuple(int(value or 0) for value in summary.groups())
        assert actual == (run, passed, failed, skipped), (name, actual)
        result.update({'tests_run': run, 'passed': passed, 'failed': failed, 'not_selected_or_ignored': skipped})
    else:
        assert 'exit code 96' in content
        result.update({'tests_run': 0, 'status': 'nextest configuration error before test execution', 'exit_code': 96})
    attempts.append(result)

binaries = [p for p in (WORK / 'target/debug/deps').glob('aws_config-*') if p.is_file() and p.stat().st_mode & 0o111]
assert len(binaries) == 1
binary = binaries[0]
frozen_binary_dir = WORK / 'frozen-binaries'
frozen_binary_dir.mkdir(exist_ok=True)
frozen_binary = frozen_binary_dir / sha(binary)
if not frozen_binary.exists():
    shutil.copyfile(binary, frozen_binary)
    frozen_binary.chmod(0o555)
assert sha(binary) == sha(frozen_binary)
peer = ROOT / 'ndu-keyring-zbus6-candidate/evidence/PEER_AWS_PORT.json'
assert sha(peer) == '9f9b413d006cb8934f54edc92d5d5e0f5d0a42fe4273911095367acb4dc2ae8c'
shutil.copyfile(peer, EVIDENCE / 'PEER_AWS_PORT.json')
shutil.copyfile(TESTED / 'Cargo.lock', EVIDENCE / 'STANDALONE_TEST_Cargo.lock')
shutil.copyfile(TESTED / '.config/nextest.toml', EVIDENCE / 'STANDALONE_TEST_nextest.toml')
shutil.copyfile(WORK / 'CANDIDATE_HANDOFF.json', EVIDENCE / 'CANDIDATE_HANDOFF.json')
shutil.copyfile(WORK / 'workspace-manifest.patch', HERE / 'workspace-manifest.patch')

failure_names = [
    'imds::client::test::one_second_connect_timeout',
    'imds::credentials::test::read_timeout_during_credentials_refresh_should_error_without_last_retrieved_credentials',
]
write_json(EVIDENCE / 'TEST_RECEIPT.json', {
    'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'candidate_vendor_inventory_sha256': sha(WORK / 'CANDIDATE_HANDOFF.json'),
    'pre_test_003_inventory_sha256': sha(WORK / 'test-003-source.json'),
    'all_77_pre_test_003_files_unchanged_after_final_run': True,
    'all_235_official_fixture_files_reopened_and_unchanged': True,
    'actual_test_binary': file_record(frozen_binary, WORK),
    'test_entrypoint': 'repository just test -> scripts/run-nextest.py; never cargo test directly',
    'package_scope': 'Complete standalone upstream aws-config 1.8.12, all default providers plus credentials-login; no first-party workspace trimming.',
    'attempts': attempts,
    'login_selected_suite': {'run': 19, 'passed': 19, 'includes': [
        'New 9 tests for RNG byte forwarding, SEC1/PEM and JWK compatibility, p256 and ring verification of actual randomized DPoP signatures, request claims, cache refresh/reopen, failure preservation, and 30-second throttle.',
        'Unchanged upstream login tests, including the original eight-case JSON fixture.'
    ]},
    'full_final_suite': {'run': 244, 'passed': 242, 'failed': 2, 'unchanged_upstream_ignored': 1, 'failed_names': failure_names},
    'unchanged_upstream_ignore': 'ecs::tests::real_dns_lookup',
    'failed_environment_assumption': 'Both failed tests expect timeout classification from HTTP 240.0.0.0. The sandbox first returned EPERM; the permitted network run instead received transparent Envoy HTTP 503 without the token TTL header. Neither response satisfies the upstream blackhole-network assumption.',
    'no_assertions_or_ignores_relaxed': True,
    'network_run_no_color_handling': 'Only NO_COLOR was removed for that test process to retain the original ANSI-log assertion. No sandbox environment variable or production behavior was changed.',
    'no_color_baseline_failure_retained': 'test-004-all-providers.log includes loader::test::provider_config_used failure with inherited NO_COLOR=1; it passes in test-005 and test-006 with the original assertion.',
    'provider_test_scope': 'Actual SDK provider and signing code with injected in-memory Fs and recording HttpClient; new provider objects are exercised. This is not a real AWS service request or an OS process/disk restart.',
    'full_first_party_workspace_tests_passed': False,
    'bazel_tests_passed': False,
    'promotion_eligible': False,
    'remaining_gates': [
        'Run the complete unchanged upstream suite on an independent runner whose timeout endpoint really stalls; preserve both failures if they recur.',
        'Regenerate and inspect the full first-party Cargo and Bazel lock graph; no legacy vulnerable crypto-bigint branch or advisory ignore.',
        'Compile and test actual codex-aws-auth consumers using the nonmember production vendor, then relevant workspace/platform CI.',
        'Validate the prepared Bazel target and its qualification-only dev dependency metadata without expanding production features.',
    ],
})

def make_patch(names):
    result = []
    for name in names:
        old = UPSTREAM / name
        new = VENDOR / name
        old_text = old.read_text() if old.exists() else ''
        result.extend(difflib.unified_diff(old_text.splitlines(True), new.read_text().splitlines(True), fromfile='a/codex-rs/third_party/aws-config-1.8.12/' + name if old.exists() else '/dev/null', tofile='b/codex-rs/third_party/aws-config-1.8.12/' + name))
    return ''.join(result)

(HERE / 'production-source.patch').write_text(make_patch(['Cargo.toml', 'src/login/dpop.rs', 'src/login/signing_rng.rs']))
(HERE / 'tests-and-build.patch').write_text(make_patch(['src/login/dpop_port_tests.rs', 'src/login/dpop_provider_tests.rs', 'BUILD.bazel', 'test-data/hepta-runfiles/crate-root.marker']))
print(json.dumps({'candidate_files': len(handoff['candidate_files']), 'pretest_file_mutations': 0, 'fixture_mutations': 0, 'login_passed': 19, 'final_passed': 242, 'final_failed': 2, 'frozen_binary': str(frozen_binary), 'evidence': str(EVIDENCE)}, indent=2))
