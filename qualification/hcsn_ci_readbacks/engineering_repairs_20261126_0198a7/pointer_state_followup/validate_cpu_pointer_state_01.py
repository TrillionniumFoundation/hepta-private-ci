"""One normal/-O regression for the publication-state test fixture correction."""
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import resource
import signal
import subprocess
import sys
import tarfile
import time

ROOT = Path('/Users/qianqi/work/hepta-hcsn-fixes-20261126-0198a7')
PREFIX = 'qualification/hcsn_differentiable/replay_v1/'
CANDIDATE = '56741fb935d2497334c127d31ad900bff22c67983f72de70aa0a65ba790f96b9'
ARCHIVE = '6fff4e8a67f9e1719a46a8830193b819b17c3fba67674aaed2cab72cdefe2cd3'
SCAFFOLD = {'justfile': '74f869224eba12fc4212b043428e7f5b35b551d26f5b06161c25d8aca525f124',
            'scripts/format.py': '8d93d7a6261bbe5f2b9fceea228154f0be29f721015d05b4f538c30076dd80b3',
            'scripts/just-shell.py': '444d6b328d44abf6453b77b6acce2a0c881fc162ff30b20f352c85067797fbe9'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    assert len(sys.argv) == 2 and sha(Path(__file__).read_bytes()) == sys.argv[1]
    out = ROOT / 'cpu_pointer_contract_01'
    out.mkdir(exist_ok=False)
    source = out / 'source'
    source.mkdir()
    result = {'status': 'STARTED', 'runner_sha256': sys.argv[1], 'max_attempts': 1,
              'registered_parent_modes': ['normal', 'optimized'],
              'expected_methods_each': 6, 'automatic_retry': False, 'runs': [],
              'real_cpu_diagnostic_calls': 0, 'model_or_training_calls': 0,
              'cpu_profile_runtime_qualified': False,
              'runtime': {'python': sys.version, 'executable': sys.executable, 'platform': platform.platform()}}
    def save():
        temp = out / 'RESULT.tmp'
        temp.write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
        temp.replace(out / 'RESULT.json')
    save()
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONHASHSEED='0')
    env.pop('PYTHONOPTIMIZE', None)
    env['PATH'] = '/opt/homebrew/bin:' + env.get('PATH', '')
    try:
        for name, expected in SCAFFOLD.items():
            data = (ROOT / 'source' / name).read_bytes()
            assert sha(data) == expected
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (source / 'codex-rs').mkdir()
        for argv in (['git', 'init', '-q'], ['git', 'add', '--', *SCAFFOLD],
                     ['git', '-c', 'user.name=workflow-test', '-c', 'user.email=workflow-test@example.invalid',
                      'commit', '-q', '-m', 'Pin original formatter scaffold']):
            subprocess.run(argv, cwd=source, env=env, check=True, capture_output=True, timeout=30)
        raw = (ROOT / 'CPU_SCOPE_AND_SOURCE_01.tar.xz').read_bytes()
        assert sha(raw) == ARCHIVE
        target = source / PREFIX
        target.mkdir(parents=True)
        with tarfile.open(fileobj=io.BytesIO(raw), mode='r:xz') as archive:
            manifest = json.loads(archive.extractfile('MEMBERS.json').read())
            for name in ('artifact_pointer.py', 'checkpoint_replay.py', 'cpu_migration.py'):
                member = 'cpu_diagnostic_scope_review/runtime_prerequisites/' + name
                data = archive.extractfile(member).read()
                assert len(data) == manifest[member]['bytes'] and sha(data) == manifest[member]['sha256']
                (target / name).write_bytes(data)
        original = (ROOT / 'CPU_POINTER_TEST_ORIGINAL.py').read_bytes()
        assert sha(original) == 'f7675950deec542458c1eb83adfb332dee0a2f066ea53226c3a215053260b11e'
        assert hashlib.sha1(b'blob ' + str(len(original)).encode() + b'\0' + original).hexdigest() == 'dea3e1ddff931a0e7baf81a0992cd919a3b42048'
        candidate = (ROOT / 'CPU_POINTER_TEST_FIXED.py').read_bytes()
        assert sha(candidate) == CANDIDATE
        (target / 'test_artifact_pointer.py').write_bytes(candidate)
        pointer = (ROOT / 'source_publication_04' / PREFIX / 'CPU-ARTIFACT.json').read_bytes()
        assert sha(pointer) == '973d13456bc798747427df097c910510f793246c26055e4889ab7af60f283e2a'
        assert json.loads(pointer)['status'] == 'FROZEN'
        (target / 'CPU-ARTIFACT.json').write_bytes(pointer)
        identities = {p.name: {'bytes': p.stat().st_size, 'sha256': sha(p.read_bytes())} for p in target.iterdir()}
        result['sources'] = identities
        result['original_test_sha256'] = sha(original)
        result['candidate_test_sha256'] = sha(candidate)
        result['registration'] = {'parent_processes': 2, 'methods_each': 6, 'nested_pointer_children_each': 8,
                                  'parent_wall_s_each': 30, 'child_inherited_cpu_soft_hard_s': [20, 21],
                                  'source_files': len(identities), 'new_model_calls': 0}
        save()
        fmt = subprocess.run(['/opt/homebrew/bin/just', 'fmt'], cwd=source, env=env, capture_output=True, text=True, timeout=90)
        (out / 'FORMAT.stdout').write_text(fmt.stdout)
        (out / 'FORMAT.stderr').write_text(fmt.stderr)
        result['official_format_10'] = {'exit_code': fmt.returncode, 'stdout_sha256': sha(fmt.stdout.encode()),
                                        'stderr_sha256': sha(fmt.stderr.encode())}
        assert fmt.returncode == 0 and all(sha((target / name).read_bytes()) == item['sha256'] for name, item in identities.items())
        for label, flags in (('normal', []), ('optimized', ['-O'])):
            argv = [sys.executable, *flags, '-B', '-m', 'unittest', 'discover', '-s', str(target), '-p', 'test_artifact_pointer.py', '-v']
            row = {'mode': label, 'argv': argv, 'state': 'INTENT'}
            result['runs'].append(row)
            save()
            def limits():
                resource.setrlimit(resource.RLIMIT_CPU, (20, 21))
                resource.setrlimit(resource.RLIMIT_FSIZE, (131072, 131072))
            before = resource.getrusage(resource.RUSAGE_CHILDREN)
            wall = time.perf_counter()
            with (out / (label + '.stdout')).open('xb') as stdout, (out / (label + '.stderr')).open('xb') as stderr:
                child = subprocess.Popen(argv, cwd=source, env=env, stdout=stdout, stderr=stderr,
                                         start_new_session=True, preexec_fn=limits)
                try:
                    child.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait(timeout=5)
                    row['timed_out'] = True
            usage = resource.getrusage(resource.RUSAGE_CHILDREN)
            stderr = (out / (label + '.stderr')).read_text()
            match = re.search(r'Ran (\d+) tests in ([0-9.]+)s', stderr)
            row.update(state='RETURNED', exit_code=child.returncode, wall_s=time.perf_counter() - wall,
                       aggregate_child_cpu_s=usage.ru_utime + usage.ru_stime - before.ru_utime - before.ru_stime,
                       methods=int(match.group(1)) if match else None,
                       stdout_sha256=sha((out / (label + '.stdout')).read_bytes()),
                       stderr_sha256=sha(stderr.encode()))
            save()
            assert child.returncode == 0 and row['methods'] == 6 and stderr.endswith('\nOK\n')
            assert not any(word in stderr for word in ('skipped=', 'expected failures=', 'unexpected successes='))
        result['sources_unchanged'] = all(sha((target / name).read_bytes()) == item['sha256'] for name, item in identities.items())
        assert result['sources_unchanged']
        result['status'] = 'PASS_BOTH_POINTER_MODES'
    except BaseException as error:
        result.update(status='FAILED_RETAINED', error=type(error).__name__ + ': ' + str(error))
        raise
    finally:
        save()
    print(json.dumps({'status': result['status'], 'result_sha256': sha((out / 'RESULT.json').read_bytes()),
                      'methods': sum(row.get('methods') or 0 for row in result['runs']), 'model_calls': 0}), flush=True)


if __name__ == '__main__':
    main()
