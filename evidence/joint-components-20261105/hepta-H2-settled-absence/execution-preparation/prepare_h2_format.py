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
EVIDENCE = ROOT / 'evidence/h2-format-preparation-1'
H1 = '9f785cb201ba12ab0ae0f0d341c0f7912cc65efc'
H1_TREE = '24804b21d0306b617e12fa3f5b9454a12ed4ad41'
H2 = 'e452defdbcc7b48c4949eb3d5cbf73ed667ca879'
TREE = '3fdf50c0b24a11b92794c9ab027ad073aae87515'
BASE = '1556a4df6e279055fd8196f81a4ca2fe0f19384a'
REF = 'fix/hepta-joint-h2-prepare-20261105-93bfc'
EXPECTED_BLOBS = {
    'codex-rs/hepta-automation/src/authorized_effect.rs': 'b596b9061737a7bc8387807af27fdf5d2e230956',
    'codex-rs/hepta-automation/src/taskflow_step.rs': '43c7df417047b4295b7120c8dbcba7357504d151',
    'codex-rs/hepta-agentd/src/automation_effect_host.rs': 'c11b1c06bdd5690fc48e49f3106a5f9916c90dd3',
    'codex-rs/hepta-automation/tests/support/authorized_owner_recovery_tests.rs': '12cabc35fd44816ec7c6913a9a47d9b03cda5990',
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
         'scope': 'isolated worktree materialization and original 300-second formatter; no Cargo tests/builds'}


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
    assert not SOURCE.exists(), 'H2 preparation worktree already exists; reconcile original job'
    previous = json.loads((ROOT / 'evidence/joint-h1-native-attempt-1/configuration-after.json').read_text())
    configurations = [Path(path) for path in previous['after']]
    protected = {str(path): digest(path) for path in configurations}
    assert protected == previous['after'] and previous['unchanged']
    prior = guard(PARENT_SOURCE, 'original-h1-before', clean=True)
    assert prior['identity']['commit'] == H1 and prior['identity']['tree'] == H1_TREE
    assert prior['tracked_count'] == 11839 and prior['tracked_bytes'] == 183369088
    publish('fetch-exact-h2-preparation', protected_configuration_before=protected)
    with (EVIDENCE / 'fetch.log').open('xb') as log:
        fetch_env = dict(ENV, GIT_NO_LAZY_FETCH='0')
        subprocess.run(['git', '-c', 'gc.auto=0', 'fetch', '--no-tags', '--no-filter', 'origin', REF],
                       cwd=PARENT_SOURCE, env=fetch_env, stdout=log, stderr=subprocess.STDOUT,
                       timeout=180, check=True)
        assert git(PARENT_SOURCE, 'rev-parse', 'FETCH_HEAD').decode().strip() == H2
        assert git(PARENT_SOURCE, 'rev-parse', H2 + '^{tree}').decode().strip() == TREE
        assert git(PARENT_SOURCE, 'rev-parse', H2 + '^').decode().strip() == H1
        changed = git(PARENT_SOURCE, 'diff', '--name-only', H1, H2).decode().splitlines()
        assert set(changed) == set(EXPECTED_BLOBS)
        materialized = []
        for path, expected in EXPECTED_BLOBS.items():
            assert git(PARENT_SOURCE, 'rev-parse', H2 + ':' + path).decode().strip() == expected
            content = subprocess.check_output(['git', '-c', 'gc.auto=0', 'cat-file', 'blob', expected],
                                              cwd=PARENT_SOURCE, env=fetch_env, stderr=log, timeout=180)
            assert hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest() == expected
            materialized.append({'path': path, 'blob': expected, 'bytes': len(content),
                                 'sha256': hashlib.sha256(content).hexdigest()})
    (EVIDENCE / 'materialized-known-blobs.json').write_text(json.dumps(materialized, indent=2) + '\n')
    publish('create-isolated-h2-worktree', materialized_known_blobs=materialized)
    with (EVIDENCE / 'worktree.log').open('xb') as log:
        subprocess.run(['git', '-c', 'gc.auto=0', 'worktree', 'add', '--detach', str(SOURCE), H2],
                       cwd=PARENT_SOURCE, env=ENV, stdout=log, stderr=subprocess.STDOUT,
                       timeout=180, check=True)
        # The original repository uses per-worktree configuration. Only this
        # new worktree is materialized; protected common/parent config stays fixed.
        assert git(SOURCE, 'config', '--get', 'extensions.worktreeConfig').decode().strip() == 'true'
        subprocess.run(['git', 'sparse-checkout', 'disable'], cwd=SOURCE, env=ENV,
                       stdout=log, stderr=subprocess.STDOUT, timeout=180, check=True)
    own_config = Path(git(SOURCE, 'rev-parse', '--git-path', 'config.worktree').decode().strip())
    if not own_config.is_absolute():
        own_config = SOURCE / own_config
    configurations.append(own_config)
    configs = {str(path): digest(path) for path in configurations}
    assert all(configs[path] == value for path, value in protected.items())
    uv = ROOT / 'tools/uv-0.11.3/bin/uv'
    assert digest(uv) == 'fa5fc652fa5ed5b44fa8e7dda507f27975c02f59643787fd8ab4bf36f1ba7438'
    before = guard(SOURCE, 'joint-before-format', clean=True)
    assert before['identity']['commit'] == H2 and before['identity']['tree'] == TREE
    assert before['tracked_count'] == 11839 and before['tracked_bytes'] == 183390834
    publish('format-h2-original-budget', joint_before=before, configuration_before=configs,
            format_command=['just', 'fmt', '--base', BASE], format_timeout_seconds=300)
    with (EVIDENCE / 'format.log').open('xb') as log:
        result = subprocess.run(['just', 'fmt', '--base', BASE], cwd=SOURCE, env=ENV,
                                stdout=log, stderr=subprocess.STDOUT, timeout=300)
    after = guard(SOURCE, 'joint-after-format', clean=False)
    delta = git(SOURCE, 'diff', '--binary', 'HEAD')
    (EVIDENCE / 'format.patch').write_bytes(delta)
    paths = git(SOURCE, 'diff', '--name-only', 'HEAD').decode().splitlines()
    assert set(paths) <= set(EXPECTED_BLOBS), 'formatter changed an unrelated H1 path'
    assert not git(SOURCE, 'ls-files', '--others', '--exclude-standard').strip()
    after_configs = {str(path): digest(path) for path in configurations}
    assert after_configs == configs, 'shared or worktree configuration changed'
    parent_after = guard(PARENT_SOURCE, 'original-h1-after', clean=True)
    assert parent_after == prior, 'H1 source was modified'
    files = [{'path': path, 'sha256': digest(SOURCE / path), 'content': (SOURCE / path).read_text()}
             for path in paths]
    if paths:
        payload = json.dumps({'paths': paths, 'patch': delta.decode(), 'files': files},
                             separators=(',', ':')).encode()
        encoded = base64.b64encode(gzip.compress(payload, mtime=0)).decode()
        (EVIDENCE / 'format-delta-export.json').write_text(json.dumps({
            'payload_sha256': hashlib.sha256(payload).hexdigest(), 'gzip_base64': encoded}) + '\n')
    record = {'status': 'formatted-not-tested' if result.returncode == 0 else 'format-failed',
              'format_exit_code': result.returncode, 'source': H2, 'tree': TREE,
              'source_path': str(SOURCE), 'before': before, 'after': after,
              'protected_h1_source_unchanged': parent_after == prior,
              'configurations': configs, 'configuration_after': after_configs,
              'configuration_unchanged': configs == after_configs,
              'delta_paths': paths, 'delta_sha256': hashlib.sha256(delta).hexdigest(),
              'formatted_file_sha256': {row['path']: row['sha256'] for row in files},
              'native_credit': False, 'finished_unix': time.time()}
    (EVIDENCE / 'result.json').write_text(json.dumps(record, indent=2) + '\n')
    publish('complete', **record)
    assert result.returncode == 0, 'original formatter failed'
    if not paths:
        assert after == before


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        if EVIDENCE.exists():
            publish('failed', status='failed', error=repr(error), finished_unix=time.time())
        raise
