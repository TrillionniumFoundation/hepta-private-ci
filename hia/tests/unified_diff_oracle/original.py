"""Compile the complete fixed original crate; never reconstruct an algorithm."""
import hashlib
import subprocess
from .common import BASE as COMMIT, CRATE_TREE

def extract_original(context):
    OUT, REPO, REPORT, common = context.output, context.args.original_root.resolve(strict=True), context.report, context
    assert subprocess.check_output(['git', '-C', REPO, 'rev-parse', f'{COMMIT}:codex-rs/apply-patch']).decode().strip() == CRATE_TREE
    # Preserve the frozen aeb88 source, admitting only the independently
    # reviewed dependency identity. All other source/manifest changes fail closed.
    from file_update_oracle.identity import (
        _REVIEWED_4280_FILES, _reviewed_4280_root, clean_identity,
    )
    paths = ('codex-rs/Cargo.toml', 'codex-rs/Cargo.lock', 'codex-rs/apply-patch/Cargo.toml')
    differences = {}
    for relative in paths:
        frozen = subprocess.check_output(['git', '-C', REPO, 'show', f'{COMMIT}:{relative}'])
        actual = (context.repo / relative).read_bytes()
        if frozen != actual:
            differences[relative] = (hashlib.sha256(frozen).hexdigest(), hashlib.sha256(actual).hexdigest())
    if differences:
        expected = {path: _REVIEWED_4280_FILES[path] for path in paths[:2]}
        if differences != expected:
            raise RuntimeError('unreviewed unified formatter dependency declaration change')
        if subprocess.check_output(['git', '-C', REPO, 'rev-parse', f'{COMMIT}^{{tree}}']).decode().strip() != '29386bcac408706d83ee0aa2a51107bb115a1295':
            raise RuntimeError('unified formatter original tree differs')
        projected = _reviewed_4280_root(context.repo, clean_identity(context.repo))
        REPORT['reviewed_dependency_identity'] = {
            'projected_tree': projected,
            'files': {path: list(pair) for path, pair in differences.items()},
            'cross_lock_ledger_sha256': '25dbc0f047be0fe369a4f75d22839810962227ea84d164053cd00cb2a2f5262b',
            'checked_transcript_sha256': '81d61c3d99dfb71091604dd6ec60e242d34fc351840d81fcac97419c084830a8',
            'wrapping_transcript_sha256': 'c13c6f01114b989a0b3a96bf7a068da2e83f15d8656c93dc7857e7faff4ca526',
        }
    root = OUT / 'original-source'
    root.mkdir()
    rows = []
    listing = subprocess.check_output(['git', '-C', REPO, 'ls-tree', '-rz', COMMIT,
                                      '--', 'codex-rs/apply-patch']).split(b'\0')
    for entry in listing:
        if not entry:
            continue
        meta, name = entry.split(b'\t', 1)
        mode, kind, blob = meta.decode().split()
        assert kind == 'blob' and mode in ('100644', '100755')
        data = subprocess.check_output(['git', '-C', REPO, 'cat-file', 'blob', blob])
        assert hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == blob
        path = root / name.decode()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(data)
        path.chmod(int(mode[-3:], 8))
        rows.append(dict(common.bind(path), relative_path=name.decode(), git_blob=blob, git_mode=mode))
    assert len(rows) == 109 and any(x['relative_path'].endswith('/src/lib.rs') for x in rows)
    common.create(OUT / 'complete-original-source.json', {'commit': COMMIT, 'files': rows})
    REPORT['complete_original'] = common.bind(OUT / 'complete-original-source.json')
    REPORT['original_file_count'] = len(rows)
    return root / 'codex-rs/apply-patch', rows


def original_args(receipt, root, directory):
    argv = receipt['argv']
    assert argv.count('apply-patch/src/lib.rs') == 1, 'unrecognized or duplicate original source entry'
    assert [x for x in argv if x.endswith('.rs')] == ['apply-patch/src/lib.rs'], 'unsupported additional or absolute Rust source entry'
    result = []
    i = 0
    while i < len(argv):
        item = argv[i]
        if item == '--crate-name':
            result.extend([item, 'codex_apply_patch_original'])
            i += 2
        elif item == 'apply-patch/src/lib.rs':
            result.append(str(root / 'src/lib.rs'))
            i += 1
        elif item == '--out-dir':
            result.extend([item, str(directory)])
            i += 2
        elif item == '--cfg' and argv[i + 1] == 'feature="hia-native"':
            i += 2
        elif item == '-l' and argv[i + 1].startswith('static=codex_hia_'):
            i += 2
        else:
            result.append(item)
            i += 1
    assert result.count(str(root / 'src/lib.rs')) == 1
    assert 'apply-patch/src/lib.rs' not in result
    return result


def options(argv, name):
    return [argv[i + 1] for i, value in enumerate(argv) if value == name]
