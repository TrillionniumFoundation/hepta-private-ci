from pathlib import Path
import hashlib
import json
import re
import zipfile
from datetime import datetime, timezone

ROOT = Path('/workspace/scratch/07dd58cc9630')
BASE = ROOT / 'research-audit/published-5b633-ci-20261105'
REVIEW = BASE / 'b13-closure-review'
HEAD = '5b6331250ff459033bd44d1a95daec70131277cc'
MERGE = '9063c52a063b6f26c48e9418f6d8dbd14e9e06ff'
TREE = 'b26598d0d97d8d51e723bb5582137315f2174d35'

def ident(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'computed_git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def file_id(p):
    return {'local_file': str(p), **ident(p.read_bytes())}

def read(p):
    return json.loads(p.read_text())

review = read(REVIEW / 'closure-review.json')
plan_path = ROOT / 'research-audit/workflow-reference-review/verified-registry-originals/fourth-seven-rows-missing-evidence.json.txt'
frozen = read(plan_path)['case_index']['B13']
names = [r['test'] for r in frozen]
assert len(names) == len(set(names)) == 9
assert names[0] == 'runtime::tests::qualification_prepare_quarantines_expired_registry_attempt_with_h7_evidence'
ledger = read(ROOT / 'hepta-audit-fifth/v6-deliverables/continuation-blocker-progress-v4.json')
original_exit = next(r for r in ledger['items'] if r['id'] == 'B13')['original_exit_condition_zh']
assert original_exit == review['original_exit_condition_zh']
history = read(REVIEW / 'historical-second-batch-qualification.original.json.txt')
original48 = [r for r in history['original_failure_snapshot']['entries'] if r['test'] in names]
assert len(original48) == 1 and original48[0]['original_platforms'] == ['windows-shard3']
assert original48[0]['test'] == 'completion_panic_retains_exact_authority_in_settlement_guardian'

leaves_doc = read(ROOT / 'hepta-audit-fifth/inputs/product-5b-full-leaf-manifest.json')
assert (leaves_doc['commit'], leaves_doc['tree'], leaves_doc['truncated']) == (HEAD, TREE, False)
leaves = {x['path']: x for x in leaves_doc['leaves']}
sources = []
source_text = {}
for r in review['source']['fixed_sources']:
    p = Path(r['local_file'])
    raw = p.read_bytes()
    actual = ident(raw)
    logical = r['archived_logical_source_path']
    assert actual['bytes'] == r['bytes'] == leaves[logical]['size']
    assert actual['sha256'] == r['sha256']
    assert actual['computed_git_blob'] == r['git_blob'] == leaves[logical]['sha']
    sources.append({'repository_path': logical, **file_id(p)})
    source_text[logical] = raw.decode()
assert len(sources) == 7
assert [r['name'] for r in review['case_index']] == names
for r in review['case_index']:
    text = source_text[r['source_path']]
    assert text.count(r['body_excerpt']) == 1
    assert text[:text.index(r['body_excerpt'])].count('\n') + 1 == r['source_line_start']
    assert r['current_windows_result'] == 'ok'

api_path = ROOT / 'hepta-audit-fifth/inputs/b13-artifact-list-api-bindings-v1.json'
api_original = read(api_path)
artifacts = {}
for r in api_original['supported_purpose_built_run_lists']:
    for a in r['result']['structuredContent']['artifacts']:
        artifacts[a['id']] = a

archives = []
queue_rows = []
for role, job_id, artifact_id in [('source',127149583164,13415207261),('merge',127149583430,13415148242)]:
    directory = BASE / f'terminal/windows-gitqueue-{role}-{job_id}'
    zpath = directory / f'artifact-{artifact_id}.zip'
    m = read(directory / f'artifact-{artifact_id}-verification.json')
    b = zpath.read_bytes()
    a = artifacts[artifact_id]
    archive_claim = m['zip'] if role == 'source' else m['archive']
    assert len(b) == a['size_in_bytes'] == archive_claim['bytes']
    assert hashlib.sha256(b).hexdigest() == a['digest'].removeprefix('sha256:') == archive_claim['sha256']
    assert a['workflow_run']['head_sha'] == HEAD and a['workflow_run']['id'] == 41999114838
    with zipfile.ZipFile(zpath) as z:
        assert z.testzip() is None
        assert len(z.namelist()) == len(set(z.namelist())) == len(m['members'])
        assert set(z.namelist()) == {r['name'] for r in m['members']}
        for r in m['members']:
            raw = z.read(r['name'])
            q = ident(raw)
            assert q['bytes'] == r['bytes'] and q['sha256'] == r['sha256']
            assert q['computed_git_blob'] == r['computed_git_blob']
            assert z.getinfo(r['name']).CRC == r['crc32' if role == 'source' else 'crc']
        src = json.loads(z.read('bazel-process-evidence/source.json'))
        retained = json.loads(z.read('bazel-process-evidence/retained.json'))
        expected_head = HEAD if role == 'source' else MERGE
        assert src['head'] == expected_head and src['tree'] == TREE
        assert src['platform'].startswith('Windows-') and src['run_id'] == '41999114838'
        assert src['diagnostic_only'] is False and src['pre_test_powershell_probe'] is False
        assert '13afd7f2c536c5622fc7f8cc3fe68c0cc1a59cc1\tcodex-rs/ext/queue/tests/queue_service.rs' in src['input_git_objects']
        raw_log = z.read('bazel-process-evidence/queue-queue_service-test-test.log')
        log = raw_log.decode()
        rows = []
        for i,line in enumerate(log.splitlines(),1):
            match = re.fullmatch(r'test (.+) \.\.\. (ok|FAILED|ignored)',line)
            if match: rows.append({'name':match[1],'result':match[2],'line_1based':i,'physical_line':line})
        assert len(rows) == len({r['name'] for r in rows}) == 36
        assert all(r['result'] == 'ok' for r in rows)
        selected = [r for r in rows if r['name'] in names[1:]]
        assert len(selected) == 8 and {r['name'] for r in selected} == set(names[1:])
        assert '36 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out' in log
        queue_rows.append({'role':role,'job_id':job_id,'artifact_id':artifact_id,'source_original':src,
                           'retained_original':retained,'log_identity':ident(raw_log),'required_rows':selected,
                           'whole_target':{'passed':36,'failed':0,'ignored':0}})
        archives.append({'artifact_id':artifact_id,**file_id(zpath),'members':len(z.namelist()),'crc_and_all_member_hashes_equal':True,
                         'fresh_api_digest_and_source_binding_equal':True})

agent = review['agentd_actual']
zpath = Path(agent['archive']['local_file'])
b = zpath.read_bytes()
a = artifacts[13431285250]
assert len(b) == a['size_in_bytes'] == 4967167
assert hashlib.sha256(b).hexdigest() == a['digest'].removeprefix('sha256:') == 'd0dd2347f5be91ae1f445d21e892ea5d4559499dc8e2f71554ce0ce2bb93ba85'
assert a['workflow_run']['head_sha'] == HEAD and a['workflow_run']['id'] == 41999114842
members = read(REVIEW / 'agentd-archive-members.json')
target = '//codex-rs/hepta-agentd:hepta-agentd-cognitive-write-qualification-test'
prefix = 'selected-target-test-logs/invocation-pj7csqys/'
with zipfile.ZipFile(zpath) as z:
    assert z.testzip() is None
    assert len(z.namelist()) == len(set(z.namelist())) == len(members) == 54
    assert set(z.namelist()) == {r['member'] for r in members}
    for r in members:
        raw = z.read(r['member'])
        q = ident(raw)
        assert q['bytes'] == r['bytes'] and q['sha256'] == r['sha256']
        assert q['computed_git_blob'] == r['git_blob']
        assert f"{z.getinfo(r['member']).CRC:08x}" == r['zip_crc32']
    collector = json.loads(z.read(prefix+'manifest.json'))
    assert collector['source'] == {'commit':MERGE,'tree':TREE,'tracked_worktree_dirty':False}
    assert collector['complete_for_selected_targets'] and not collector['errors']
    retention = collector['retention']['targets'][target]
    assert retention['status'] == 'PASSED' and not retention['cached_marker']
    assert retention['summary_lines'] == [target+'  PASSED in 31.0s']
    files = [r for r in collector['files'] if r['target'] == target]
    assert len(files) == 2
    for r in files:
        raw = z.read(prefix+r['archive_relative_path'])
        assert len(raw) == r['bytes'] and hashlib.sha256(raw).hexdigest() == r['sha256']
    raw_log = z.read(prefix+'targets/0003/test.log')
    log = raw_log.decode()
    agent_rows = []
    for i,line in enumerate(log.splitlines(),1):
        match = re.fullmatch(r'test (.+) \.\.\. (ok|FAILED|ignored)',line)
        if match: agent_rows.append({'name':match[1],'result':match[2],'line_1based':i,'physical_line':line})
    assert len(agent_rows) == 3 and all(r['result'] == 'ok' for r in agent_rows)
    assert len([r for r in agent_rows if r['name'] == names[0]]) == 1
    assert '3 passed; 0 failed; 0 ignored; 0 measured; 172 filtered out; finished in 30.56s' in log
    archives.append({'artifact_id':13431285250,**file_id(zpath),'members':54,'crc_and_all_member_hashes_equal':True,
                     'fresh_api_digest_and_source_binding_equal':True})

job_path = BASE / 'terminal/main-win-shard2-127339255880/job.log'
job_lines = job_path.read_text().splitlines()
evidence_lines = [{'line_1based':i,'text':line} for i,line in enumerate(job_lines,1)
                  if ('hepta-agentd-cognitive-write-qualification' in line or MERGE in line)]
assert any('Compiling Rust bin' in r['text'] for r in evidence_lines)
assert any('Testing '+target in r['text'] for r in evidence_lines)
assert any(target+'  PASSED in 31.0s' in r['text'] for r in evidence_lines)
assert any('[command]' in r['text'] and MERGE in r['text'] for r in evidence_lines)

result = {
 'schema':'hepta-b13-original-windows-root-verification-v1',
 'observed_utc':datetime.now(timezone.utc).isoformat(),
 'decision':'CLOSED_SCOPED',
 'scope':'Original Windows Lease/Queue fixture contract on 5b and equal-tree merge9063; not whole-project or five-platform acceptance.',
 'head':HEAD,'merge':MERGE,'tree':TREE,
 'original_exit_condition_zh':original_exit,'original_exit_unchanged':True,
 'frozen_nine':frozen,'original48_association':original48,
 'archives':archives,'source_bindings':sources,
 'all_nine_complete_case_bodies_read_and_exactly_bound':True,
 'contract_review':[{k:r[k] for k in ('name','source_path','source_line_start','source_line_end','preserved_contract')} for r in review['case_index']],
 'queue_actual':queue_rows,'agentd_actual':{'job_id':127339255880,'artifact_id':13431285250,'source':collector['source'],
    'target':target,'rows':agent_rows,'log_identity':ident(raw_log),'complete_wrapper_summary':{'passed':3,'failed':0,'ignored':0,'filtered':172,'seconds':30.56},
    'job_original':file_id(job_path),'actual_compile_test_and_checkout_lines':evidence_lines},
 'negative_control_review':'Original test bodies retain physical hook block, caller cancellation, injected completion panic/error, process fence after short dispatch expiry, release_count==0, real SQLite reopen with no resubmit, gated DB ACK and actual wall-clock H7 quarantine. No mutation-negative experiment is invented.',
 'budgets':'Original current source TTL30s then actual expiry; Queue10s/25s waits,400ms/300ms and1/11/11s observations unchanged.',
 'limits':[
    'Collector alone only records existing logs and checkout at collection; full job adds actual checkout, compile and test actions. Execution-log zst is preserved, not decoded by this receipt.',
    'Existing Bazel retry/cache policy remains; no retries=0 claim. Final Agentd target contains only log/XML, not an attempt inventory.',
    'Bazel wrapper XML is not a per-Rust-case inventory; names come from complete original test.log bodies.',
    'Queue working files may be CRLF; recorded Git objects and original working hashes remain distinct.',
    'Default Cargo omits qualification feature, but original explicit Bazel target actually ran it.',
    'Historical Q05/Q06 five-platform collection plan is not five-platform all-pass. Original failed guardian platform is Windows-shard3.',
    'Historical d12 native results and empty targeted_negative_observations are preserved, not borrowed or embellished.',
    'New eed tree, full B15 and production Agentd/AppServer/Root/Current acceptance remain independently pending.'
 ],
 'independent_review':file_id(REVIEW/'closure-review.json'),
 'api_binding':file_id(api_path),
 'native_tests_executed_by_this_root_verification':False,
 'counts_after_B22_and_B13':{'CLOSED_SCOPED':10,'OPEN':12,'SCIENTIFIC_HOLD':1}
}
out = ROOT / 'hepta-audit-fifth/inputs/b13-original-windows-closure-root-verification-v1.json'
out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'decision':result['decision'],'original_names':len(names),'archive_members':sum(x['members'] for x in archives),'sources':len(sources),'receipt':file_id(out)},ensure_ascii=False))
