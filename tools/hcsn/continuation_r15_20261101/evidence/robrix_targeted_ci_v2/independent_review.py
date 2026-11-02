"""Read-only independent review of the four-platform Robrix workflow delta."""
from pathlib import Path
import copy
import gzip
import hashlib
import json
import yaml

BASE = Path('/tmp/hcsn-robrix-targeted-ci')
NEXT = Path('/tmp/hcsn-robrix-targeted-ci-v2')
REL = '.github/workflows/hcsn-robrix-fixture-r16.yml'
TARGET = '//codex-rs/hepta-supervisor:hepta-supervisor-robrix_control_projection-test'
def ident(path):
    b = path.read_bytes()
    return {'path': str(path), 'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()}
old_path, new_path = BASE/'candidate'/REL, NEXT/'candidate'/REL
old_raw, new_raw = old_path.read_text(), new_path.read_text()
assert ident(old_path)['sha256'] == 'f03ad806a2789a72b33af94d29ba89f3c67745713c883150db3ce46f28357491'
assert ident(new_path)['sha256'] == '08e885ff1c0f475d5b80a0c267fddcbf6d2ffb527d1c5c8c9dffc9c43ade1091'
addition = '          - os: macos-15\n            target: aarch64-apple-darwin\n          - os: macos-15-intel\n            target: x86_64-apple-darwin\n'
anchor = '            target: x86_64-pc-windows-msvc\n'
assert old_raw.count(anchor) == 1
assert new_raw == old_raw.replace(anchor, anchor+addition)
old, new = yaml.load(old_raw, Loader=yaml.BaseLoader), yaml.load(new_raw, Loader=yaml.BaseLoader)
matrix = new['jobs']['robrix']['strategy']['matrix']['include']
expected = [{'os':'ubuntu-24.04','target':'x86_64-unknown-linux-gnu'},
            {'os':'windows-latest','target':'x86_64-pc-windows-msvc'},
            {'os':'macos-15','target':'aarch64-apple-darwin'},
            {'os':'macos-15-intel','target':'x86_64-apple-darwin'}]
assert matrix == expected
without = copy.deepcopy(new)
without['jobs']['robrix']['strategy']['matrix']['include'] = old['jobs']['robrix']['strategy']['matrix']['include']
assert without == old
assert new['permissions'] == {'contents':'read'}
job = new['jobs']['robrix']
assert job['strategy']['fail-fast'] == 'false'
test = next(x for x in job['steps'] if x['name']=='Run the complete Robrix fixture target')
assert 'continue-on-error' not in test and 'if' not in test
assert test['run'].count(TARGET)==1 and '--nocache_test_results' in test['run']
assert not any(s in test['run'] for s in ['--test_filter','--test_tag_filters','--runs_per_test','--flaky_test_attempts','--skip_incompatible_explicit_targets'])
assert [x['name'] for x in job['steps'] if x.get('continue-on-error')=='true'] == ['Upload Bazel execution logs']
wrapper = BASE/'original/.github/scripts/run-bazel-ci.sh'
wrapper_text = wrapper.read_text()
assert 'macOS)\n    ci_config=ci-macos' in wrapper_text
assert 'bazel_status=${PIPESTATUS[0]}' in wrapper_text and 'exit "$bazel_status"' in wrapper_text
wiring_path = NEXT/'WIRING_EXECUTION_V2.json'
wiring = json.loads(wiring_path.read_text())
assert wiring['workflow']['sha256']==ident(new_path)['sha256']
assert wiring['shell_wrapper']['sha256']==ident(wrapper)['sha256']
assert wiring['native_execution_count']==0 and len(wiring['workflow_matrix_runs'])==8
seen = set()
rows=[]
for record in wiring['workflow_matrix_runs']:
    key=(record['matrix_os'],record['matrix_target'],record['synthetic_lower_exit'])
    assert key not in seen
    seen.add(key)
    assert record['execution']['command']==['bash','-c',test['run']]
    assert record['execution']['exit_code']==record['synthetic_lower_exit']
    args=record['lower_executor_calls'][0]
    assert args[-2:]==['--',TARGET] and '--nocache_test_results' in args
    if record['runner_os']=='macOS':
        assert '--config=ci-macos' in args and '--config=ci-windows' not in args
        assert not any(x.startswith('--platforms=') for x in args)
    rows.append({'runner':record['matrix_os'],'target_triple':record['matrix_target'],
                 'injected_lower_exit':record['synthetic_lower_exit'],'observed_wrapper_exit':record['execution']['exit_code']})
assert seen=={(x['os'],x['target'],n) for x in expected for n in [0,37]}
assert [x['execution']['exit_code'] for x in wiring['source_preflight_runs']]==[0,1]
lint_path=NEXT/'FORMAT_AND_LINT_V2.json'
lint=json.loads(lint_path.read_text())
assert lint['workflow_sha256']==ident(new_path)['sha256']
assert len(lint['executions'])==3 and all(x['exit_code']==0 for x in lint['executions'])
patch=NEXT/'ROBRIX_TARGETED_CI_V2.patch'
assert ident(patch)['sha256']=='04c6823f115694c6425674540e092a2d7a5ac73d9ed88f6a021943407ed7ca98'
logs=[]
for job_id, expected_gzip in [(125028471674,'ecfff357144bc74146b8c7b027ade09d241f527aca7e39a435712ecf05e2e9f8'),
                             (125028471783,'22ceff1fbb7f8882989632a809f21bb26f6c6fcf7b293aa75b3307eda22f6a59')]:
    p=Path('/tmp/hcsn-f52-native-status')/f'JOB_{job_id}.log.gz'
    assert ident(p)['sha256']==expected_gzip
    raw=gzip.decompress(p.read_bytes());lines=raw.decode().splitlines()
    hits=[i+1 for i,line in enumerate(lines) if 'Error: Bazel launcher did not set INSTA_WORKSPACE_ROOT' in line]
    assert len(hits)==2
    logs.append({'job':job_id,'gzip_sha256':expected_gzip,'raw_sha256':hashlib.sha256(raw).hexdigest(),'error_lines_1based':hits})
receipt={'schema':'robrix-ci-v2-independent-review-v1','blocking_findings':[],
    'scope':'Read-only source, record and identity review; no new wrapper/Bazel/Rust/financial execution by reviewer',
    'inputs':[ident(x) for x in [old_path,new_path,patch,wrapper,wiring_path,lint_path]],
    'verified_change':'Exactly four matrix lines appended; all other raw bytes and parsed workflow fields unchanged',
    'matrix':matrix,'actual_author_wiring_records_reviewed':rows,
    'source_head_positive_negative_exit_codes':[0,1],'observed_f52_mac_error_evidence':logs,
    'preserved':['one complete original Robrix target','read-only permissions','pinned actions and exact source checkout',
                 'shared prepare action and unchanged shell wrapper','native macOS ci-macos configuration',
                 'failure propagation through PIPESTATUS[0]','no test filter, retry or incompatible-target skip',
                 'failure remains fatal; only artifact upload is nonfatal','existing broad workflows unchanged'],
    'validation_limit':'Eight author-run wiring controls execute actual shell code on Linux with an explicitly synthetic lower Python executor. They do not execute native macOS, Windows, or the actual Robrix target.',
    'acceptance_remaining':'All four exact-new-head hosted platform jobs must execute and pass the original target and clean-worktree check.'}
out=Path('/tmp/hcsn-robrix-ci-v2-independent-review.json')
out.write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps({'review':ident(out),'blocking_findings':0,'new_native_or_financial_executions':0}))
