import subprocess
import tempfile
from pathlib import Path


def git(root, *args, data=None):
    return subprocess.run(['git', '-C', str(root), *args], input=data, capture_output=True, check=True).stdout


def original_blob_matches_worktree(root: Path, rel: str):
    row = git(root, 'ls-tree', 'HEAD', '--', rel).decode().strip()
    metadata, _, found = row.partition('\t')
    mode, typ, oid = metadata.split()
    return (found == rel and mode == '100644' and typ == 'blob'
            and git(root, 'cat-file', 'blob', oid) == (root / rel).read_bytes())


def patched_blob_matches_worktree(root: Path, rel: str):
    row = git(root, '--no-replace-objects', 'ls-tree', 'HEAD', '--', rel).decode().strip()
    metadata, _, found = row.partition('\t')
    mode, typ, oid = metadata.split()
    return (found == rel and mode == '100644' and typ == 'blob'
            and git(root, '--no-replace-objects', 'cat-file', 'blob', oid) == (root / rel).read_bytes())

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    git(root, 'init', '-q')
    file = root / 'source.rs'
    file.write_bytes(b'frozen original\n')
    git(root, 'add', 'source.rs')
    git(root, '-c', 'user.name=LocalProof', '-c', 'user.email=proof@example.invalid', 'commit', '-qm', 'baseline')
    oid = git(root, 'rev-parse', 'HEAD:source.rs').decode().strip()
    changed = b'unreviewed replacement\n'
    file.write_bytes(changed)
    new_oid = git(root, 'hash-object', '-w', '--stdin', data=changed).decode().strip()
    git(root, 'replace', oid, new_oid)
    git(root, 'update-index', '--assume-unchanged', 'source.rs')
    status = git(root, 'status', '--porcelain=v1').decode().strip()
    replacements = git(root, 'for-each-ref', '--format=%(refname)', 'refs/replace').decode().strip()
    old_answer = original_blob_matches_worktree(root, 'source.rs')
    fixed_answer = patched_blob_matches_worktree(root, 'source.rs')
    assert status == ''
    assert old_answer and not fixed_answer
    assert replacements.startswith('refs/replace/')
    print('Git status clean:', status == '')
    print('Current vulnerable object comparison accepted tampered bytes:', old_answer)
    print('No-replace object comparison rejected tampered bytes:', not fixed_answer)
    print('Replacement ref enumerated:', bool(replacements))
