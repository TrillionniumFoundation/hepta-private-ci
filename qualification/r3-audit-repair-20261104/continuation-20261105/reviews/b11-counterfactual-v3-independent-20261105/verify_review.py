import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path('/workspace/scratch/07dd58cc9630')
OUT = ROOT / 'ci-audit/acl-counterfactual-wrapper-v3-review-20261105'
AUTHOR = ROOT / 'architecture-audit/b11-acl-repair-20261105/counterfactual-workflow-v3'

def identity(body):
    return {'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
            'git_blob': hashlib.sha1(f'blob {len(body)}\0'.encode() + body).hexdigest()}

def pin(path):
    return {'path': str(path), **identity(path.read_bytes())}

def load(path):
    return json.loads(path.read_text())

def functions(source):
    lines = source.splitlines(keepends=True)
    return {node.name: ''.join(lines[node.lineno - 1:node.end_lineno])
            for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)}

manifest_path = AUTHOR / 'manifest-DISABLED.json'
manifest = load(manifest_path)
path = manifest['paths'][0]
pre = Path(path['preimage']['path'])
post = Path(path['postimage']['path'])
patch = Path(manifest['patch']['path'])
workflow = Path(manifest['unchanged_workflow']['path'])
for key, file in [(path['preimage'], pre), (path['postimage'], post), (manifest['patch'], patch), (manifest['unchanged_workflow'], workflow)]:
    actual = identity(file.read_bytes())
    assert all(actual[k] == key[k] for k in actual), (file, actual, key)
old = pre.read_text()
new = post.read_text()
old_functions, new_functions = functions(old), functions(new)
assert old_functions.keys() == new_functions.keys()
unchanged = []
for name in old_functions:
    if name != 'main':
        assert old_functions[name] == new_functions[name], name
        unchanged.append(name)
tail = '        original_bytes = source.read_bytes()\n'
assert old[old.index(tail):] == new[new.index(tail):]
prefix = '        for required in [CASE,'
new_prefix = '        required_cases = [CASE,'
assert old[:old.index(prefix)] == new[:new.index(new_prefix)]
assert workflow.read_bytes() == (ROOT / 'architecture-audit/b11-acl-repair-20261105/counterfactual-workflow-v2/candidate/.github/workflows/hepta-windows-token-mechanism-probe.yml').read_bytes()
assert 'timeout-minutes: 120' in workflow.read_text()
assert manifest['change_counts'] == {'paths': 1, 'added': 60, 'removed': 7}
required = manifest['required_original_cases']
assert len(required) == 4 and len(set(required)) == 4
assert new.count('positive_result = subprocess.run(') == 1
assert 'for number, required in enumerate(required_cases, 1):' in new
assert '"--nocache_test_results", "--flaky_test_attempts=1", f"--test_arg={required}", "--test_arg=--exact"' in new
assert 'ok\\. 1 passed; 0 failed; 0 ignored; 0 measured; 155 filtered out;' in new
assert 'positive_after == positive_before' in new
assert 'positive_before == entry' in new
assert new.index('report["positive_scopes"].append(qualified)') < new.index(tail)

prior = load(AUTHOR / 'static-verification.json')
raw_pin = prior['native7_full_log']
raw_path = Path(raw_pin['path'])
raw = raw_path.read_bytes()
xml_path = Path(prior['native7_full_XML']['path'])
xml = xml_path.read_bytes()
terminal_path = Path(prior['native7_original_terminal']['path'])
terminal = load(terminal_path)
collector_path = Path(prior['native7_retained_manifest']['path'])
collector = load(collector_path)
for item in [raw_pin, prior['native7_full_XML'], prior['native7_original_terminal'], prior['native7_retained_manifest']]:
    assert all(identity(Path(item['path']).read_bytes())[k] == item[k] for k in ['bytes','sha256','git_blob'])
assert terminal['status'] == 'INVALID_OR_NOT_RUN' and terminal['source_mutated'] is False
assert terminal['source_mutation_attempted'] is False
assert terminal['physical_counterfactual_qualified'] is False
clean = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', raw.decode()).replace('\r', '')
counts = {name: len(re.findall(r'^test ' + re.escape(name) + r' \.\.\. ok$', clean, re.MULTILINE)) for name in required}
assert list(counts.values()) == [1,1,1,0]
failure_headers = re.findall(r'^---- (.+) stdout ----$', clean, re.MULTILINE)
assert len(failure_headers) == 7 and not set(required).intersection(failure_headers)
actual_summaries = re.findall(r'^test result: (ok|FAILED)\. ([0-9]+) passed; ([0-9]+) failed; ([0-9]+) ignored; 0 measured; ([0-9]+) filtered out; finished in ([0-9.]+)s$', clean, re.MULTILINE)
assert actual_summaries == [('ok','92','0','0','64','1.04'),('FAILED','55','7','2','92','0.21')]
assert tuple(sum(int(row[k]) for row in actual_summaries) for k in (1,2,3)) == (147,7,2)
split_lines = [{'line': i+1, 'text': s} for i,s in enumerate(clean.splitlines()) if required[3] in s]
assert len(split_lines) == 1 and 'insideok' in split_lines[0]['text']
assert collector['source'] == {'commit':'b5c23d8943a0a36a14a962175cb2ec75d22d5553', 'tree':'29316e75554590382268dafa77869fab0394a264', 'tracked_worktree_dirty':False}
for suffix, body in [('.log',raw),('.xml',xml)]:
    found = [x for x in collector['files'] if x['target'] == '//codex-rs/windows-sandbox-rs:windows-sandbox-rs-unit-tests' and x['testlogs_relative_path'].endswith('/test'+suffix)]
    assert len(found) == 1 and len(body) == found[0]['bytes'] and identity(body)['sha256'] == found[0]['sha256']
xml_cases = ET.fromstring(xml).findall('.//testcase')
assert len(xml_cases) == 1 and len(xml_cases[0].findall('error')) == 1

old_failure_path = Path(prior['actual_prior_required_case_failure_header_rejected_before_additional_scopes']['source']['path'])
old_failure = old_failure_path.read_bytes()
assert identity(old_failure) == {k: prior['actual_prior_required_case_failure_header_rejected_before_additional_scopes']['source'][k] for k in ['bytes','sha256','git_blob']}
assert f'---- {required[1]} stdout ----' in old_failure.decode()

commands=[]
working=Path(tempfile.mkdtemp(prefix='private-roundtrip-',dir=OUT))
relative=path['repository_path']
target=working/relative
target.parent.mkdir(parents=True)
target.write_bytes(pre.read_bytes())
for args in [['git','init','--quiet'],['git','add','--',relative],['git','apply','--check',str(patch)],['git','apply',str(patch)]]:
    result=subprocess.run(args,cwd=working,capture_output=True,check=False)
    commands.append({'argv':args,'exit_code':result.returncode,'stdout':result.stdout.decode(),'stderr':result.stderr.decode()})
    assert result.returncode==0
assert target.read_bytes()==post.read_bytes()
for args in [['git','apply','--reverse','--check',str(patch)],['git','apply','--reverse',str(patch)]]:
    result=subprocess.run(args,cwd=working,capture_output=True,check=False)
    commands.append({'argv':args,'exit_code':result.returncode,'stdout':result.stdout.decode(),'stderr':result.stderr.decode()})
    assert result.returncode==0
assert target.read_bytes()==pre.read_bytes()

report={
    'schema':'b11-counterfactual-v3-independent-static-verification-v1',
    'manifest':pin(manifest_path),'preimage':pin(pre),'postimage':pin(post),'patch':pin(patch),'unchanged_workflow':pin(workflow),
    'old_non_main_functions_byte_equal':unchanged,
    'initial_whole_source_console_prefix_byte_equal':True,
    'entire_negative_exception_finally_terminal_tail_byte_equal':True,
    'whole_workflow_byte_equal':True,'original_120_minute_job_budget_unchanged':True,
    'native7_inputs':[pin(raw_path),pin(xml_path),pin(terminal_path),pin(collector_path)],
    'native7_old_exact_line_counts':counts,'native7_original_failure_headers':failure_headers,
    'native7_interleaved_line_preserved':split_lines,
    'native7_original_scope':{'passed':147,'failed':7,'ignored':2,'source_mutated':False,'counterfactual_status':terminal['status'],'actual_original_libtest_subinvocations':actual_summaries},
    'reviewer_correction':{'initial_parser':pin(OUT/'reviewer-initial-parser.py.source.txt'),'reason':'Reviewer first assumed one aggregate 147/7/2 libtest summary. Original default batch wrapper actually emitted 92/0/0 plus 55/7/2, with 64/92 filtered. Revised parser verifies the two actual original summaries and sums them. Candidate and all native originals are unchanged.'},
    'prior_actual_required_case_failure':{'input':pin(old_failure_path),'case':required[1],'original_failure_header_present':True},
    'private_cloud_git_roundtrip':commands,'forward_and_reverse_bytes_exact':True,
    'actions':{'native_commands':0,'rust_tests':0,'new_positive_execution':0,'negative_execution':0,'ref_mutations':0},
    'limits':['The new four positive scopes and negative remain unexecuted. No interleaved PASS record was repaired or accepted.',
              'The XML is the outer Bazel testcase, not four per-Rust-case XMLs. Exact name attribution follows the fixed full-name --exact command and strict one-case libtest summary.',
              'This review does not qualify the independent setup helper target or close original B11 failures.']}
output=OUT/'verification.json'
output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(pin(output)))
