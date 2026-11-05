"""Independent byte/patch checks only; never executes the Windows candidate."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
from datetime import datetime, timezone

ROOT = Path('/workspace/scratch/07dd58cc9630')
SRC = ROOT / 'architecture-audit/b11-acl-repair-20261105/identity-candidate-v3'
OUT = Path(__file__).resolve().parent


def identity(path):
    data = path.read_bytes()
    return {'path': str(path), 'bytes': len(data),
            'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


mapping = json.loads((SRC / 'source-map.json').read_text())
author_map = json.loads((SRC / 'github-readback-map.json').read_text())
verified = []
for row in author_map['objects']:
    got = identity(Path(row['path']))
    assert all(got[k] == row[k] for k in ('bytes', 'sha256', 'git_blob')), row
    assert row['created'] and row['GET_byte_equal']
    verified.append(got)
for row in mapping['paths']:
    for role in ('preimage', 'postimage'):
        expected = row[role]
        got = identity(Path(expected['path']))
        assert all(got[k] == expected[k] for k in ('bytes', 'sha256', 'git_blob'))

commands = []
stages = []
work = Path(tempfile.mkdtemp(prefix='independent-roundtrip-', dir=OUT))
for row in mapping['paths']:
    dest = work / row['repository_path']
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(Path(row['preimage']['path']).read_bytes())


def apply(patch, reverse=False):
    for check in (True, False):
        argv = ['git', '-C', str(work), 'apply']
        if reverse:
            argv.append('--reverse')
        if check:
            argv.append('--check')
        argv.append(str(SRC / patch))
        completed = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        commands.append({'argv': argv, 'returncode': completed.returncode,
                         'stdout': completed.stdout.decode(), 'stderr': completed.stderr.decode()})
        assert completed.returncode == 0, commands[-1]


def compare(stage, negative=False, preimage=False):
    rows = []
    for row in mapping['paths']:
        path = row['repository_path']
        if preimage:
            wanted = Path(row['preimage']['path'])
        elif negative and path.endswith('/acl_deny.rs'):
            wanted = Path(mapping['negative_source']['path'])
        else:
            wanted = Path(row['postimage']['path'])
        actual = work / path
        assert actual.read_bytes() == wanted.read_bytes(), (stage, path)
        rows.append({'repository_path': path, **identity(actual), 'byte_equal': True})
    stages.append({'stage': stage, 'paths': rows})


apply('full.patch')
compare('positive')
apply('remove-identity-check.patch')
compare('negative', negative=True)
apply('restore-identity-check.patch')
compare('restored-positive')
apply('full.patch', reverse=True)
compare('inverse-original', preimage=True)

old = (SRC / 'source/codex-rs/windows-sandbox-rs/src/acl_tests.rs').read_text()
new = (SRC / 'candidate/codex-rs/windows-sandbox-rs/src/acl_tests.rs').read_text()
case_start = '#[test]\nfn existing_native_deny_does_not_require_write_dac()'
new_prefix = new[:new.index(case_start)]
for added_import in ('use std::io::Write;\n', 'use std::os::windows::io::FromRawHandle;\n',
                     'use std::os::windows::io::OwnedHandle;\n'):
    assert new_prefix.count(added_import) == 1
    new_prefix = new_prefix.replace(added_import, '')
assert new_prefix == old[:old.index(case_start)]
names_old = re.findall(r'#\[test\]\nfn ([A-Za-z0-9_]+)\(', old)
names_new = re.findall(r'#\[test\]\nfn ([A-Za-z0-9_]+)\(', new)
assert len(names_old) == 7
assert names_new == names_old + ['deny_repair_rejects_a_replaced_path_before_mutating_either_object']
manifest = json.loads((SRC / 'manifest.json').read_text())
assertions = manifest['physical_controls']['original_assertions']
for text in (old, new):
    offsets = [text.index(a, text.index(case_start)) for a in assertions]
    assert offsets == sorted(offsets)
needle = '        assert_eq!(\n            replacement_after,\n            replacement_dacl,'
assert new.count(needle) == 1
panic_line = new[:new.index(needle)].count('\n') + 1
assert panic_line == 597

prod_old = (SRC / 'source/codex-rs/windows-sandbox-rs/src/acl_deny.rs').read_text()
prod_new = (SRC / 'candidate/codex-rs/windows-sandbox-rs/src/acl_deny.rs').read_text()
segments = {}
starts_ends = {
    'object_matcher': ('pub(super) unsafe fn dacl_has_complete_deny_for_object(', '\n    false\n}\n'),
    'initial_read_control_open': ('    let raw = CreateFileW(\n        to_wide(path).as_ptr(),\n        READ_CONTROL,', '    let object = OwnedHandle::from_raw_handle(raw as _);\n'),
    'query_and_complete_early_return': ('    let mut info: FILE_STANDARD_INFO =', '        return Ok(false);\n    }\n'),
    'acl_mutation_tail': ('    let entry = EXPLICIT_ACCESS_W {', '    acl_api_result(path, "SetSecurityInfo", code).map(|()| true)\n}\n'),
}
for name, (begin, end) in starts_ends.items():
    parts = []
    for text in (prod_old, prod_new):
        i = text.index(begin)
        j = text.index(end, i) + len(end)
        parts.append(text[i:j].encode())
    assert parts[0] == parts[1], name
    segments[name] = {'byte_equal': True, 'bytes': len(parts[0]),
                      'sha256': hashlib.sha256(parts[0]).hexdigest()}

receipt = {
    'schema': 'independent-b11-acl-identity-v3-static-roundtrip-v1',
    'observed_at_utc': datetime.now(timezone.utc).isoformat(),
    'scope': 'Cloud byte checks and isolated Git apply only. No Rust compilation, Windows, native execution or shared source/ref modification.',
    'author_create_get_map': identity(SRC / 'github-readback-map.json'),
    'author_map_local_objects_verified': verified,
    'source_map': identity(SRC / 'source-map.json'),
    'commands': commands, 'stages': stages,
    'original_test_names': names_old, 'candidate_test_names': names_new,
    'first_six_tests_and_original_helpers_byte_equal_after_only_three_added_imports_removed': True,
    'original_no_write_dac_six_assertions_present_in_order': assertions,
    'production_preserved_segments': segments,
    'negative_expected_macro_start_line': panic_line,
    'negative_runtime_result': 'NOT_RUN',
    'positive_runtime_result': 'NOT_RUN',
    'passed': True,
}
(OUT / 'static-reconstruction.json').write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + '\n')
print(json.dumps({'passed': True, 'commands': len(commands), 'stages': len(stages),
                  'author_objects': len(verified), 'receipt': identity(OUT / 'static-reconstruction.json')}, indent=2))
