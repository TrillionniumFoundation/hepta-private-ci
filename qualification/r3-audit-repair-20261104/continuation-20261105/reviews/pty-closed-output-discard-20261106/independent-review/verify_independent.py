#!/usr/bin/env python3
"""Independent static source and offline evidence replay; no Rust or PTY execution."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
sys.dont_write_bytecode = True


def identity(data):
    return {'bytes': len(data), 'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest(), 'sha256': hashlib.sha256(data).hexdigest()}


def merkle(leaves):
    root = {}
    for path, entry in leaves.items():
        here = root
        parts = path.split('/')
        for part in parts[:-1]:
            here = here.setdefault(part, {})
        assert parts[-1] not in here
        here[parts[-1]] = (entry['mode'], entry['sha'])
    count = 0
    def digest(node):
        nonlocal count
        count += 1
        records = []
        for name, entry in node.items():
            is_tree = isinstance(entry, dict)
            mode, sha = ('40000', digest(entry)) if is_tree else entry
            records.append(((name + ('/' if is_tree else '')).encode(), mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(sha)))
        raw = b''.join(row[1] for row in sorted(records))
        return hashlib.sha1(b'tree ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    value = digest(root)
    return value, count


def verify(author, root):
    freeze_bytes = (author / 'freeze-manifest.json').read_bytes()
    assert identity(freeze_bytes)['git_blob'] == '141539d98f058161ad68cb1b9f34123b8b3e51b3'
    freeze = json.loads(freeze_bytes)
    assert freeze['data_files'] == len(freeze['files']) == 69
    assert len({e['path'] for e in freeze['files']}) == 69
    for row in freeze['files']:
        actual = identity((author / row['path']).read_bytes())
        assert actual == {key: row[key] for key in actual}
    path = 'codex-rs/utils/pty/src/unix_io.rs'
    pre = (author / 'source' / path).read_bytes()
    post = (author / 'candidate' / path).read_bytes()
    assert identity(pre)['git_blob'] == '67168dab510c9fd400a1cbcf4b4a6bb905b73c59'
    assert identity(post)['git_blob'] == 'c7ad412d04fd3f5505259a4afdcec0d4d8562a88'
    added = b'''                        // Keep draining without allocating a message or polling a send
                        // that can no longer succeed once the channel is closed.
                        if stdout_tx.is_closed() {
                            #[cfg(test)]
                            diagnostics.observe(ReaderEvent::Discarded(count));
                            continue;
                        }
'''
    anchor = b'                        // Output caps may close the receiver before the child exits.\n'
    assert pre.count(anchor) == post.count(added) == 1 and len(added) == 406
    assert pre.replace(anchor, anchor + added) == post
    assert post.replace(added, b'', 1) == pre
    actual = json.loads((root / 'original/postimage.fresh-GET.json').read_bytes())['structuredContent']
    assert actual['content'].encode() == post
    tree = json.loads((author / 'authority/main67-full-tree.json').read_bytes())
    assert not tree['truncated'] and tree['sha'] == '3982ba56dc5a3f1da0c1de7ea57992f88125c359'
    leaves = {e['path']: e for e in tree['tree'] if e['type'] != 'tree'}
    assert len(leaves) == 10582
    before, directories = merkle(leaves)
    assert before == tree['sha']
    after = dict(leaves)
    after[path] = {**after[path], 'sha': identity(post)['git_blob']}
    projected, after_directories = merkle(after)
    assert projected == 'c1249a173ac346d0f1230fe56451b97d4e13c601'
    assert directories == after_directories
    assert [p for p in leaves if leaves[p] != after[p]] == [path]
    primary = []
    for name in ['bounded', 'batch_semaphore', 'async_fd', 'registration']:
        data = (author / f'primary/{name}.rs').read_bytes()
        original = json.loads((author / f'primary/{name}.rs.GET.original.json').read_bytes())['structuredContent']
        assert original['content'].encode() == data
        assert '/tokio-1.53.3/' in original['url']
        primary.append({'path': f'primary/{name}.rs', **identity(data)})
    with tempfile.TemporaryDirectory(prefix='pty-review-offline-') as temp:
        copied = Path(temp) / 'candidate'
        copied.mkdir()
        for row in freeze['files']:
            dest = copied / row['path']
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(author / row['path'], dest)
        shutil.copyfile(author / 'freeze-manifest.json', copied / 'freeze-manifest.json')
        replay = subprocess.run([sys.executable, str(copied / 'verify_candidate.py'), '--root', str(copied)], cwd=temp, capture_output=True, timeout=60)
        assert replay.returncode == 0 and replay.stderr == b''
        assert replay.stdout == (author / 'static-final.stdout.json').read_bytes()
        assert identity(replay.stdout)['git_blob'] == '9f21221d4df81c24bd93dc6dd0b0c7e129b6b10b'
        (root / 'author-replay.stdout.json').write_bytes(replay.stdout)
        (root / 'author-replay.stderr.txt').write_bytes(replay.stderr)
        (root / 'author-replay.exit-code.txt').write_text('0\n')
    return {'schema': 'pty-closed-receiver-independent-proof-v1', 'decision': 'STATIC_OFFLINE_SOURCE_ACCEPTED_ONLY', 'freeze': identity(freeze_bytes), 'frozen_data_files_verified': 69, 'frozen_data_bytes': sum(e['bytes'] for e in freeze['files']), 'preimage': identity(pre), 'actual_fresh_full_GET_postimage': identity(post), 'exact_single_insertion_bytes': 406, 'full_inverse_restores_original': True, 'original_tree': before, 'candidate_tree': projected, 'leaf_count': len(leaves), 'directory_count': directories, 'unchanged_leaves': 10581, 'fixed_primary_full_GET_matches': primary, 'isolated_author_replay': {'exit_code': 0, 'stderr_bytes': 0, 'stdout': identity(replay.stdout), 'equal_to_frozen_author_output': True}, 'scope': {'original_tests_and_two_backends_unchanged': True, 'original_two_second_budget_unchanged': True, 'original_send_race_path_unchanged': True, 'AsyncFd_readiness_and_cooperative_await_remain': True, 'ordinary_stdout_backpressure_unchanged': True, 'product_execution_or_compilation': False, 'formatter_executed': False, 'timeout_cause_proven': False, 'B21_closed': False}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--author-root', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    print(json.dumps(verify(args.author_root.resolve(), args.root.resolve()), ensure_ascii=False, indent=2))
