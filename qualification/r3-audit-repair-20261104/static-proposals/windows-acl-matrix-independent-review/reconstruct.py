from pathlib import Path
import hashlib
import json
import subprocess
import tempfile

ROOT = Path('/workspace/scratch/07dd58cc9630')
OUT = Path(__file__).parent
IDEM = ROOT / 'research-audit/b11-current-boundary-design'
MATRIX = ROOT / 'research-audit/b11-delete-matrix'


def identity(data):
    return {
        'bytes': len(data),
        'sha256': hashlib.sha256(data).hexdigest(),
        'blob': hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest(),
    }


im = json.loads((IDEM / 'idempotency-candidate-manifest.json').read_text())
mm = json.loads((MATRIX / 'repair-manifest.json').read_text())
files = {}
for row in im['files']:
    path = row['path']
    before = (IDEM / 'source' / f'{path}.txt').read_bytes() if row['before'] else None
    after = Path(row['candidate_path']).read_bytes()
    assert identity(after) == row['after'], path
    if before is not None:
        assert identity(before) == row['before'], path
    files[path] = dict(before=before, after=after, group='idempotency')
for row in mm['changes']['files']:
    path = row['path']
    before = (MATRIX / 'source' / path).read_bytes() if row['before'] else None
    after = (MATRIX / 'candidate' / path).read_bytes()
    assert identity(after) == row['after'], path
    if before is not None:
        assert identity(before) == row['before'], path
    assert path not in files
    files[path] = dict(before=before, after=after, group='matrix')

patches = [
    IDEM / 'idempotency-candidate.patch',
    MATRIX / 'combined.patch',
    MATRIX / 'token-matrix.patch',
    MATRIX / 'legacy-matrix.patch',
]
report = {
    'schema': 'independent_windows_acl_matrix_patch_reconstruction_v1',
    'scope': 'Isolated partial source fixtures only; not compilation, native testing, or whole repository reconstruction.',
    'initial_review_script_error': {
        'type': 'ValueError: substring not found',
        'reason': 'The review helper looked for public add_deny_write_ace after the private function; the actual next function is add_deny_read_ace.',
        'product_finding': False,
        'resolution': 'Use the exact next read-function documentation boundary and persist every subsequent command receipt.',
    },
    'manifests': {
        'idempotency': identity((IDEM / 'idempotency-candidate-manifest.json').read_bytes()),
        'matrix': identity((MATRIX / 'repair-manifest.json').read_bytes()),
    },
    'patches': [dict(path=str(p.relative_to(ROOT)), **identity(p.read_bytes())) for p in patches],
    'results': [],
    'source_files': [
        dict(path=p, before=identity(r['before']) if r['before'] is not None else None, after=identity(r['after']))
        for p, r in files.items()
    ],
}


def save():
    (OUT / 'patch-reconstruction.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


for label, groups, sequence in [
    ('idempotency', ['idempotency'], [patches[0]]),
    ('matrix-combined', ['matrix'], [patches[1]]),
    ('matrix-split', ['matrix'], [patches[2], patches[3]]),
    ('both-composed', ['idempotency', 'matrix'], patches[:2]),
]:
    work = Path(tempfile.mkdtemp(prefix=f'{label}-verified-', dir=OUT))
    selected = {p: r for p, r in files.items() if r['group'] in groups}
    record = dict(label=label, worktree=str(work), commands=[], files=[])
    report['results'].append(record)

    def run(args):
        result = subprocess.run(args, cwd=work, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        record['commands'].append(dict(argv=args, exit=result.returncode, stdout=result.stdout, stderr=result.stderr))
        save()
        assert result.returncode == 0, (label, args, result.stderr)
        return result

    run(['git', 'init', '-q'])
    for path, row in selected.items():
        if row['before'] is not None:
            dest = work / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(row['before'])
    run(['git', 'add', '.'])
    for patch in sequence:
        run(['git', 'apply', '--check', str(patch)])
        run(['git', 'apply', str(patch)])
    for path, row in selected.items():
        actual = (work / path).read_bytes()
        assert actual == row['after'], path
        record['files'].append(dict(path=path, **identity(actual), matches_manifest=True))
    record['all_postimages_equal'] = True
    save()

old_acl = files['codex-rs/windows-sandbox-rs/src/acl.rs']['before'].decode()
new_acl = files['codex-rs/windows-sandbox-rs/src/acl.rs']['after'].decode()
start = old_acl.index('unsafe fn add_deny_ace(')
end = old_acl.index('\n\n/// Adds a deny ACE to prevent reads', start)
old_function = old_acl[start:end]
attachment = '#[path = "acl_deny.rs"]\nmod deny;\nuse deny::add_deny_ace;'
assert new_acl.count(attachment) == 1
preserved = {
    'acl_outside_private_add_deny_ace_byte_equal': new_acl.replace(attachment, old_function, 1) == old_acl,
    'all_original_acl_tests_prefix_byte_equal': files['codex-rs/windows-sandbox-rs/src/acl_tests.rs']['after'].startswith(files['codex-rs/windows-sandbox-rs/src/acl_tests.rs']['before']),
    'all_original_token_tests_prefix_byte_equal': files['codex-rs/windows-sandbox-rs/src/token_tests.rs']['after'].startswith(files['codex-rs/windows-sandbox-rs/src/token_tests.rs']['before']),
}
for path, insertion in [
    ('codex-rs/windows-sandbox-rs/src/unified_exec/tests.rs', '#[path = "delete_permission_tests.rs"]\nmod delete_permission_tests;\n\n'),
    ('codex-rs/windows-sandbox-rs/src/lib.rs', '#[cfg(all(test, target_os = "windows"))]\n#[path = "delete_permission_matrix_tests.rs"]\nmod delete_permission_matrix;\n\n'),
]:
    row = files[path]
    after = row['after'].decode()
    preserved[path + '_inverse_registration_byte_equal'] = after.count(insertion) == 1 and after.replace(insertion, '', 1) == row['before'].decode()
assert all(preserved.values()), preserved
report['preservation'] = preserved
report['all_roundtrips_pass'] = all(row['all_postimages_equal'] for row in report['results'])
report['product_execution_performed'] = False
report['shared_or_native_source_changed'] = False
report['refs_changed'] = False
save()
print(json.dumps(dict(report=str(OUT / 'patch-reconstruction.json'), all_roundtrips_pass=report['all_roundtrips_pass'], preservation=preserved, file_count=len(files)), ensure_ascii=False, indent=2))
