#!/usr/bin/env python3
"""Independent exact two-edit and complete-tree verification; no Rust execution."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

BASE = '67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed'
TREE = '3982ba56dc5a3f1da0c1de7ea57992f88125c359'
AFTER = 'e60df9b57046df73cc1af53d8773cff48eafd311'
EDITS = {
    'codex-rs/arg0/src/bin/test_arg0_preflight.rs': (
        'be0507472a7277fbb9c22f9c946039b09127355d',
        '6fbb88e17c1da7d9533efe6f40eae77e60c3b085',
        '                let error = result.expect_err("refused preflight must return its original error");',
        '                let Err(error) = result else {\n'
        '                    bail!("refused preflight must return its original error");\n'
        '                };'),
    'codex-rs/arg0/src/preflight_tests.rs': (
        '7e315f1aa7284b3e0899d31520568c474cbddd0d',
        '1947350263edd252723d88c8179f8fe7a3a018aa',
        '            let process = child.0.as_mut().expect("owned child remains until reaped");',
        '            let process = child\n'
        '                .0\n'
        '                .as_mut()\n'
        '                .ok_or_else(|| anyhow::anyhow!("owned child remains until reaped"))?;'),
}

def identity(data):
    return {'bytes': len(data), 'git_blob': hashlib.sha1(
        b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest(),
        'sha256': hashlib.sha256(data).hexdigest()}

def merkle(leaves):
    nodes = {'': {}}
    for path, leaf in leaves.items():
        parts = path.split('/')
        assert all(p and p not in ('.', '..') for p in parts)
        for i in range(len(parts)-1):
            parent, child = '/'.join(parts[:i]), '/'.join(parts[:i+1])
            nodes.setdefault(parent, {})[parts[i]] = ('40000', child, True)
            nodes.setdefault(child, {})
        parent = '/'.join(parts[:-1])
        assert parts[-1] not in nodes[parent]
        nodes[parent][parts[-1]] = (leaf['mode'], leaf['sha'], False)
    hashes = {}
    for path in sorted(nodes, key=lambda p: (p.count('/'), bool(p)), reverse=True):
        body = b''
        for name, (mode, ref, is_tree) in sorted(nodes[path].items(),
                key=lambda kv: (kv[0] + ('/' if kv[1][2] else '')).encode()):
            sha = hashes[ref] if is_tree else ref
            body += mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(sha)
        hashes[path] = hashlib.sha1(b'tree ' + str(len(body)).encode() + b'\0' + body).hexdigest()
    return hashes[''], hashes

def tree_input(path, expected):
    raw = path.read_bytes()
    obj = json.loads(raw)
    assert obj['sha'] == expected and obj['truncated'] is False
    rows = {e['path']: e for e in obj['tree']}
    assert len(rows) == len(obj['tree'])
    leaves = {p: {'path':p, 'mode':e['mode'], 'type':e['type'], 'sha':e['sha']}
              for p,e in rows.items() if e['type'] != 'tree'}
    calculated, dirs = merkle(leaves)
    assert calculated == expected
    assert {p:e['sha'] for p,e in rows.items() if e['type']=='tree'} == {p:s for p,s in dirs.items() if p}
    assert len(leaves) == 10582 and len(dirs) == 1571
    return leaves, dirs, identity(raw)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    root = ap.parse_args().root.resolve()
    author = root/'author-frozen'
    before, dirs, authority = tree_input(root/'authority/main67-full-tree.json', TREE)
    intended, new_dirs, intended_id = tree_input(author/'intended-full-tree.json', AFTER)
    after = dict(before)
    files = []
    for path, (old_sha, new_sha, old_text, new_text) in EDITS.items():
        old, new = (author/'preimage'/path).read_bytes(), (author/'candidate'/path).read_bytes()
        assert identity(old)['git_blob'] == old_sha == before[path]['sha']
        assert identity(new)['git_blob'] == new_sha
        assert old.count(old_text.encode()) == new.count(new_text.encode()) == 1
        assert old.replace(old_text.encode(), new_text.encode()) == new
        assert new.replace(new_text.encode(), old_text.encode()) == old
        get = json.loads((root/'original'/('postimage-'+new_sha+'.GET.json')).read_bytes())
        assert get['structuredContent']['content'].encode() == new
        counts = {term.decode(): old.count(term) for term in
                  (b'#[test]',b'ensure!(',b'assert!(',b'assert_eq!(')}
        assert counts == {term: new.count(term.encode()) for term in counts}
        assert b'.expect(' not in new and b'.expect_err(' not in new
        after[path] = {**before[path], 'sha':new_sha}
        files.append({'path':path,'preimage':identity(old),'postimage':identity(new),
                      'exact_forward_and_inverse_full_bytes':True,'fresh_full_GET_equal':True,
                      'original_assertion_counts':counts})
    actual, calculated_dirs = merkle(after)
    assert actual == AFTER and calculated_dirs == new_dirs and after == intended
    changed = sorted(p for p in before if before[p] != after[p])
    assert changed == sorted(EDITS)
    fixture = (author/'candidate'/next(iter(EDITS))).read_text()
    tests = (author/'candidate/codex-rs/arg0/src/preflight_tests.rs').read_text()
    assert 'use anyhow::bail;' in fixture and 'pub(super) fn run() -> Result<()>' in fixture
    assert 'fn run(&self, mode: Mode) -> Result<()>' in tests
    assert 'const CHILD_DEADLINE: Duration = Duration::from_secs(10);' in tests
    assert tests.count('#[test]') == 3
    patch = (author/'candidate.patch').read_bytes()
    operations=[]
    with tempfile.TemporaryDirectory(prefix='arg0-independent-patch-') as tmp:
        work=Path(tmp)
        for path in EDITS:
            dest=work/path;dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes((author/'preimage'/path).read_bytes())
        for flags, expected in [(['--check'],None),([], 'candidate'),(['--reverse','--check'],None),(['--reverse'],'preimage')]:
            p=subprocess.run(['git','apply',*flags,str(author/'candidate.patch')],cwd=work,capture_output=True,timeout=15)
            assert p.returncode==0 and not p.stdout and not p.stderr
            if expected: assert all((work/f).read_bytes()==(author/expected/f).read_bytes() for f in EDITS)
            operations.append({'argv':['git','apply',*flags,'<frozen candidate.patch>'],'exit':0})
    report={'schema':'arg0-clippy-independent-static-v1','source_head':BASE,
        'source_tree':TREE,'candidate_tree':actual,'complete_base_tree':authority,
        'complete_intended_tree':intended_id,'files':files,'changed_paths':changed,
        'original_leaves':len(before),'unchanged_leaves':len(before)-len(changed),
        'directories':len(dirs),'patch':identity(patch),'git_apply_operations':operations,
        'three_original_tests_and_all_assertions_unchanged':True,
        'original_spawn_argv_environment_10_second_deadline_poll_and_Drop_unchanged':True,
        'unexpected_state_remains_failure':'Two fixture panic paths become Result errors; neither path can return success.',
        'ordinary_result_error_paths_unchanged':True,
        'new_Rust_tests_or_native_runs':False,'Rust_format_compile_clippy_test_executed':False,
        'scope':'STATIC_SOURCE_ACCEPTANCE_ONLY; automatic original GNU clippy and tests remain pending.'}
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
