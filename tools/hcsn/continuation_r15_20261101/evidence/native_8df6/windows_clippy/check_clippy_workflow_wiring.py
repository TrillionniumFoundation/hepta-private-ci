"""Execute the real workflow Bash with explicit query/wrapper test doubles.

Only command wiring is exercised here. The separate real-Bazel probe checks
platform compatibility and action-failure semantics; this is not a Rust run.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

import yaml


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(original, candidate, excluded, output):
    if output.exists():
        raise FileExistsError(output)
    versions = {name: yaml.safe_load(path.read_text()) for name, path in (
        ('original', original), ('candidate', candidate))}
    scripts = {name: next(step['run'] for step in document['jobs']['clippy']['steps']
                         if step.get('name') == 'bazel build --config=clippy lint targets')
               for name, document in versions.items()}
    # The two package patterns and two compatible helper examples are synthetic.
    # The 157 incompatible labels are taken verbatim from this exact-head log.
    targets = ['//codex-rs/...', '-//codex-rs/v8-poc:all',
               '//codex-rs/fixture:fixture-unit-tests-bin',
               '//codex-rs/fixture:fixture-native-test-bin']+json.loads(excluded.read_text())
    observations = []
    with tempfile.TemporaryDirectory(prefix='hcsn-clippy-wiring-') as directory:
        root = Path(directory)
        (root/'scripts').mkdir(); (root/'.github/scripts').mkdir(parents=True)
        (root/'targets.txt').write_text('\n'.join(targets)+'\n')
        (root/'scripts/list-bazel-clippy-targets.sh').write_text('#!/usr/bin/env bash\nset -euo pipefail\ncat targets.txt\n')
        (root/'.github/scripts/run-bazel-ci.sh').write_text('''#!/usr/bin/env bash
set -euo pipefail
python3 - "$@" <<'PY'
import json, os, sys
from pathlib import Path
Path(os.environ['PROBE_ARGUMENT_LOG']).write_text(json.dumps(sys.argv[1:]))
raise SystemExit(int(os.environ.get('PROBE_EXIT_CODE', '0')))
PY
''')
        for path in (root/'scripts/list-bazel-clippy-targets.sh', root/'.github/scripts/run-bazel-ci.sh'):
            path.chmod(0o755)
        for platform in ('Linux', 'macOS', 'Windows'):
            observed = {}
            for version, script in scripts.items():
                log = root/f'{platform}-{version}.json'
                env = {**os.environ, 'RUNNER_OS': platform, 'GITHUB_SHA': 'synthetic-command-capture',
                       'PROBE_ARGUMENT_LOG': str(log), 'PROBE_EXIT_CODE': '0'}
                result = subprocess.run(['/bin/bash', '-e', '-o', 'pipefail', '-c', script],
                                        cwd=root, env=env, capture_output=True, text=True)
                assert result.returncode == 0, result.stderr
                args = json.loads(log.read_text())
                separators = [i for i, value in enumerate(args) if value == '--']
                assert len(separators) == 2 and args[separators[1]+1:] == targets
                observed[version] = args
                observations.append({'platform': platform, 'version': version, 'exit_code': result.returncode,
                    'arguments': args, 'targets_unchanged': True})
            flag = '--skip_incompatible_explicit_targets'
            if platform == 'Windows':
                assert flag not in observed['original'] and observed['candidate'].count(flag) == 1
                assert [a for a in observed['candidate'] if a != flag] == observed['original']
                assert '--platforms=//:windows_x86_64_msvc' in observed['candidate']
                assert '--windows-msvc-host-platform' in observed['candidate']
            else:
                assert observed['candidate'] == observed['original'] and flag not in observed['candidate']
        log = root/'failure.json'
        env = {**os.environ, 'RUNNER_OS': 'Windows', 'GITHUB_SHA': 'synthetic-command-capture',
               'PROBE_ARGUMENT_LOG': str(log), 'PROBE_EXIT_CODE': '37'}
        failure = subprocess.run(['/bin/bash', '-e', '-o', 'pipefail', '-c', scripts['candidate']],
                                 cwd=root, env=env, capture_output=True, text=True)
        assert failure.returncode == 37
    receipt = {'schema': 'hcsn.windows-clippy-workflow-wiring.v1', 'passed': True,
        'script_sha256': sha(__file__), 'original_sha256': sha(original), 'candidate_sha256': sha(candidate),
        'real_failed_target_roster_sha256': sha(excluded), 'explicit_roster_count': len(targets),
        'cases': observations, 'propagated_wrapper_failure_exit_code': failure.returncode,
        'source_scope': 'Actual original/candidate workflow Bash; query and wrapper replaced only inside an isolated command-capture fixture. All 157 observed incompatible labels plus four explicit fixture labels preserved. No native Rust execution.'}
    with output.open('x') as f:
        json.dump(receipt, f, indent=2); f.write('\n')
    print(json.dumps({'passed': True, 'platforms': 3, 'captured_commands': len(observations),
        'targets_per_command': len(targets), 'failure_exit_code': failure.returncode, 'output': str(output)}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('original', 'candidate', 'excluded', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    main(args.original, args.candidate, args.excluded, args.output)
