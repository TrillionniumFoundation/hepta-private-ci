#!/usr/bin/env python3
"""Independent immutable-input, tree, patch and offline-control verification."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import yaml

OLD = '88b6308899357e23b4a4058aecd4527b4edcee9b'
NEW = '57f6095d18c5517c9e7cf7d0de05b9645b106152'
TREE = '3982ba56dc5a3f1da0c1de7ea57992f88125c359'
NEW_TREE = '06c4e2f80884b169e31d8a5edf04438486a9ee81'
PATH = '.github/workflows/cargo-deny.yml'
COMMAND = 'cargo +1.95.0 deny --locked --all-features check --config deny.toml'


def identity(data):
    return {'bytes': len(data), 'git_blob': hashlib.sha1(
        b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest(),
        'sha256': hashlib.sha256(data).hexdigest()}


def merkle(leaves):
    nodes = {'': {}}
    for path, leaf in leaves.items():
        parts = path.split('/')
        assert all(p and p not in ('.', '..') for p in parts)
        for i in range(len(parts) - 1):
            parent, child = '/'.join(parts[:i]), '/'.join(parts[:i + 1])
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    args = ap.parse_args()
    root = args.root.resolve()
    src = root / 'author-frozen'
    freeze_bytes = (src / 'SOURCE_AND_STATIC_FREEZE.json').read_bytes()
    freeze = json.loads(freeze_bytes)
    assert freeze['workflow_git_blob'] == NEW and freeze['expected_full_tree'] == NEW_TREE
    assert len(freeze['members']) == len({r['path'] for r in freeze['members']}) == 515
    for row in freeze['members']:
        path = Path(row['path'])
        assert not path.is_absolute() and '..' not in path.parts
        assert identity((src / path).read_bytes()) == {k: row[k] for k in ('bytes', 'git_blob', 'sha256')}
    old, new = (src / 'source' / PATH).read_bytes(), (src / 'candidate' / PATH).read_bytes()
    assert identity(old)['git_blob'] == OLD and identity(new)['git_blob'] == NEW
    assert old == (root / 'original/cargo-deny.workflow.yml').read_bytes()
    fetched = json.loads((root / 'original/frozen-workflow.GET.json').read_bytes())
    assert fetched['structuredContent']['content'].encode() == new
    base_tree = json.loads((src / 'authority/main67-full-tree.json').read_bytes())
    assert base_tree['sha'] == TREE and base_tree['truncated'] is False
    entries = {x['path']: x for x in base_tree['tree']}
    assert len(entries) == len(base_tree['tree'])
    leaves = {p: x for p, x in entries.items() if x['type'] != 'tree'}
    base_hash, dirs = merkle(leaves)
    assert base_hash == TREE and len(leaves) == 10582 and len(dirs) == 1571
    assert {p: x['sha'] for p, x in entries.items() if x['type'] == 'tree'} == {p: h for p, h in dirs.items() if p}
    assert leaves[PATH]['sha'] == OLD
    after = dict(leaves)
    after[PATH] = {**leaves[PATH], 'sha': NEW}
    new_hash, new_dirs = merkle(after)
    assert new_hash == NEW_TREE and len(new_dirs) == 1571
    assert [p for p in after if after[p] != leaves[p]] == [PATH]

    a, b = (yaml.load(raw, Loader=yaml.BaseLoader) for raw in (old, new))
    assert {k: v for k, v in a.items() if k != 'jobs'} == {k: v for k, v in b.items() if k != 'jobs'}
    ja, jb = a['jobs']['cargo-deny'], b['jobs']['cargo-deny']
    assert {k: v for k, v in ja.items() if k != 'steps'} == {k: v for k, v in jb.items() if k != 'steps'}
    assert ja['timeout-minutes'] == '30' and ja['runs-on'] == 'ubuntu-latest'
    assert ja['defaults'] == {'run': {'working-directory': './codex-rs'}}
    sa, sb = ja['steps'], jb['steps']
    assert len(sa) == 6 and len(sb) == 9 and sa[:4] == sb[:4] and sa[5] == sb[5]
    assert sa[4]['run'] == COMMAND
    run, collect, final = sb[4]['run'], sb[6]['run'], sb[8]['run']
    assert run == (src / 'support/run.sh').read_text()
    assert collect == "python3 - <<'PY'\n" + (src / 'support/collect.py').read_text() + 'PY\n'
    assert final == (src / 'support/final-gate.sh').read_text()
    assert run.count(COMMAND) == 1
    assert COMMAND + ' 2>&1 | tee "${evidence_dir}/cargo-deny.log"\npipeline_status=("${PIPESTATUS[@]}")\n' in run
    assert 'continue-on-error' not in new.decode() and 'CARGO_TERM_COLOR' not in new.decode()
    assert sb[6]['if'] == sb[8]['if'] == 'always()'
    assert sb[7]['if'] == "always() && steps.collect_evidence.outcome == 'success' && steps.collect_evidence.outputs.safe_for_upload == 'true'"
    assert sb[7]['with']['path'] == '${{ steps.collect_evidence.outputs.public_dir }}'
    assert sb[7]['with']['if-no-files-found'] == 'error'
    assert sb[6]['env']['EVIDENCE_GITHUB_TOKEN'] == '${{ github.token }}'
    assert final.count(' = success') == 3
    primary = (root / 'original/rust-toolchain.action.yml').read_bytes()
    assert identity(primary)['git_blob'] == 'cabbec62b5151edf6026228ca868557d7e8bf6bb'
    assert primary == (src / 'primary/rust-toolchain-action.yml').read_bytes()
    assert b'if [ -z "${CARGO_TERM_COLOR+set}" ]; then\n          echo CARGO_TERM_COLOR=always >> $GITHUB_ENV' in primary

    patch = (src / 'full.patch').read_bytes()
    commands = []
    with tempfile.TemporaryDirectory(prefix='cargo-deny-independent-patch-') as temp:
        work = Path(temp)
        target = work / PATH
        target.parent.mkdir(parents=True)
        target.write_bytes(old)
        for flags, expected in [(['--check'], None), ([], new), (['--reverse', '--check'], None), (['--reverse'], old)]:
            result = subprocess.run(['git', 'apply', *flags, str(src / 'full.patch')], cwd=work,
                                    capture_output=True, timeout=15)
            assert result.returncode == 0 and not result.stdout and not result.stderr
            if expected is not None:
                assert target.read_bytes() == expected
            commands.append({'argv': ['git', 'apply', *flags, '<frozen full.patch>'], 'exit': 0})
    replays = []
    for actual_name, expected_name in [('author-static-replay', 'static-01.stdout.json'), ('author-fake-replay', 'fake-controls-01.stdout.json')]:
        actual = (root / (actual_name + '.stdout.json')).read_bytes()
        assert (root / (actual_name + '.exit-code.txt')).read_text() == '0\n'
        assert not (root / (actual_name + '.stderr.txt')).read_bytes()
        assert actual == (src / expected_name).read_bytes()
        replays.append({'kind': actual_name, 'exit': 0, 'stderr_bytes': 0, 'stdout': identity(actual), 'full_bytes_equal': True})
    fixtures = json.loads((root / 'author-fake-replay.stdout.json').read_bytes())
    assert fixtures['case_count'] == 17 and fixtures['all_passed']
    assert all(c['original_command_invocations'] == 1 for c in fixtures['cases'])
    assert all(c['final_gate_exit'] != 0 for c in fixtures['cases'] if c['original_step_exit'] != 0 or not c['safe_for_upload'])
    result = {
        'schema': 'cargo-deny-independent-static-review-v1',
        'frozen_members': 515, 'frozen_total_bytes': sum(m['bytes'] for m in freeze['members']),
        'author_freeze_identity': identity(freeze_bytes), 'all_frozen_files_exact': True,
        'preimage': identity(old), 'candidate': identity(new), 'fresh_full_GET_equal': True,
        'base_tree': base_hash, 'candidate_tree': new_hash,
        'original_leaves': len(leaves), 'unchanged_leaves': len(leaves)-1, 'directories': len(dirs),
        'original_settings_and_setup_clean_steps_preserved': True,
        'exact_original_check_command': COMMAND, 'one_check_per_offline_fixture': True,
        'PIPESTATUS_immediate_and_original_exit_prioritized': True,
        'raw_private_log_and_checked_public_copy': 'Every uploaded file is constructed from the already-scanned bytes and read back for complete equality; no raw private directory upload.',
        'normal_ANSI_environment_preserved': True,
        'privacy_false_negative_corrected': 'ANSI normalization and unsupported-control check are repeated at every decoded view.',
        'patch': identity(patch), 'real_local_git_patch_operations': commands,
        'isolated_replays': replays,
        'runtime_source_scope': 'Records actual HEAD/tree; requires before/after equality and clean. External actual checkout/API binding remains required for native qualification.',
        'privacy_scope': 'Known values and recognized syntax/URI forms with four percent-decoding layers; no universal classifier for arbitrary unmarked unknown secrets.',
        'actual_cargo_deny_failure_cause': 'UNKNOWN',
        'real_cargo_Rust_build_CI_dispatch_or_rerun': False,
        'ref_mutation': False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
