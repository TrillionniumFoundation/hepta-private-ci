"""Review actual A formatter bytes in an isolated cloud-only Git directory."""
import ast
import collections
import difflib
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path('/workspace/scratch/07dd58cc9630')
OUT = Path(__file__).resolve().parent
INPUT = ROOT / 'ci-audit/recovered-20261105/final-A-fmt-complete-v1'


def ident_bytes(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def ident(path):
    return {'path': str(path.relative_to(ROOT)), **ident_bytes(path.read_bytes())}


def treehash(files):
    root = {}
    for path, obj in files.items():
        d, parts = root, path.split('/')
        for part in parts[:-1]:
            d = d.setdefault(part, {})
        d[parts[-1]] = (obj['mode'], obj['sha'])
    def calc(d):
        entries = [(name, '40000', calc(value)) if isinstance(value, dict) else (name, *value)
                   for name, value in d.items()]
        entries.sort(key=lambda x: (x[0] + ('/' if x[1] in ['40000', '040000'] else '')).encode())
        raw = b''.join(mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(sha)
                       for name, mode, sha in entries)
        return hashlib.sha1(b'tree ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    return calc(root)


def rust_tokens(text):
    """Lexical diagnostic, not a Rust parser; retain every comment/literal byte."""
    result, pos = [], 0
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        begin = pos
        if text.startswith('//', pos):
            end = text.find('\n', pos)
            pos = len(text) if end == -1 else end
            result.append(('comment', text[begin:pos]))
            continue
        if text.startswith('/*', pos):
            depth, pos = 1, pos + 2
            while depth:
                assert pos < len(text)
                if text.startswith('/*', pos):
                    depth, pos = depth + 1, pos + 2
                elif text.startswith('*/', pos):
                    depth, pos = depth - 1, pos + 2
                else:
                    pos += 1
            result.append(('comment', text[begin:pos]))
            continue
        raw = re.match(r'(?:br|cr|r)(#*)"', text[pos:])
        if raw:
            end = text.find('"' + raw[1], pos + raw.end())
            assert end >= 0
            pos = end + 1 + len(raw[1])
            result.append(('literal', text[begin:pos]))
            continue
        quoted = re.match(r'(?:b|c)?"', text[pos:])
        if quoted:
            pos += quoted.end()
            while pos < len(text):
                if text[pos] == '\\':
                    pos += 2
                elif text[pos] == '"':
                    pos += 1
                    break
                else:
                    pos += 1
            else:
                raise AssertionError('unterminated quoted token')
            result.append(('literal', text[begin:pos]))
            continue
        char = re.match(r"(?:b)?'(?:\\(?:u\{[0-9a-fA-F_]+\}|x[0-9a-fA-F]{2}|.)|[^\\'\n])'", text[pos:])
        if char:
            pos += char.end()
            result.append(('literal', text[begin:pos]))
            continue
        word = re.match(r'\w+', text[pos:])
        if word:
            pos += word.end()
            result.append(('word', text[begin:pos]))
            continue
        pos += 1
        result.append(('punct', text[begin:pos]))
    return result


changes = json.loads((INPUT / 'original-fmt-changes.json').read_bytes())
status = json.loads((INPUT / 'original-fmt-status.json').read_bytes())
small = json.loads((INPUT / 'small-postimages.json').read_bytes())
patch_path = INPUT / 'large-decoded/original-fmt.patch'
patch = patch_path.read_bytes()
assert ident_bytes(patch)['sha256'] == '870bebd231538f636a89e4e23b87b2933429ae75d9977b9c88b6141a92afa66d'
assert len(patch) == 66988
assert status['argv'] == ['just', 'fmt'] and status['exit_code'] == 0
assert changes['before_tree'] == 'b2901e2beb8171f125fe5906d585fbe134802423'
assert changes['after_tree'] == '4a3374e22e16ce5c764288ad018cd9affadf94ea'
assert not status['after_guard_failures']
headers = re.findall(r'^diff --git a/(.+) b/\1\nindex ([0-9a-f]{40})\.\.([0-9a-f]{40}) 100644$', patch.decode(), re.M)
assert len(headers) == len(changes['changed_paths']) == 17
before_blobs = {path: pre for path, pre, post in headers}
after_blobs = {path: post for path, pre, post in headers}
assert set(after_blobs) == {r['path'] for r in changes['changed_paths']}
posts = {row['path']: row['content'].encode() for row in small['files']}
for path in ['codex-rs/cli/src/doctor.rs', 'codex-rs/core/tests/suite/hooks.rs']:
    posts[path] = (INPUT / 'large-decoded' / (path.replace('/', '__') + '.source.txt')).read_bytes()
assert len(posts) == 17
for row in changes['changed_paths']:
    actual = ident_bytes(posts[row['path']])
    assert row['mode'] == '100644' and row['status'] == 'M'
    assert actual['blob'] == row['git_blob'] == after_blobs[row['path']]
    assert actual['bytes'] == row['bytes'] and actual['sha256'] == row['sha256']

scratch = Path(tempfile.mkdtemp(prefix='fmt-roundtrip-', dir=OUT))
commands = []
def git(args):
    result = subprocess.run(['git', *args], cwd=scratch, capture_output=True, text=True)
    commands.append({'argv': ['git', *args], 'exit_code': result.returncode,
                     'stdout': result.stdout, 'stderr': result.stderr})
    assert result.returncode == 0, commands[-1]
git(['init', '-q'])
for path, raw in posts.items():
    p = scratch / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(raw)
git(['apply', '--reverse', '--check', str(patch_path)])
git(['apply', '--reverse', str(patch_path)])
pres = {path: (scratch / path).read_bytes() for path in posts}
assert all(ident_bytes(raw)['blob'] == before_blobs[path] for path, raw in pres.items())
git(['apply', '--check', str(patch_path)])
git(['apply', str(patch_path)])
assert all((scratch / path).read_bytes() == raw for path, raw in posts.items())
for kind, sources in [('fmt-preimages', pres), ('fmt-postimages', posts)]:
    for path, raw in sources.items():
        p = OUT / kind / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw)

base_path = ROOT / 'hepta-audit-fourth/inputs/cabc-tree.json'
base = json.loads(base_path.read_bytes())
assert base['truncated'] is False
files = {e['path']: {'mode': e['mode'], 'sha': e['sha']} for e in base['tree'] if e['type'] != 'tree'}
assert treehash(files) == base['sha']
map_path = ROOT / 'ci-audit/recovered-20261105/full-fb9-complete-archive/decoded-verified-v1/small/final-source-map.json'
source_map = json.loads(map_path.read_bytes())
for row in source_map['files']:
    files[row['path']] = {'mode': row['mode'], 'sha': row['git_blob']}
assert treehash(files) == source_map['final_tree']
files['codex-rs/linux-sandbox/src/parent_lifecycle_tests.rs']['sha'] = '58eff73120448cb122c3e6d22ea60a7ee1899844'
assert treehash(files) == changes['before_tree']
assert all(files[path]['sha'] == sha for path, sha in before_blobs.items())
for path, sha in after_blobs.items():
    files[path]['sha'] = sha
assert treehash(files) == changes['after_tree']

rows = []
for path in posts:
    pre, post = pres[path].decode(), posts[path].decode()
    row = {'path': path, 'preimage': ident_bytes(pres[path]), 'postimage': ident_bytes(posts[path])}
    if path.endswith('.py'):
        left, right = ast.dump(ast.parse(pre), include_attributes=False), ast.dump(ast.parse(post), include_attributes=False)
        assert left == right
        row.update({'verification': 'FULL_PYTHON_AST_EQUAL', 'ast_sha256': hashlib.sha256(left.encode()).hexdigest()})
    else:
        left, right = rust_tokens(pre), rust_tokens(post)
        # No string/byte/raw literal, numeric/identifier, or comment may change.
        left_literals = [t for t in left if t[0] == 'literal']
        right_literals = [t for t in right if t[0] == 'literal']
        assert collections.Counter(left_literals) == collections.Counter(right_literals), path
        assert [t for t in left if t[0] == 'comment'] == [t for t in right if t[0] == 'comment'], path
        if path != 'codex-rs/windows-sandbox-rs/src/lib.rs':
            assert left_literals == right_literals, path
            assert [t for t in left if t[0] == 'word'] == [t for t in right if t[0] == 'word'], path
        ops = []
        for tag, a, b, c, d in difflib.SequenceMatcher(a=left, b=right, autojunk=False).get_opcodes():
            if tag != 'equal':
                ops.append({'kind': tag, 'pre_tokens': left[a:b], 'post_tokens': right[c:d],
                            'pre_context_before': left[max(0, a - 8):a], 'pre_context_after': left[b:b + 8]})
        row.update({'verification': 'FULL_DIFF_MANUAL_REVIEW_PLUS_LEXICAL_DIAGNOSTIC_NOT_RUST_AST',
                    'literal_token_multiset_exact': True,
                    'literal_token_sequence_exact': left_literals == right_literals,
                    'comment_tokens_exact': True,
                    'word_token_sequence_exact': path != 'codex-rs/windows-sandbox-rs/src/lib.rs',
                    'non_whitespace_lexical_edits': ops})
    rows.append(row)

module_path = 'codex-rs/windows-sandbox-rs/src/lib.rs'
block = '#[cfg(all(test, target_os = "windows"))]\n#[path = "delete_permission_matrix_tests.rs"]\nmod delete_permission_matrix;\n'
assert pres[module_path].decode().count(block) == posts[module_path].decode().count(block) == 1
assert pres[module_path].decode().replace(block, '') == posts[module_path].decode().replace(block, '')
module_evidence = []
for name, expected in [('deny_read_acl.rs', 'dd3bc350e48299fe5a99e8d45eba61a239e5a186'),
                       ('deny_read_state.rs', 'fd073a4d45c781f0441839708f92e32d0831556c')]:
    p = OUT / 'context/codex-rs/windows-sandbox-rs/src' / name
    assert ident(p)['blob'] == expected
    assert files['codex-rs/windows-sandbox-rs/src/' + name]['sha'] == expected
    assert 'macro_rules!' not in p.read_text() and '#[macro_use' not in p.read_text()
    module_evidence.append(ident(p))
matrix = posts['codex-rs/windows-sandbox-rs/src/delete_permission_matrix_tests.rs'].decode()
assert 'macro_rules!' not in matrix and '#[macro_use' not in matrix
assert not re.search(r'#\s*\[\s*macro_use', pres[module_path].decode())

review = {
    'schema': 'hepta-A-actual-fmt-independent-review-v1',
    'verdict': 'STATIC_ACCEPT_ALL_17_ACTUAL_FORMATTER_POSTIMAGES',
    'native_execution': {'job_as_reported': '1a1aa209167-fc05-3db7', 'argv': status['argv'],
        'exit_code': status['exit_code'], 'duration_seconds': status['duration_seconds'],
        'command_status_receipt': ident(INPUT / 'original-fmt-status.json'),
        'controller_terminal_receipt': ident(INPUT / 'terminal.json'),
        'controller_review_stop_is_not_formatter_failure': True},
    'source': {'last_tested_A_tree': source_map['final_tree'], 'pre_fmt_tree': changes['before_tree'],
        'post_fmt_tree': changes['after_tree'], 'complete_tree_recomputed': True,
        'patch': ident(patch_path), 'patch_github_blob': '99ca4fb388b31cc0e0cbd6ed5646a0c77357b1c9',
        'native_changes_receipt': ident(INPUT / 'original-fmt-changes.json'),
        'complete_base_tree_receipt': ident(base_path), 'native_full_source_map': ident(map_path),
        'all_17_preimages_reverse_reconstructed_exact': True, 'all_17_postimages_forward_reconstructed_exact': True,
        'changes_outside_declared_17_paths': False, 'active_locks_or_manifests_changed': False},
    'per_path': rows,
    'substantive_review': [
        {'path': 'codex-rs/apply-patch/src/lib.rs', 'finding': 'The closure body changes from { ApplyPatchFailure::new(...) } to that same expression. No statement, capture, return value, evaluation order, error cause, or delta changes.'},
        {'path': 'codex-rs/windows-sandbox-rs/src/delete_permission_matrix_tests.rs', 'finding': 'The Err(error) match arm changes from return Err(error).with_context(...) as the arm expression to a block containing that same return with a terminal semicolon. Both return from finish immediately; no local is introduced and no later action becomes reachable. Exact object identity, same-DACL, retained bytes, delete-pending/link-count, after-close filesystem checks and strict outcomes remain.'},
        {'path': module_path, 'finding': 'The complete test-only cfg+path+mod item moves before deny_read_acl/deny_read_state. Removing that item makes pre/post byte-equal. No macro_use attribute or macro_rules definition exists in the moved or crossed modules. Its calls resolve through ordinary module paths; item order does not change runtime initialization or cfg scope.', 'crossed_module_primary': module_evidence},
        {'path': 'codex-rs/linux-sandbox/src/parent_lifecycle.rs', 'finding': 'Private role capture, low-FD duplication, unread proc identity/offset/flags checks, capability-first order, PR_SET then PF_EXITING/state validation, owned-FD drop and pre-user-fork ordering are retained. Only layout and optional trailing commas change.'},
        {'path': 'codex-rs/linux-sandbox/src/parent_lifecycle_tests.rs', 'finding': 'All marker strings, exact line equality, 5-second bounds, WNOWAIT process-group custody, kill/reparent ordering, no-rearm panic, pre-fork EBADF tuple and exec inode checks remain. Formatter changes assertion line numbers; this is not retroactive relocation of prior negative-run evidence.'},
        {'path': 'codex-rs/windows-sandbox-rs/src/acl_deny.rs', 'finding': 'SetEntriesInAclW receives the same four arguments in the same order; same-handle rights, masks, flags, DACL matching, error propagation and early no-op are unchanged.'},
        {'path': 'remaining changed Rust and Python files', 'finding': 'Every diff hunk was read. Full Python ASTs match. Rust literal/comment bytes and non-module word sequences match; only layout, optional trailing commas and the explicitly reviewed closure/match blocks remain. All original approvals, assertions, matrices, fixture commands, syscall arguments and deadlines retain their values and order.'},
    ],
    'cloud_only_git_roundtrip_commands': commands,
    'limits': ['No Cargo, Bazel, product test, native host command, shared-source/cache mutation, or ref mutation performed.',
               'No post-hygiene A test is implied; full 19,506 execution belongs to fb9 and its original 16 failures/25 early returns remain.',
               'Rust lexical diagnostics supplement full diff review; they are not a compiler or Rust AST equivalence proof.',
               'Root still owns remaining diff gates, final source qualification and publication.',
               'B remains unbound. The new 25,447,063,552-byte capacity reading does not authorize execution or cache deletion.'],
}
(OUT / 'actual-fmt-independent-review.json').write_text(json.dumps(review, ensure_ascii=False, indent=2) + '\n')
(OUT / 'actual-fmt-git-roundtrip.json').write_text(json.dumps({'scope': 'isolated cloud Git only', 'commands': commands,
    'pre_tree': changes['before_tree'], 'post_tree': changes['after_tree'], '17_preimages_and_postimages_exact': True}, indent=2) + '\n')
print(json.dumps({'review': ident(OUT / 'actual-fmt-independent-review.json'),
                  'roundtrip': ident(OUT / 'actual-fmt-git-roundtrip.json'),
                  'rust_token_edits': {row['path']: row.get('non_whitespace_lexical_edits') for row in rows},
                  'post_tree': treehash(files)}, ensure_ascii=False))
