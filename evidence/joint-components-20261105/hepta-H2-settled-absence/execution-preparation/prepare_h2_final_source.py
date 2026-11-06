from pathlib import Path
import base64
import gzip
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import time

ROOT = Path('/home/qian-qi/work/hepta-pq-effect-v4-20261105-93bfcf')
PARENT_SOURCE = ROOT / 'source'
SOURCE = ROOT / 'source-h2'
EVIDENCE = ROOT / 'evidence/h2-final-source-preparation'
H1 = '9f785cb201ba12ab0ae0f0d341c0f7912cc65efc'
H1_TREE = '24804b21d0306b617e12fa3f5b9454a12ed4ad41'
PREP = 'e452defdbcc7b48c4949eb3d5cbf73ed667ca879'
H2 = '620cb63ae9b58904483005bcb2c4e1507df99539'
TREE = 'f2cebe6d99deca596c170922b8e60d66648d7393'
BASE = '1556a4df6e279055fd8196f81a4ca2fe0f19384a'
REF = 'fix/hepta-joint-h2-20261105-93bfc-frozen'
EXPECTED_BLOBS = {
    'codex-rs/hepta-automation/src/authorized_effect.rs': 'b596b9061737a7bc8387807af27fdf5d2e230956',
    'codex-rs/hepta-automation/src/taskflow_step.rs': 'b3d06be21b9513a9776b0c593f99542b588e5b02',
    'codex-rs/hepta-agentd/src/automation_effect_host.rs': 'c11b1c06bdd5690fc48e49f3106a5f9916c90dd3',
    'codex-rs/hepta-automation/tests/support/authorized_owner_recovery_tests.rs': 'bceed0c4ce7815f8deb3ed47f16bbba5b99dcc4a',
    '.github/workflows/hepta-pq-policy-renewal.yml': '487bf796005439547ff1ac0366648a0f2daf236c',
}
ENV = dict(os.environ, GIT_NO_LAZY_FETCH='1', GIT_TERMINAL_PROMPT='0',
           PYTHONDONTWRITEBYTECODE='1', RUSTUP_TOOLCHAIN='1.96.0')
ENV['PATH'] = str(ROOT / 'tools/uv-0.11.3/bin') + ':' + ENV['PATH']
os.environ.update({key: ENV[key] for key in ['GIT_NO_LAZY_FETCH', 'GIT_TERMINAL_PROMPT',
                                           'PYTHONDONTWRITEBYTECODE', 'RUSTUP_TOOLCHAIN', 'PATH']})
sys.dont_write_bytecode = True
STATE = {'status': 'preparing-not-qualified', 'source': str(SOURCE),
         'requested_commit': H2, 'requested_tree': TREE, 'started_unix': time.time(),
         'scope': 'materialize exact already-formatted frozen H2 and verify complete raw source; no formatter, Cargo tests/builds or native credit'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(source, *args):
    return subprocess.check_output(['git', '-c', 'gc.auto=0', *args], cwd=source,
                                   env=ENV, timeout=180)


def publish(phase, **extra):
    STATE.update(phase=phase, **extra)
    path = EVIDENCE / 'status.pending.json'
    path.write_text(json.dumps(STATE, indent=2) + '\n')
    path.replace(EVIDENCE / 'status.json')
    print(json.dumps({'phase': phase, **extra}), flush=True)


def guard(source, label, clean):
    path = source / 'scripts/hepta_ci_exec.py'
    assert digest(path) == 'e55f5ca1200b2c9fc5af4158c42f460e71f3815166a962a5b892acfe9477b1d1'
    spec = importlib.util.spec_from_file_location('original_hepta_ci_exec', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    identity = module.identity(repository=source)
    raw_match = module.worktree_blobs_match(repository=source)
    entries = git(source, 'ls-tree', '-r', '-l', '-z', 'HEAD').split(b'\0')
    count = total = 0
    missing = []
    for entry in entries:
        if not entry:
            continue
        header, name = entry.split(b'\t', 1)
        mode, kind, oid, size = header.split()
        assert kind == b'blob'
        count += 1
        total += int(size)
        if not os.path.lexists(source / os.fsdecode(name)):
            missing.append(os.fsdecode(name))
    flags = [line for line in git(source, 'ls-files', '-v', '-z').decode().split('\0') if line]
    hidden = [line for line in flags if line[0] == 'S' or line[0].islower()]
    result = {'identity': identity, 'raw_git_blob_bytes_match': raw_match,
              'tracked_count': count, 'tracked_bytes': total, 'index_count': len(flags),
              'missing': missing, 'hidden': hidden,
              'tree_inventory_sha256': hashlib.sha256(b'\0'.join(entries)).hexdigest(),
              'guard_sha256': digest(path),
              'cargo_lock_sha256': digest(source / 'codex-rs/Cargo.lock'),
              'toolchain_file_sha256': digest(source / 'codex-rs/rust-toolchain.toml'),
              'nextest_config_sha256': digest(source / 'codex-rs/.config/nextest.toml')}
    (EVIDENCE / (label + '.json')).write_text(json.dumps(result, indent=2) + '\n')
    assert count == len(flags) and not missing and not hidden
    if clean:
        assert raw_match and not identity['dirty']
    return result



def main():
    EVIDENCE.mkdir(mode=0o700)
    previous = json.loads((ROOT / 'evidence/h2-format-preparation-1/result.json').read_text())
    assert previous['source'] == PREP and previous['format_exit_code'] == 0
    assert git(SOURCE, 'rev-parse', 'HEAD').decode().strip() == PREP
    assert hashlib.sha256(git(SOURCE, 'diff', '--binary', 'HEAD')).hexdigest() == previous['delta_sha256']
    configurations = [Path(path) for path in previous['configurations']]
    configs = {str(path): digest(path) for path in configurations}
    assert configs == previous['configurations']
    for path, expected in previous['formatted_file_sha256'].items():
        assert digest(SOURCE / path) == expected
    before = guard(SOURCE, 'formatted-preparation-before', clean=False)
    publish('fetch-frozen-h2-source', configuration_before=configs)
    with (EVIDENCE / 'fetch.log').open('xb') as log:
        fetch_env = dict(ENV, GIT_NO_LAZY_FETCH='0')
        subprocess.run(['git', '-c', 'gc.auto=0', 'fetch', '--no-tags', '--no-filter', 'origin', REF],
                       cwd=SOURCE, env=fetch_env, stdout=log, stderr=subprocess.STDOUT,
                       timeout=180, check=True)
        assert git(SOURCE, 'rev-parse', 'FETCH_HEAD').decode().strip() == H2
        assert git(SOURCE, 'rev-parse', H2 + '^{tree}').decode().strip() == TREE
        assert git(SOURCE, 'rev-parse', H2 + '^').decode().strip() == PREP
        assert set(git(SOURCE, 'diff', '--name-only', PREP, H2).decode().splitlines()) == set(previous['delta_paths'])
        for path in previous['delta_paths']:
            blob = EXPECTED_BLOBS[path]
            assert git(SOURCE, 'rev-parse', H2 + ':' + path).decode().strip() == blob
            content = subprocess.check_output(['git', '-c', 'gc.auto=0', 'cat-file', 'blob', blob],
                                              cwd=SOURCE, env=fetch_env, stderr=log, timeout=180)
            assert content == (SOURCE / path).read_bytes(), 'frozen source differs from actual formatter'
    # Checkout cannot overwrite any differing local data: every working-tree
    # change already equals the frozen reviewed formatter commit.
    git(SOURCE, 'diff', '--exit-code', H2)
    with (EVIDENCE / 'checkout.log').open('xb') as log:
        subprocess.run(['git', 'checkout', '--detach', H2], cwd=SOURCE, env=ENV,
                       stdout=log, stderr=subprocess.STDOUT, timeout=180, check=True)
    after = guard(SOURCE, 'frozen-source-after', clean=True)
    assert after['identity']['commit'] == H2 and after['identity']['tree'] == TREE
    assert after['tracked_count'] == 11839 and after['tracked_bytes'] == 183391637
    for path, blob in EXPECTED_BLOBS.items():
        assert git(SOURCE, 'rev-parse', 'HEAD:' + path).decode().strip() == blob
    parent = guard(PARENT_SOURCE, 'original-h1-source-after', clean=True)
    assert parent == json.loads((ROOT / 'evidence/h2-format-preparation-1/original-h1-before.json').read_text())
    final_configs = {str(path): digest(path) for path in configurations}
    assert configs == final_configs
    record = {'status': 'complete-source-ready-not-native-qualified', 'source': H2, 'tree': TREE,
              'source_path': str(SOURCE), 'before': before, 'after': after,
              'configurations': configs, 'configuration_after': final_configs,
              'configuration_unchanged': True, 'original_h1_source_unchanged': True,
              'native_credit': False, 'finished_unix': time.time()}
    (EVIDENCE / 'result.json').write_text(json.dumps(record, indent=2) + '\n')
    publish('complete', **record)


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        if EVIDENCE.exists():
            publish('failed', status='failed', error=repr(error), finished_unix=time.time())
        raise
