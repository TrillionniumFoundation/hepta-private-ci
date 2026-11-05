import ast
import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess

import yaml

ROOT = Path('/workspace/scratch/07dd58cc9630')
BASE = ROOT / 'ci-audit/b11-helper-execution-v2-independent-20261105'
AUTHOR = ROOT / 'research-audit/b11-read-readiness-20261105/execution-candidate-v2'
CANDIDATE = AUTHOR / 'candidate'


def identity(body):
    return {'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
            'git_blob': hashlib.sha1(f'blob {len(body)}\0'.encode() + body).hexdigest()}


def pin(path):
    return {'path': str(path), **identity(path.read_bytes())}


def load(path):
    return json.loads(path.read_text())


def definitions(path):
    text = path.read_text()
    tree = ast.parse(text)
    return text, tree, {n.name: ast.get_source_segment(text, n) for n in tree.body if isinstance(n, ast.FunctionDef)}


def constants(tree):
    result = {}
    def value(n):
        if isinstance(n, ast.Name): return result[n.id]
        if isinstance(n, ast.Dict): return {value(k): value(v) for k, v in zip(n.keys, n.values)}
        if isinstance(n, (ast.Set, ast.List, ast.Tuple)):
            rows = [value(x) for x in n.elts]
            return set(rows) if isinstance(n, ast.Set) else rows
        return ast.literal_eval(n)
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            try: result[n.targets[0].id] = value(n.value)
            except (ValueError, TypeError, KeyError): pass
    return result


BASE.mkdir(exist_ok=True)
mapping = load(AUTHOR / 'combined-source-map.json')
assert len(mapping['files']) == 7
assert mapping['base_head'] == '0f6148ea3fbe9d1263354791d5cc63c7e66d4628'
files = []
for row in mapping['files']:
    for which in ('preimage', 'postimage'):
        if row[which] is None:
            assert row['local_' + which] is None
            continue
        p = Path(row['local_' + which]); got = identity(p.read_bytes())
        assert got == {k: row[which][('blob' if k == 'git_blob' else k)] for k in got}, (row['path'], which)
    files.append({'path': row['path'], 'preimage': None if row['preimage'] is None else pin(Path(row['local_preimage'])),
                  'postimage': pin(Path(row['local_postimage']))})

helper_path = CANDIDATE / '.github/scripts/run_b11_read_acl_readiness.py'
helper_text, helper_tree, helper_functions = definitions(helper_path)
cfg = constants(helper_tree)
assert identity(helper_path.read_bytes())['git_blob'] == '6010ce9cc6da2eca95aac9ba453581f68770bbe6'
assert cfg['CONTROL_BLOB'] == '3680db31233e47ba7fad99f31a7019c4536288bb'
control_path = CANDIDATE / cfg['CONTROL_SCRIPT']
v3_path = ROOT / 'architecture-audit/b11-acl-repair-20261105/counterfactual-workflow-v3/candidate/.github/scripts/run_b11_acl_identity_counterfactual.py'
assert control_path.read_bytes() == v3_path.read_bytes()
control_text, _, control_functions = definitions(control_path)
v1 = ROOT / 'research-audit/b11-read-readiness-20261105/execution-candidate-v1/candidate/.github/scripts/run_b11_read_acl_readiness.py'
assert v1.read_text().replace('25def4386ea08bb72a7605cc113117f31fffcd1b', cfg['CONTROL_BLOB']) == helper_text
assert v1.read_text().count('25def4386ea08bb72a7605cc113117f31fffcd1b') == 1

readiness = ROOT / 'research-audit/b11-read-readiness-20261105'
source_evidence = load(readiness / 'source-evidence.json')
known = {r['path']: Path(r['local_file']) for r in source_evidence['sources']}
known['.github/scripts/run-bazel-ci.sh'] = ROOT / 'architecture-audit/macos-bash-empty-array-20261105/candidate/.github/scripts/run-bazel-ci.sh'
for row in mapping['files']: known[row['path']] = Path(row['local_postimage'])
physical_pins = []
for name, blob in cfg['PINS'].items():
    assert name in known, name
    p = known[name]
    assert identity(p.read_bytes())['git_blob'] == blob, name
    physical_pins.append({'logical_source': name, **pin(p)})
assert len(physical_pins) == 11

win = CANDIDATE / 'codex-rs/windows-sandbox-rs/src/bin/setup_main/win.rs'
acl = known['codex-rs/windows-sandbox-rs/src/bin/setup_main/win_acl_tests.rs']
mutex = CANDIDATE / 'codex-rs/windows-sandbox-rs/src/bin/setup_main/win/read_acl_mutex_tests.rs'
expected = {'win::tests::' + n for n in re.findall(r'#\[test\]\s+fn (\w+)\(', win.read_text())}
expected |= {'win::acl_tests::' + n for n in re.findall(r'#\[test\]\s+fn (\w+)\(', acl.read_text())}
expected |= {'win::read_acl_mutex::tests::' + n for n in re.findall(r'#\[test\]\s+fn (\w+)\(', mutex.read_text())}
assert expected == cfg['REQUIRED_CASES'] and len(expected) == 11
for row in mapping['files'][:3]:
    original_candidate = readiness / 'candidate' / row['path']
    assert original_candidate.read_bytes() == Path(row['local_postimage']).read_bytes()

workflow = '.github/workflows/hepta-windows-token-mechanism-probe.yml'
old_wf = yaml.safe_load((AUTHOR / 'source' / workflow).read_text())
new_wf = yaml.safe_load((CANDIDATE / workflow).read_text())
old_job = old_wf['jobs']['token-mechanism-observations']
new_job = new_wf['jobs']['token-mechanism-observations']
assert old_job['timeout-minutes'] == new_job['timeout-minutes'] == 120
assert old_job['runs-on'] == new_job['runs-on'] == 'windows-latest'
old_steps = {s.get('name', s.get('uses')): s for s in old_job['steps']}
new_steps = {s.get('name', s.get('uses')): s for s in new_job['steps']}
for name, step in old_steps.items():
    now = dict(new_steps[name])
    if name == 'Check the ACL identity counterfactual and restore its source':
        assert now.pop('id') == 'acl_identity_counterfactual'
    assert now == step, name
assert len(new_steps) == len(old_steps) + 1
added = new_steps['Run the original setup helper target after exact restoration']
assert added['if'] == "always() && !cancelled() && steps.acl_identity_counterfactual.outcome == 'success'"
assert 'continue-on-error' not in new_job
assert all('continue-on-error' not in s for s in new_job['steps'])
collector = '.github/scripts/collect_bazel_failed_test_logs.py'
old_collector = (AUTHOR / 'source' / collector).read_text()
new_collector = (CANDIDATE / collector).read_text()
line = '    "' + cfg['TARGET'] + '",\n'
assert new_collector.count(line) == 1 and new_collector.replace(line, '') == old_collector
_, _, old_collector_functions = definitions(AUTHOR / 'source' / collector)
_, _, new_collector_functions = definitions(CANDIDATE / collector)
assert old_collector_functions == new_collector_functions

main = helper_functions['main']
assert 'entry["source"] == prior_entry == restored' in main
assert all(s in main for s in ['"VALID_NEGATIVE_AND_EXACT_RESTORE"', 'prior.get("physical_counterfactual_qualified") is True',
    'prior.get("restored_exact_original_bytes") is True', 'prior.get("error") is None', 'prior.get("restore_error") is None'])
argv_assignment = next(n for n in ast.walk(helper_tree) if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'argv' for t in n.targets))
argv = [e.value if isinstance(e, ast.Constant) else cfg[e.id] if isinstance(e, ast.Name) else '<dynamic GITHUB_SHA build metadata>' for e in argv_assignment.value.elts]
assert argv[-2:] == ['--', cfg['TARGET']]
assert '--nocache_test_results' in argv and '--flaky_test_attempts=1' in argv
assert not any(a.startswith(('--test_arg', '--test_filter', '--test_timeout', '--runs_per_test')) for a in argv)
assert main.index('entry["source"] == prior_entry == restored') < main.index('subprocess.run(argv')
assert 'helper_qualified=False' in main and 'final == entry' in main
assert 'return exit_code if exit_code not in (None, 0)' in main

work = BASE / 'isolated-reconstruction-v1'
work.mkdir(exist_ok=False)
for row in mapping['files']:
    if row['preimage'] is not None:
        path = work / row['path']; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(Path(row['local_preimage']).read_bytes())
commands = []
def run(args):
    result = subprocess.run(['git', '-c', 'core.autocrlf=false', *args], cwd=work, capture_output=True)
    commands.append({'argv': ['git', '-c', 'core.autocrlf=false', *args], 'cwd': str(work), 'exit_code': result.returncode,
                     'stdout': result.stdout.decode(), 'stderr': result.stderr.decode()})
    assert result.returncode == 0, commands[-1]
run(['init', '-q'])
patch = str(AUTHOR / 'combined-seven-paths.patch')
run(['apply', '--check', patch]); run(['apply', patch])
for row in mapping['files']:
    assert (work / row['path']).read_bytes() == Path(row['local_postimage']).read_bytes()
run(['apply', '--reverse', '--check', patch]); run(['apply', '--reverse', patch])
for row in mapping['files']:
    p = work / row['path']
    assert (not p.exists()) if row['preimage'] is None else p.read_bytes() == Path(row['local_preimage']).read_bytes()

report = {'schema': 'b11-helper-execution-v2-independent-verification-v1', 'observed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'status': 'STATIC_ACCEPT_NO_NATIVE_EXECUTION', 'source_files': files, 'physical_input_pins': physical_pins,
    'checks': {'combined_seven_paths_real_git_forward_and_reverse_exact': True, 'original_whole_library_step_byte_semantics_preserved': True,
        'all_existing_workflow_steps_preserved_except_counterfactual_id': True, 'workflow_120min_preserved': True,
        'collector_only_one_helper_retention_line': True, 'all_collector_functions_byte_equal': True,
        'consumer_pin_is_actual_V3_3680': True, 'consumer_only_one_pin_change_from_V1': True,
        'three_readiness_postimages_byte_equal_prior_review': True, 'required_11_helper_anchors_match_original_and_new_source_tests': True,
        'valid_counterfactual_and_exact_source_restoration_required_before_command': True,
        'unfiltered_original_helper_target_with_no_timeout_increase': True, 'explicit_no_cache_one_attempt': True,
        'helper_final_guard_error_is_not_PASS': True},
    'helper_argv_static': argv, 'required_helper_anchors': sorted(expected), 'cloud_git_commands': commands,
    'inputs': [pin(AUTHOR / n) for n in ['manifest.json', 'execution.patch', 'combined-seven-paths.patch', 'v1-to-v2-consumer-pin.delta.patch', 'combined-source-map.json', 'static-composition-verification.json']],
    'limits': ['This script parses source and performs isolated cloud Git reconstruction only; no candidate CLI, Rust, Bazel, Windows, tests, or workflow execution.',
               'The11 anchors are source expectations, not a claimed native compiled roster. Actual helper result and full named roster remain pending.',
               'Existing whole-library failures, hard-cancellation limits and B11 OPEN are preserved.']}
(BASE / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'verification': pin(BASE / 'verification.json'), 'checks': report['checks']}))
