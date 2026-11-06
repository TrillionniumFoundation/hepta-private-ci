from pathlib import Path
import ast
import base64
import collections
import difflib
import hashlib
import json
import re

ROOT=Path('/workspace/scratch/08f5efd48967')
OUT=Path(__file__).parent
E='/home/alex/work/hepta-cell-unified-20261106-a/evidence/'
P='native-source52-project-r28'
TREE='211f15baff19095e8c98bcea2b0ed99ca2270ade'
COMMIT='1e0910becc37383e6d17ecf861ea844fd07d8862'


def pin(b):
    return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}


def save(p,b):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('xb') as f:
        f.write(b)


def dump(o):
    return (json.dumps(o,indent=2,ensure_ascii=False)+'\n').encode()


x=json.loads((OUT/'transfer-payload.json').read_bytes())
raws={};provenance=[]
for f in x['files']:
    assert f['eof'] and f['path'].startswith(E)
    n=f['path'][len(E):];assert '/' not in n and n not in raws
    b=f['text'].encode();q=pin(b)
    assert len(b)==f['size'] and q['sha256']==f['sha256']
    raws[n]=b;provenance.append({'path':n,**q,'version':f['version']})
assert len(raws)==24
for item in x['large']:
    fi=item['file_info'];n=fi['path'][len(E):];assert '/' not in n and n not in raws
    parts=[];offset=0;proof=[]
    for chunk in item['chunks']:
        b=base64.b64decode(chunk['data_base64'],validate=True)
        assert chunk['path']==fi['path'] and chunk['version']==fi['version'] and chunk['size']==fi['size']
        assert chunk['offset']==offset and chunk['next_offset']==offset+len(b)
        assert hashlib.sha256(b).hexdigest()==chunk['chunk_sha256']
        offset+=len(b);parts.append(b);proof.append({'offset':chunk['offset'],'next_offset':offset,'sha256':chunk['chunk_sha256']})
    b=b''.join(parts);assert offset==len(b)==fi['size'] and pin(b)['sha256']==fi['sha256']
    raws[n]=b;provenance.append({'path':n,**pin(b),'version':fi['version'],'chunks':proof})
assert len(raws)==26
terminal_raw=x['terminal']['text'].encode();terminal=json.loads(terminal_raw)
assert terminal['job_id']==x['job_id']=='1a1b1e9bee0-fc05-7b7c'
assert terminal['state']=='succeeded' and terminal['exit_code']==0
assert all(terminal[k] is True for k in ['audit_recorded','output_complete','output_durable','terminal_publication_confirmed'])
assert not any(terminal[k] for k in ['automatic_retry','cancelled','timed_out']) and not any(terminal['log_truncated'].values())
assert len(terminal_raw)==731 and pin(terminal_raw)['sha256']=='897df3ad774667b7fab516e0d93fc3c68c43eb4c6c91e713207326feb9cd1458'
complete=json.loads(raws[P+'-complete.json'])
assert complete['schema']=='hepta.source52-project-gates-complete.v1'
assert complete['source_commit']==COMMIT and complete['source_tree']==TREE
assert complete['python_exit']==complete['strict_exit']==complete['tests_exit']==0
assert complete['python_tests']==32 and complete['python_skipped']==0
assert complete['required_old_ids']==1564 and complete['all_old_ids_observed_pass']
assert complete['source_guards_pass'] and complete['source50_lock_inherited_for_unchanged_dependency_inputs']
assert not complete['source52_bazel_lock_update_executed'] and not complete['fix_fmt_executed']
packages=['codex-cli','codex-exec-server','codex-network-proxy','codex-external-agent-migration']
assert complete['packages']==packages
commands={
    'python-runner':['python3','-m','unittest','discover','-s','scripts','-p','test_run_nextest*.py','-v'],
    'strict':['just','clippy','--locked',*[v for pkg in packages for v in ['-p',pkg]],'--','-D','warnings'],
    'tests':['just','test','--locked',*[v for pkg in packages for v in ['-p',pkg]],'--retries','0'],
}
phase_proof=[]
for phase in ['python-runner','strict','tests']:
    stem=P+'-'+phase
    receipt=json.loads(raws[stem+'-receipt.json']);raw=json.loads(raws[stem+'-raw-process-result.json'])
    assert raw['exit_code']==receipt['exit_code']==receipt['effective_exit_code']==0
    assert raw['command']==receipt['command']==commands[phase]
    assert raw['source_commit']==receipt['source_commit']==COMMIT and raw['source_tree']==receipt['source_tree']==TREE
    assert receipt['phase_pass'] and receipt['source_guards_pass'] and not receipt['issues']
    assert receipt['log_sha256']==pin(raws[stem+'.log'])['sha256']
    assert receipt['resources_sha256']==pin(raws[stem+'-resources.txt'])['sha256']
    for key in ['raw_process_result','source_postguard','acceptance_readback']:
        v=receipt[key]
        if v is not None:
            assert pin(raws[v['path']])=={k:v[k] for k in ['bytes','sha256','git_blob']}
    for suffix in ['-source-pre-verification.json','-source-post-verification.json']:
        guard=json.loads(raws[stem+suffix]);assert guard['pass'] and guard['expected_tree']==guard['actual_tree']==TREE and guard['source_commit']==COMMIT and guard['changed_file_count']==195
    phase_proof.append({'phase':phase,'raw_exit_code':0,'effective_exit_code':0,'elapsed_seconds':receipt['elapsed_seconds'],
                        'receipt':{'path':stem+'-receipt.json',**pin(raws[stem+'-receipt.json'])}})
for ptr in complete['phase_receipts']:
    assert pin(raws[ptr['path']])=={k:ptr[k] for k in ['bytes','sha256','git_blob']}
for name in [P+'-source-pre-verification.json',P+'-source-final-verification.json']:
    guard=json.loads(raws[name]);assert guard['pass'] and guard['expected_tree']==guard['actual_tree']==TREE and guard['source_commit']==COMMIT and guard['changed_file_count']==195
pylog=raws[P+'-python-runner.log']
pyids=re.findall(rb'^test_\S+ \(([^)\n]+)\) \.\.\.',pylog,re.M)
assert len(pyids)==len(set(pyids))==32 and re.search(rb'^Ran 32 tests in [0-9.]+s$',pylog,re.M) and pylog.rstrip().endswith(b'OK')
pyreview=json.loads(raws[P+'-python-runner-result-review.json'])
assert pyreview['pass'] and pyreview['reported_test_count']==32 and pyreview['reported_skipped']==0

log=raws[P+'-tests.log'];lines=[];offset=0
ansi=re.compile(rb'\x1b\[[0-?]*[ -/]*[@-~]')
for number,rawline in enumerate(log.splitlines(keepends=True),1):
    text=ansi.sub(b'',rawline).decode().rstrip('\r\n');lines.append((number,offset,text));offset+=len(rawline)
starts=[(n,o,t,re.match(r'^\s*Starting ([0-9]+) tests?\b',t)) for n,o,t in lines]
starts=[r for r in starts if r[3]]
summaries=[(n,o,t,re.match(r'^\s*Summary\s+\[\s*([0-9.]+)s\]\s+([0-9]+) tests? run:\s*(.*)$',t)) for n,o,t in lines]
summaries=[r for r in summaries if r[3]]
assert len(starts)==len(summaries)==1
start,summary=starts[0],summaries[0]
assert int(start[3][1])==int(summary[3][2])==1564
assert summary[3][3]=='1564 passed, 3 skipped'
rows=[];footer=[];row_re=re.compile(r'^\s*(PASS|FAIL|TIMEOUT)\s+\[\s*([0-9.]+)s\]\s+(\S+)\s+(.+)$')
for n,o,t in lines:
    m=row_re.match(t)
    if m:
        row={'status':m[1],'seconds':float(m[2]),'binary':m[3],'name':m[4].strip(),'line':n,'byte_offset':o}
        if start[0]<n<summary[0]:rows.append(row)
        elif n>summary[0]:footer.append(row)
actual_rows=json.loads(raws[P+'-tests-test-results.json'])
assert actual_rows==rows and len(rows)==1564 and not footer
identity={(r['binary'],r['name']):r for r in rows}
assert len(identity)==1564 and all(r['status']=='PASS' for r in rows)
baseline_path=ROOT/'native-validation-results/r26-archive-closed/original/input/source50-four-package-r23-baseline.json'
baseline_raw=baseline_path.read_bytes()
assert len(baseline_raw)==277789 and pin(baseline_raw)['sha256']=='6feba9a285f77f16fc1d34710d2737eae78a4ba3be74affd40f5703bc8ce405e'
baseline=json.loads(baseline_raw)
assert {(r['binary'],r['name']) for r in baseline['test_ids']}==set(identity)
counts=collections.Counter(r['binary'].split('::',1)[0] for r in rows)
assert dict(counts)=={'codex-cli':652,'codex-exec-server':524,'codex-network-proxy':220,'codex-external-agent-migration':168}
review=json.loads(raws[P+'-tests-result-review.json'])
assert review['pass'] and review['unique_test_count']==1564 and review['counts']=={'PASS':1564,'FAIL':0,'TIMEOUT':0}
assert review['baseline_missing']==review['baseline_not_pass']==review['additional_test_ids']==[]
assert review['reported_skipped']==3 and review['skip_identities_inferred'] is False
old_two=['runtime::tests::host_blocked_subdomain_wildcards_exclude_apex','runtime::tests::host_blocked_global_wildcard_allowlist_allows_public_hosts_except_denylist']
old_two_rows=[identity[('codex-network-proxy',name)] for name in old_two]
for name,b in raws.items():save(OUT/'evidence'/name,b)
save(OUT/'evidence'/x['terminal']['path'],terminal_raw)
for c in x['controllers']:save(OUT/'controller'/c['name'],c['text'].encode())
proof={'schema':'hepta.r28-full-native-independent-readback.v1','status':'PASS_ORIGINAL_PROJECT_GATE',
       'source_tree':TREE,'source_commit':COMMIT,'job_id':x['job_id'],'outer_exit_code':0,
       'source_changed_count':195,'all_source_guards_pass':True,'phases':phase_proof,'python_unique_test_count':32,'python_reported_skipped':0,
       'starting':{'line':start[0],'byte_offset':start[1],'text':start[2]},'summary':{'line':summary[0],'byte_offset':summary[1],'text':summary[2]},
       'unique_test_count':1564,'counts':{'PASS':1564,'FAIL':0,'TIMEOUT':0},'per_package_pass':dict(counts),'reported_skipped':3,
       'footer_duplicates_excluded':footer,'baseline_exact_set_equal':True,'baseline_used_as_filter':False,'baseline':pin(baseline_raw),
       'prior_r26_two_failures_now_exact_pass_rows':old_two_rows,'native_parsed_rows_byte_content_verified_against_raw_log':True,
       'originals':provenance,'terminal':{'path':x['terminal']['path'],**pin(terminal_raw)},'fix_fmt_executed':False,'workspace_qualification':'PENDING_SEPARATE_GATE'}
proof_raw=dump(proof);save(OUT/'LOCAL-READBACK.json',proof_raw)

B=ROOT/'native-validation-results/r29-bound-input';B.mkdir(exist_ok=False)
template=(ROOT/'source52-workspace-gates-preparation/native-run-r29-template.py').read_bytes()
assert len(template)==78396 and pin(template)['sha256']=='4b2d2f5a4f3eb33dfa7f3d744f0d2d322e2e1c1697dfbed45d0047f49dd455b9'
bindings=json.loads((ROOT/'native-validation-results/r28-bound-input/ACTUAL-BINDINGS.json').read_bytes())
bindings.update({'SOURCE_MANIFEST_BYTES':55209,
 'R28_INPUT_PINS':{name:{'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()} for name,b in sorted(raws.items())},
 'R28_JOB_ID':x['job_id'],'R28_TERMINAL_NAME':x['terminal']['path'],
 'R28_TERMINAL_SHA256':pin(terminal_raw)['sha256'],'R28_TERMINAL_BYTES':len(terminal_raw)})
text=template.decode();nodes={n.targets[0].id:n for n in ast.parse(text).body if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name)}
none={k for k,n in nodes.items() if isinstance(n.value,ast.Constant) and n.value.value is None}
assert none==set(bindings) and len(bindings)==21
bound=text
for k,v in bindings.items():
    old=k+' = None';assert bound.count(old)==1
    bound=bound.replace(old,k+' = '+repr(v),1)
bn={n.targets[0].id:n for n in ast.parse(bound).body if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name)}
assert {k:ast.literal_eval(bn[k].value) for k in bindings}==bindings
assert ast.literal_eval(bn['FROZEN'].value) is False
reverse=bound
for k in reversed(list(bindings)):
    before=ast.get_source_segment(bound,bn[k]);assert reverse.count(before)==1
    reverse=reverse.replace(before,k+' = None',1)
assert reverse.encode()==template
assert bound.count('FROZEN = False')==1
final=bound.replace('FROZEN = False','FROZEN = True',1);ast.parse(final)
diff=''.join(difflib.unified_diff(text.splitlines(True),bound.splitlines(True),fromfile='reviewed-r29-template.py',tofile='bound-r29.py')).encode()
freeze_diff=''.join(difflib.unified_diff(bound.splitlines(True),final.splitlines(True),fromfile='bound-r29.py',tofile='final-r29.py')).encode()
save(B/'native-run-r29-bound.py',bound.encode());save(B/'native-run-r29.py',final.encode())
save(B/'ACTUAL-BINDINGS.json',dump(bindings));save(B/'template-to-bound.patch',diff);save(B/'bound-to-final.patch',freeze_diff)
bound_review={'schema':'hepta.source52-r29-native-bound-review.v1','status':'STATIC_CLEAR_BOUND_INPUTS_NATURALLY_PASSED',
 'template':pin(template),'bound':pin(bound.encode()),'final':pin(final.encode()),'bindings':bindings,
 'actual_r28_full_readback':{'path':str(OUT/'LOCAL-READBACK.json'),**pin(proof_raw)},
 'actual21_literal_replacements':True,'whole_file_inverse_matches_reviewed_template':True,'final_only_frozen_flip':True,
 'ast_parse_pass':True,'no_r29_execution':True,'no_fix_fmt_execution':True}
br=dump(bound_review);save(B/'BOUND-INDEPENDENT-READBACK.json',br)
print(json.dumps({'r28_readback':pin(proof_raw),'r29_bound':pin(bound.encode()),'r29_final':pin(final.encode()),'bound_review':pin(br),'package_pass':dict(counts),'terminal':pin(terminal_raw)}))
