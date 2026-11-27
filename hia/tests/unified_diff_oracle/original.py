"""Compile the complete fixed original crate; never reconstruct an algorithm."""
import hashlib
import subprocess
from .common import BASE as COMMIT, CRATE_TREE
from file_update_oracle.dependencies import ROOT_FILES, admit_workspace_sources

def extract_original(context):
    OUT, REPO, REPORT, common = context.output, context.args.original_root.resolve(strict=True), context.report, context
    assert subprocess.check_output(['git', '-C', REPO, 'rev-parse', f'{COMMIT}:codex-rs/apply-patch']).decode().strip() == CRATE_TREE
    originals = {relative: subprocess.check_output(['git', '-C', REPO, 'show', f'{COMMIT}:{relative}'])
                 for relative in ROOT_FILES}
    admission = admit_workspace_sources(context.repo, originals)
    for relative in ('codex-rs/Cargo.toml', 'codex-rs/Cargo.lock', 'codex-rs/apply-patch/Cargo.toml'):
        if admission is not None and relative in ROOT_FILES:
            assert subprocess.check_output(['git', '-C', REPO, 'show', f'{COMMIT}:{relative}']) == admission["restored"][relative]
        else:
            assert subprocess.check_output(['git', '-C', REPO, 'show', f'{COMMIT}:{relative}']) == (context.repo / relative).read_bytes()
    context.dependency_source_admission = admission
    if admission is not None:
        REPORT["dependency_source_admission"] = admission["report"]
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
