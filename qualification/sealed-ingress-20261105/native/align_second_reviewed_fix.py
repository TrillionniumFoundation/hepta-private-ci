#!/usr/bin/env python3
"""Align already reviewed working bytes to exact S; do not rerun native tests/fix."""
import fcntl
import gzip
import hashlib
import importlib.util
import json
import pathlib
import subprocess
import sys
import time

TASK = pathlib.Path('/home/qq/work/hepta-convergence-20261105-0c901b')
SOURCE = TASK / 'source-next'
FIRST = TASK / 'source'
OLD_HEAD = 'eed6541df0add428add8e2d9ab2cbd54a961abeb'
OLD_TREE = 'b8ce8b96a759f522cb7db60027d4844f1b3ad974'
NEW_HEAD = '0766fc4d5feabea9569d48e7eca4e0a3431bd0f5'
NEW_TREE = '1cfb78c47f636a60dcfa9968ffd7e44a054d58cc'
FIRST_HEAD = '432421d0d9ca9d82c5e3401fe3425af29131505a'
FIRST_TREE = 'd93136bb5e318ea4131bfb5cb0b9ac9310f27d1d'
CHANGED = 'codex-rs/hepta-intelligence/src/plasticity_product_tests.rs'
FORMAT_BASE = '4e31abc907f09740d402d1ddef7a1d2fe0a366a6'
PINNED_RECEIPTS = {
    'native-desktop-regression-v1/receipt.json': '4b133f93c90f5e27910a8d729b9b89ffdffb01d0bb659e491406bde484f06c19',
    'native-green-v2/receipt.json': 'f47d72c3930e2575b567fb8acaeb999f6696fab34bdcdd81ccd56b542fd81588',
    'native-fix-v1/receipt.json': 'ae54b470fd20e079d33602f60abffc3f130816586974b297cebe2f6ea3704d3b',
    'native-sealed-red-q-decision-v1/receipt.json': 'a7fc0b3cf48abeb3d66bd124c553d606c7555f9a63f4c9a679c9a269ed4d88b6',
    'native-sealed-red-q-agentd-v1/receipt.json': '6b3d09bac8a4e5cac69fd423a14fc2a19b7e0ba65139acd82c09c2ddf496c5e4',
    'native-sealed-red-q-plasticity-v2/receipt.json': '4cffc7cac9855131854689730fe1d9ead021b6ea45eaf2c12aebd77101b2a34e',
    'native-sealed-red-q-selector-v1/receipt.json': '41c062e316dfd9f6f18bc0e129b8aebfa62d6211b715642e9284d0e6c6e57419',
    'native-sealed-green-v1/receipt.json': 'ab6da7188d4354a088025ec0202533c025436d6f7fcf70196913ef24deb82488',
    'native-sealed-fix-v1/receipt.json': 'cb1f12c6d7e4c09f3e5c6df4a9f9f337d28540bc4e81c7d5c2c9b45ee2b5504c',
    'native-sealed-remaining-pipeline-v2/receipt.json': 'df53252839fc2c66102b33614456b0648d2028ea8e85b839baee3fe9e67c5612',
    'native-second-postfix-scope-v1/receipt.json': '2d139a714003f0e0f0e1960c499969f82872f40326a6abc23af86e01dbbec24f',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def need(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def main():
    evidence = TASK / 'evidence/native-second-postfix-alignment-v1'
    evidence.mkdir(exist_ok=False)
    receipt = {'schema': 'hepta.second-native-reviewed-postfix-alignment.v1', 'state': 'preflight',
               'source': str(SOURCE), 'tested_head': OLD_HEAD, 'tested_tree': OLD_TREE,
               'reviewed_postfix_head': NEW_HEAD, 'reviewed_postfix_tree': NEW_TREE,
               'first_head_retained': FIRST_HEAD, 'steps': [], 'original_receipts': PINNED_RECEIPTS,
               'tests_rerun_after_fix': False, 'fix_rerun': False,
               'historical_805_passes_apply_only_to_tested_E': True,
               'script_sha256': sha(pathlib.Path(__file__).read_bytes())}
    env = None
    native_lock = None

    def save():
        tmp = evidence / 'receipt.json.tmp'
        tmp.write_text(json.dumps(receipt, indent=2) + '\n')
        tmp.replace(evidence / 'receipt.json')

    def run(name, argv, cwd=SOURCE):
        print(json.dumps({'stage': name, 'argv': argv}), flush=True)
        started = time.time()
        r = subprocess.run(argv, cwd=cwd, env=env, capture_output=True)
        for stream, data in [('stdout', r.stdout), ('stderr', r.stderr)]:
            (evidence / (name + '.' + stream)).write_bytes(data)
        receipt['steps'].append({'name': name, 'argv': argv, 'exit_code': r.returncode,
                                 'elapsed_seconds': time.time() - started,
                                 'stdout_sha256': sha(r.stdout), 'stderr_sha256': sha(r.stderr)})
        save()
        need(r.returncode == 0, name + ' failed')
        return r.stdout

    def original_receipts():
        for rel, expected in PINNED_RECEIPTS.items():
            need(sha((TASK / 'evidence' / rel).read_bytes()) == expected, 'Original receipt changed: ' + rel)

    def first_check(suffix):
        identity = run('first-identity-' + suffix, ['git', '--no-optional-locks', 'rev-parse', 'HEAD', 'HEAD^{tree}'], FIRST)
        need(identity.decode().splitlines() == [FIRST_HEAD, FIRST_TREE], 'First source identity changed')
        need(run('first-clean-' + suffix, ['git', '--no-optional-locks', 'status', '--porcelain=v1', '--untracked-files=all'], FIRST) == b'',
             'First source is not clean')

    try:
        save()
        runner = TASK / 'native-sealed-gate-v2/run_native_round2.py'
        need(sha(runner.read_bytes()) == '46552f047784d07b825cec59e0358cfbb02a010f448b7538bb0fadc15ea2f7df', 'Frozen environment module changed')
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location('native_environment_only', runner)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        env, receipt['verified_environment'] = module.native_environment()
        native_lock = (TASK / 'evidence/native-sealed-validation.lock').open('a+b')
        fcntl.flock(native_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        original_receipts()
        first_check('before')
        need(run('old-identity', ['git', 'rev-parse', 'HEAD', 'HEAD^{tree}']).decode().splitlines() == [OLD_HEAD, OLD_TREE], 'Old source identity changed')
        expected = json.loads((TASK / 'evidence/native-sealed-fix-v1/receipt.json').read_text())['after']
        before = []
        for item in expected:
            data = (SOURCE / item['path']).read_bytes()
            value = {'path': item['path'], 'sha256': sha(data), 'git_blob': blob(data)}
            need(value == item, 'Reviewed after-file differs')
            before.append(value)
        receipt['reviewed_bytes_before_alignment'] = before
        lock_bytes = (SOURCE / 'codex-rs/Cargo.lock').read_bytes()
        need(sha(lock_bytes) == '4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c', 'Lock drift')
        run('fetch-exact-reviewed-commit', ['git', 'fetch', '--depth=1', '--filter=blob:none', 'origin', NEW_HEAD])
        commit = run('new-commit-object', ['git', 'cat-file', '-p', NEW_HEAD]).decode().splitlines()
        parents = [line.split(' ', 1)[1] for line in commit if line.startswith('parent ')]
        trees = [line.split(' ', 1)[1] for line in commit if line.startswith('tree ')]
        need(parents == [OLD_HEAD] and trees == [NEW_TREE], 'New commit parent/tree differs')
        receipt['ordered_parents'] = parents
        changed = run('committed-delta', ['git', 'diff', '--no-ext-diff', '--no-renames', '--name-only', '-z', OLD_HEAD, NEW_HEAD, '--'])
        need(changed == (CHANGED + '\0').encode(), 'Published commit changes unexpected paths')
        need(run('committed-after-blob', ['git', 'rev-parse', NEW_HEAD + ':' + CHANGED]).decode().strip() == '2b85adacb939c778b13f42177467b5959d16b50a',
             'Published after blob differs')
        need(run('untracked-before', ['git', 'ls-files', '--others', '--exclude-standard', '-z']) == b'', 'Untracked files present')
        run('all-tracked-bytes-equal-new-commit', ['git', 'diff', '--exit-code', '--no-ext-diff', NEW_HEAD, '--'])
        # The preceding full tracked comparison is mandatory before moving only
        # the task-owned HEAD/index. This operation never writes working bytes.
        run('align-index-head-only', ['git', 'reset', '--mixed', NEW_HEAD])
        need(run('new-identity', ['git', 'rev-parse', 'HEAD', 'HEAD^{tree}']).decode().splitlines() == [NEW_HEAD, NEW_TREE], 'Aligned identity differs')
        need(run('clean-after-alignment', ['git', 'status', '--porcelain=v1', '--untracked-files=all']) == b'', 'Aligned source not clean')
        tree = run('complete-tree', ['git', 'ls-tree', '-r', '-z', NEW_HEAD])
        rust = []
        for entry in tree.split(b'\0'):
            if not entry:
                continue
            meta, path_bytes = entry.split(b'\t', 1)
            mode, kind, oid = meta.decode().split(' ')
            path = path_bytes.decode()
            if kind != 'blob' or not path.endswith('.rs'):
                continue
            data = (SOURCE / path).read_bytes()
            need(blob(data) == oid, 'Tracked Rust blob mismatch: ' + path)
            rust.append({'path': path, 'mode': mode, 'git_blob': oid, 'sha256': sha(data)})
        need(len(rust) == 5314, 'Unexpected tracked Rust count')
        inventory = (json.dumps(rust, indent=2) + '\n').encode()
        (evidence / 'verified-rust-blobs.json').write_bytes(inventory)
        zipped = gzip.compress(inventory, mtime=0)
        (evidence / 'verified-rust-blobs.json.gz').write_bytes(zipped)
        receipt['rust_inventory'] = {'count': len(rust), 'path': str(evidence / 'verified-rust-blobs.json'),
                                     'size': len(inventory), 'sha256': sha(inventory),
                                     'gzip_path': str(evidence / 'verified-rust-blobs.json.gz'),
                                     'gzip_size': len(zipped), 'gzip_sha256': sha(zipped)}
        receipt['reviewed_bytes_after_alignment'] = []
        for item in before:
            data = (SOURCE / item['path']).read_bytes()
            value = {'path': item['path'], 'sha256': sha(data), 'git_blob': blob(data)}
            need(value == item, 'Working bytes changed during alignment')
            receipt['reviewed_bytes_after_alignment'].append(value)
        need((SOURCE / 'codex-rs/Cargo.lock').read_bytes() == lock_bytes, 'Lock bytes changed')
        need(run('committed-lock', ['git', 'rev-parse', NEW_HEAD + ':codex-rs/Cargo.lock']).decode().strip() == blob(lock_bytes), 'Committed lock differs')
        run('full-stack-format-check-only', ['just', 'fmt', '--base', FORMAT_BASE, '--check'])
        need(run('final-clean', ['git', 'status', '--porcelain=v1', '--untracked-files=all']) == b'', 'Format check changed source')
        first_check('after')
        original_receipts()
        receipt.update(state='reviewed-postfix-exact-source-aligned', exit_code=0, clean=True,
                       working_bytes_unchanged_by_alignment=True, cargo_lock_sha256=sha(lock_bytes),
                       only_committed_delta=[CHANGED], original_receipts_preserved=True,
                       first_source_unchanged_clean=True)
    except Exception as error:
        receipt.update(state='postfix-alignment-blocked', exit_code=1, error=str(error))
    finally:
        if native_lock is not None:
            native_lock.close()
        save()
    print(json.dumps({'state': receipt['state'], 'exit_code': receipt['exit_code'],
                      'receipt': str(evidence / 'receipt.json'), 'sha256': sha((evidence / 'receipt.json').read_bytes()),
                      'rust_inventory': receipt.get('rust_inventory')}), flush=True)
    return receipt['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
