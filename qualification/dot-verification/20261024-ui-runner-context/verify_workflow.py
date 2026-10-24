"""Local workflow syntax/semantic and full binding-step check; no hosted jobs."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import yaml

before = yaml.safe_load(Path(sys.argv[1]).read_text())
after = yaml.safe_load(Path(sys.argv[2]).read_text())
job = 'native-presentation'
name = 'Bind source before installing native inputs'
oldjob = before['jobs'][job]
newjob = after['jobs'][job]
idx = next(i for i, s in enumerate(newjob['steps']) if s.get('name') == name)
line = '''printf 'CARGO_TARGET_DIR=%s/native-presentation-target\\n' "${RUNNER_TEMP:?}" >> "${GITHUB_ENV:?}"\n'''
assert oldjob['env']['CARGO_TARGET_DIR'] == '${{ runner.temp }}/native-presentation-target'
assert 'CARGO_TARGET_DIR' not in newjob['env']
assert newjob['steps'][idx]['run'] == oldjob['steps'][idx]['run'].replace('set -euo pipefail\n', 'set -euo pipefail\n' + line, 1)
expected = copy.deepcopy(before)
del expected['jobs'][job]['env']['CARGO_TARGET_DIR']
expected['jobs'][job]['steps'][idx]['run'] = newjob['steps'][idx]['run']
assert expected == after, 'unrelated YAML semantic changes'
for i, step in enumerate(newjob['steps']):
    if 'CARGO_TARGET_DIR' in step.get('run', '') and i != idx:
        assert i > idx, 'consumer before initialization'
assert all('uses' not in j for j in after['jobs'].values()), 'unexpected reusable workflow'
# PyYAML YAML1.1 maps plain on to True; compare unchanged full parsed structure.
assert before[True] == after[True]
assert set(after[True]) == {'pull_request'}
run_count = 0
for j in after['jobs'].values():
    for step in j['steps']:
        if 'run' in step:
            subprocess.run(['bash', '-n'], input=step['run'], text=True, check=True)
            run_count += 1
with tempfile.TemporaryDirectory(prefix='ui workflow binding ') as td:
    root = Path(td)
    repo = root / 'fixture repo'
    repo.mkdir()
    lock = repo / 'apps/hepta-control-ui/rust/Cargo.lock'
    lock.parent.mkdir(parents=True)
    lock.write_text('# fixture lock bytes\n')
    def git(*args):
        return subprocess.check_output(['git', '-c', 'user.name=fixture', '-c', 'user.email=fixture@invalid', *args], cwd=repo, text=True).strip()
    git('init', '-q')
    git('add', '.')
    git('commit', '-qm', 'fixture')
    temp = root / 'runner temp with spaces'
    temp.mkdir()
    github_env = root / 'github env with spaces'
    env = dict(os.environ, RUNNER_TEMP=str(temp), GITHUB_ENV=str(github_env))
    subprocess.run(['bash', '-c', newjob['steps'][idx]['run']], cwd=repo, env=env, check=True)
    expected_target = str(temp / 'native-presentation-target')
    assert github_env.read_text() == f'CARGO_TARGET_DIR={expected_target}\n'
    assert not Path(expected_target).exists(), 'initializer must not change target creation behavior'
    evidence = temp / 'native-presentation-evidence'
    assert (evidence / 'tested-head.txt').read_text().strip() == git('rev-parse', 'HEAD')
    assert (evidence / 'tested-tree.txt').read_text().strip() == git('rev-parse', 'HEAD^{tree}')
    subprocess.run(['sha256sum', '-c', str(evidence / 'original-lock.sha256')], cwd=repo, check=True, stdout=subprocess.PIPE)
    # Model subsequent-step environment injection, not sourcing untrusted shell.
    key, value = github_env.read_text().rstrip('\n').split('=', 1)
    consumer_env = dict(env, **{key: value})
    observed = subprocess.check_output(['bash', '-c', 'printf "%s" "$CARGO_TARGET_DIR"'], env=consumer_env, text=True)
    assert observed == expected_target
print(json.dumps({'semantic_changes': ['remove job env CARGO_TARGET_DIR', 'add exact donor initializer to existing binding step'], 'jobs': list(after['jobs']), 'bash_scripts_checked': run_count, 'consumer_order': 'passed', 'spaced_path_complete_step': 'passed', 'head_tree_lock_evidence': 'passed', 'target_creation_unchanged': True, 'trigger': 'pull_request only', 'hosted_execution': False}, indent=2))
