import datetime
import hashlib
import json
from pathlib import Path


ROOT = Path('ci-audit/recovered-20261105/b16-ai395-cold-bootstrap-v1')
SDK = ROOT / 'p4-libcap-sdk-continuation-v2'
OUTPUT = Path('hepta-audit-fifth/inputs/libcap-sdk-root-review.json')


def identity(raw):
    return {
        'bytes': len(raw),
        'sha256': hashlib.sha256(raw).hexdigest(),
        'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest(),
    }


def check(raw, expected):
    actual = identity(raw)
    for key in actual:
        if key in expected:
            assert actual[key] == expected[key], (key, actual[key], expected[key])
    return actual


transport = json.loads((SDK / 'originals-transport.json').read_text())
assert transport['truncated'] is False and len(transport['files']) == 7
for entry in transport['files']:
    assert entry['eof']
    raw = entry['text'].encode()
    assert len(raw) == entry['size']
    check(raw, entry)
    assert (SDK / 'originals' / Path(entry['path']).name).read_bytes() == raw

receipt = json.loads((SDK / 'originals/libcap-sdk.json').read_text())
terminal = json.loads((SDK / 'originals/terminal.json').read_text())
assert terminal['success'] and not terminal['errors']
assert not any(terminal[key] for key in ('tests_executed', 'build_executed', 'system_install'))
assert len(terminal['commands']) == 4 and all(command['exit_code'] == 0 for command in terminal['commands'])
assert receipt['source_tree'] == '4a3374e22e16ce5c764288ad018cd9affadf94ea'
assert receipt['version'] == '1:2.75-10ubuntu2'
assert not any(receipt[key] for key in (
    'build_executed', 'tests_executed', 'system_mutation', 'source_or_lock_change', 'global_sysroot_set'))
assert receipt['default_system_search_preserved']
assert receipt['environment'] == {
    'PKG_CONFIG_PATH': '/home/qq/work/hepta-audit-b16-20261105/tools/libcap-2.75-10ubuntu2/pkgconfig'}

expected_packages = {
    'libcap-dev': (619148, '74fa71aa089d90d720722f6278314b90b72fa2e1631aea5dc32b770d0324ce86'),
    'libcap2': (29264, '150603a0792b1d22aa0bde0a26c27b413018c799284003e4b43cba587a5b3a18'),
}
assert {entry['name'] for entry in receipt['packages']} == set(expected_packages)
for package in receipt['packages']:
    download = package['official_download']
    actual = download['package']
    assert (actual['bytes'], actual['sha256']) == expected_packages[package['name']]
    assert download['no_new_download'] and download['reused_closed_original_download']
    assert download['url'].startswith('https://archive.ubuntu.com/ubuntu/pool/main/libc/libcap2/')
    assert package['extract']['exit_code'] == 0

library = receipt['library']
assert library['byte_equal']
assert all(library['private'][key] == library['system_readonly'][key] for key in ('bytes', 'sha256', 'git_blob'))
assert library['private']['sha256'] == 'c5b463a8136dabb152bad8b04e89bf67bd2049ef49777ed0b96bdbc6cb5b9565'
assert len(receipt['headers']) == 2 and len(receipt['aliases']) == 2
for alias in receipt['aliases']:
    assert all(alias['resolved_file'][key] == library['private'][key] for key in ('bytes', 'sha256', 'git_blob'))

official_pc = (SDK / 'originals/libcap.pc.official.original').read_bytes()
check(official_pc, receipt['official_pc'])
lines = official_pc.splitlines(keepends=True)
assert [entry['variable'] for entry in receipt['relocation']] == ['prefix', 'libdir', 'includedir']
for change in receipt['relocation']:
    before, after = change['before'].encode(), change['after'].encode()
    assert lines.count(before) == 1
    lines[lines.index(before)] = after
check(b''.join(lines), receipt['relocated_pc'])
flags = (SDK / 'originals/pkg-config-libcap-relocated-flags.stdout.original').read_bytes()
check(flags, receipt['pkg_config_commands'][1]['stdout'])
assert flags.decode().split() == [
    '-I/home/qq/work/hepta-audit-b16-20261105/tools/libcap-2.75-10ubuntu2/sysroot/usr/include',
    '-L/home/qq/work/hepta-audit-b16-20261105/tools/libcap-2.75-10ubuntu2/sysroot/usr/lib/x86_64-linux-gnu',
    '-lcap',
]

guards = []
for filename, key in [('initial.guard.json', 'initial_guard'), ('final.guard.json', 'final_guard')]:
    raw = (SDK / 'originals' / filename).read_bytes()
    check(raw, terminal[key])
    guard = json.loads(raw)
    assert guard['head'] == '20fd174ded4e5ce01bda34e4f6d1d74803301f49'
    assert guard['head_tree'] == guard['working_tree'] == receipt['source_tree']
    assert guard['ordinary_index']['sha256'] == '6b39b6b27d164001c9b130487d0d7879be5f80e22a4579d06fd472c2bb8d7ac0'
    assert not guard['untracked']
    guards.append(guard)
assert guards[0]['guarded_files'] == guards[1]['guarded_files']
assert guards[0]['ordinary_index'] == guards[1]['ordinary_index']
failed_raw = (ROOT / 'p4-libcap-sdk-v1/failure-originals/terminal.json').read_bytes()
check(failed_raw, terminal['prior_failed_sdk_terminal'])
failed = json.loads(failed_raw)
assert not failed['success'] and [command['exit_code'] for command in failed['commands']] == [0, 0]

review = {
    'schema': 'hepta-root-libcap-private-sdk-review-v1',
    'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'verdict': 'PASS_SCOPED_PREREQUISITE_ONLY',
    'inputs': {name: identity((SDK / 'originals' / name).read_bytes()) for name in [
        'terminal.json', 'libcap-sdk.json', 'libcap-pc-relocation.json', 'libcap.pc.official.original',
        'pkg-config-libcap-relocated-flags.stdout.original', 'initial.guard.json', 'final.guard.json']},
    'verified': {
        'seven_full_originals_transport_and_hashes': True,
        'four_actual_sdk_continuation_commands_exit_zero': True,
        'source_ordinary_index_and_two_locks_unchanged': True,
        'two_official_package_identities_exact': True,
        'private_runtime_equals_installed_runtime_recorded_identity': True,
        'three_exact_pc_line_changes_only': True,
        'real_pkg_config_private_include_library_and_lcap_flags': True,
        'default_system_pkg_config_search_preserved': True,
        'initial_final_whole_source_guards': True,
        'prior_v1_stream_close_order_failure_preserved': True,
    },
    'scope_limits': [
        'Package/header/shared-object physical identities are native receipts; no cloud re-download or second physical-host measurement claimed.',
        'Review covers seven fully retrieved original files; remaining SDK command originals are still being recovered.',
        'No tests executed, no test qualification, no B16 closure.',
    ],
    'test_qualification': False,
}
OUTPUT.parent.mkdir(exist_ok=True)
OUTPUT.write_text(json.dumps(review, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'path': str(OUTPUT), **identity(OUTPUT.read_bytes()), 'verdict': review['verdict']}))
