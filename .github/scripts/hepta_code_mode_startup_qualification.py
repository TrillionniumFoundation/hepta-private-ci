"""Run the existing code-mode-host native owner without changing its deadlines."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import platform
import subprocess
import time
import traceback


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', required=True, type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    out = args.report_dir.resolve()
    assert not out.is_relative_to(repo), 'evidence must remain outside the checkout'
    out.mkdir(parents=True, exist_ok=False)

    def save(name, value):
        path = out / name
        data = (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()
        with path.open('wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())

    def git(*argv):
        return subprocess.check_output(['git', *argv], cwd=repo)

    def snapshot():
        result = {}
        for name in sorted(git('ls-files', '-z').decode().split('\0')):
            if not name:
                continue
            path = repo / name
            if path.is_symlink():
                data = os.fsencode(os.readlink(path))
                mode = '120000'
            else:
                assert path.is_file(), name
                data = path.read_bytes()
                mode = '100755' if path.stat().st_mode & 0o111 else '100644'
            result[name] = {'bytes': len(data), 'mode': mode, 'sha256': sha(data)}
        return result

    head = git('rev-parse', 'HEAD').decode().strip()
    assert head == os.environ['GITHUB_SHA']
    assert not git('status', '--porcelain=v1', '--untracked-files=all')
    before = snapshot()
    save('source-before.json', before)
    save('runner.json', {'head': head, 'tree': git('rev-parse', 'HEAD^{tree}').decode().strip(),
                         'platform': platform.platform(), 'machine': platform.machine(),
                         'runner_os': os.environ.get('RUNNER_OS'),
                         'run_id': os.environ['GITHUB_RUN_ID']})
    results = []

    def run(name, argv):
        started = time.monotonic()
        path = out / (name + '.log')
        with path.open('xb') as log:
            process = subprocess.run(argv, cwd=repo, stdout=log, stderr=subprocess.STDOUT)
            log.flush()
            os.fsync(log.fileno())
        record = {'name': name, 'argv': argv, 'exit': process.returncode,
                  'seconds': time.monotonic() - started,
                  'log_bytes': path.stat().st_size, 'log_sha256': sha(path.read_bytes())}
        results.append(record)
        save('commands.json', results)
        print(json.dumps(record), flush=True)
        return process.returncode

    error = None
    try:
        tests = run('original-owner', [
            './.github/scripts/run-bazel-ci.sh', '--print-failed-action-summary',
            '--print-failed-test-logs', '--', 'test',
            '--test_tag_filters=-argument-comment-lint', '--test_verbose_timeout_warnings',
            '--nocache_test_results', '--flaky_test_attempts=1',
            '--build_metadata=COMMIT_SHA=' + head,
            '--build_event_json_file=' + str(out / 'original-owner.bep.json'),
            '--', '//codex-rs/code-mode-host/...',
        ])
        query = subprocess.run([
            './.github/scripts/run-bazel-query-ci.sh', '--output=label', '--',
            'kind("rust_test rule", attr(tags, "manual", //codex-rs/code-mode-host/...))',
        ], cwd=repo, capture_output=True, check=False)
        (out / 'manual-test-query.stdout').write_bytes(query.stdout)
        (out / 'manual-test-query.stderr').write_bytes(query.stderr)
        assert query.returncode == 0, 'original manual test target discovery failed'
        manual = query.stdout.decode().splitlines()
        assert manual and all(label.startswith('//codex-rs/code-mode-host:') for label in manual)
        # Unconfigured query includes incompatible platform helpers. Match the
        # native selection in scripts/list-bazel-clippy-targets.sh.
        manual = [label for label in manual if not label.endswith('-windows-cross-bin')]
        assert manual, 'native manual test target discovery returned no owners'
        strict = run('strict', [
            './.github/scripts/run-bazel-ci.sh', '--print-failed-action-summary', '--',
            'build', '--config=clippy',
            '--@rules_rust//rust/settings:clippy_flag=--deny=warnings',
            '--build_metadata=COMMIT_SHA=' + head,
            '--build_event_json_file=' + str(out / 'strict.bep.json'),
            '--', '//codex-rs/code-mode-host/...', *manual,
        ])
        assert tests == 0 and strict == 0, 'original owner or strict Clippy failed'
    except BaseException:
        error = traceback.format_exc()
        save('failure.json', {'error': error})
    finally:
        after = snapshot()
        save('source-after.json', after)
        same = before == after and head == git('rev-parse', 'HEAD').decode().strip()
        clean = not git('status', '--porcelain=v1', '--untracked-files=all')
        save('qualification.json', {
            'passed': error is None and same and clean,
            'source_unchanged': same, 'checkout_clean': clean,
            'readiness_timeout_seconds': 10, 'test_attempts': 1,
            'scope': 'original code-mode-host owner under the repository native Bazel configuration',
            'full_platform_qualified': False, 'startup_cause_identified': False,
            'whole_codex_rewritten': False, 'commands': results,
        })
        assert same and clean, 'source identity changed during qualification'
    if error is not None:
        raise RuntimeError(error)


if __name__ == '__main__':
    main()
