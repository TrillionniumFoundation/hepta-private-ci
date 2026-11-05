from pathlib import Path
from datetime import datetime,timezone
from collections import Counter
import hashlib,json,re,zipfile

ROOT=Path('/workspace/scratch/07dd58cc9630')
D=ROOT/'architecture-audit/b11-pr4884-ci-20261105/terminal/probe-127383345954'
def read(p):return json.loads(Path(p).read_text())
def ident(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'computed_git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def fid(p):return {'local_file':str(p),**ident(Path(p).read_bytes())}
review=read(D/'terminal-review.json')
verify=read(D/'artifact-verification.json')
projection=read(D/'physical-observation-projection.json')
classification=read(D/'failure-classification.json')
api=read(ROOT/'hepta-audit-fifth/inputs/b11-native5-artifacts-api.json')
artifact=next(x for x in api['structuredContent']['artifacts'] if x['id']==13432969770)
zp=D/'artifact-13432969770.zip'
zb=zp.read_bytes()
assert len(zb)==artifact['size_in_bytes']==2029329
assert hashlib.sha256(zb).hexdigest()==artifact['digest'].removeprefix('sha256:')=='4b36db2a7068cdd4d3498a5097193e62de3a2a6463c2dbc4b54a876c7f2ba5e7'
assert artifact['workflow_run']['head_sha']=='7e0b2303ed0242d83bf56202e8ffb17f5c856186'
assert artifact['workflow_run']['id']==42066891449
member_rows=[]
with zipfile.ZipFile(zp) as z:
 assert z.testzip() is None
 assert len(z.namelist())==len(set(z.namelist()))==len(verify['members'])==14
 for m in verify['members']:
  b=z.read(m['path']);v=ident(b)
  assert v['bytes']==m['bytes'] and v['sha256']==m['sha256'] and v['computed_git_blob']==m['git_blob']
  assert z.getinfo(m['path']).CRC==m['crc']
  assert b==(D/'members'/m['path']).read_bytes()
  member_rows.append({'member':m['path'],**v})
 source=z.read('b11-token-mechanism-probe/source-head-tree.txt').decode()
 assert '582f5315f4f632444ae3782d9381f69ed1ae555d' in source
 assert '1718e3e2235b875320f366d03cf796e2a4e92281' in source
 assert not z.read('b11-token-mechanism-probe/source-status-before.txt').strip()
 assert not z.read('b11-token-mechanism-probe/source-status-after.txt').strip()
 assert z.read('b11-token-mechanism-probe/original-bazel-exit-code.txt').strip()==b'3'
 assert z.read('b11-token-mechanism-probe/console-copy-exit-code.txt').strip()==b'0'
 source_leaves=z.read('b11-token-mechanism-probe/source-leaves.txt').decode()
 for row in review['source_leaf_checks']:
  assert f"{row['mode']} {row['type']} {row['git_blob']}\t{row['path']}" in source_leaves
 log_member='bazel-execution-logs/failed-test-logs/invocation-iloq9z78/targets/0000/test.log'
 raw=z.read(log_member);text=raw.decode();lines=text.splitlines()
 assert ident(raw)['sha256']=='fcea1fd7d4a059130a34b392f5171e5db76ddfd2d0a0a0f21ebd7414641f71fc'

summaries=[]
for i,line in enumerate(lines,1):
 m=re.fullmatch(r'test result: (?:ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out; finished in (.+)s',line)
 if m:summaries.append({'line':i,'raw':line,'counts':list(map(int,m.groups()[:5])),'seconds':m[6]})
assert [r['counts'] for r in summaries]==[[90,2,0,0,63],[53,8,2,0,92]]
assert Counter(r['classification'] for r in classification['failures'])=={
 'PRODUCTION_REPAIR_ENDPOINT_REOPEN_ACCESS_DENIED':2,
 'HOST_NEGATIVE_PRECONDITION_FAILED_REOPEN_SUCCEEDED':1,
 'ACTUAL_STRICT_TOKEN_OUTSIDE_DELETE_ESCAPE':1,
 'ORDINARY_HOST_NEITHER_PRECONDITION_FAILED_BEFORE_RESTRICTED_SUBJECT':2,
 'SHARED_TEST_MUTEX_POISON_NOT_INDEPENDENT_BUSINESS_ORACLE':4}
normalized=text.replace('\r\n','\n')
for row in classification['failures']:
 assert normalized.count(row['original_block'])==1
 assert lines[row['line']-1]==row['original_block'].splitlines()[0]
passed=[]
for name in classification['three_now_direct_pass']:
 matches=[{'line':i,'raw':line} for i,line in enumerate(lines,1) if line==f'test {name} ... ok']
 assert len(matches)==1,(name,matches)
 passed.append({'name':name,**matches[0]})
for kind,group in projection['parsed'].items():
 prefix='PROBE_OBSERVATION_ONLY '+kind+' '
 for row in group['complete_json']:
  physical=lines[row['line']-1]
  assert json.loads(physical.split(prefix,1)[1])==row['value']
 for row in group['interleaved_not_repaired']:
  assert lines[row['line']-1]==row['raw']
  try:json.loads(row['raw'].split(prefix,1)[1])
  except json.JSONDecodeError:pass
  else:raise AssertionError('interleaved line unexpectedly parsed')
assert len(projection['parsed']['row']['complete_json'])==6
assert len(projection['parsed']['row']['interleaved_not_repaired'])==2
assert len(projection['parsed']['restoration']['complete_json'])==8
assert len(projection['parsed']['finalized']['complete_json'])==8
assert projection['restoration_objects']==80 and projection['restoration_errors']==0
assert (projection['restored_survivors'],projection['deleted_pending_objects'],projection['descendants_spawned'])==(54,26,0)
subjects=[(r['value']['subject'],r['value']['outside_level']) for r in projection['parsed']['row']['complete_json']]
assert set(subjects)=={('host','low_other_cohort'),('current_strict','low_other_cohort'),('current_strict_low','medium'),('current_strict_low','low_other_cohort'),('full_restricting_explicit_read','medium'),('full_restricting_explicit_read','low_other_cohort')}
for r in projection['complete_marker']:assert lines[r['line']-1]==r['raw']
assert review['combined_disjoint_counts']=={'total_named_tests':155,'passed':143,'failed':10,'ignored':2}

result={'schema':'hepta-b11-native5-original-root-verification-v1','observed_utc':datetime.now(timezone.utc).isoformat(),
 'run':42066891449,'job':127383345954,'head':'7e0b2303ed0242d83bf56202e8ffb17f5c856186',
 'actual_checkout':'582f5315f4f632444ae3782d9381f69ed1ae555d','actual_tree':'1718e3e2235b875320f366d03cf796e2a4e92281',
 'scope':'Actual merged primaryeed+diagnostic7e; whole target FAILED; B11 remains OPEN',
 'archive':fid(zp),'official_artifact':artifact,'all14_crc_hash_and_local_originals_verified':True,'members':member_rows,
 'source_leaves':review['source_leaf_checks'],'source_clean_before_after':True,'exit_codes':{'bazel':3,'console_copy':0},
 'two_original_disjoint_harness_summaries':summaries,'combined_counts':review['combined_disjoint_counts'],
 'three_original_named_passes':passed,'failures':classification['failures'],
 'failure_category_counts':dict(Counter(r['classification'] for r in classification['failures'])),
 'physical_projection':fid(D/'physical-observation-projection.json'),
 'physical_complete_json_row_identities':[list(x) for x in subjects],
 'physical_interleaved_rows':['host/medium','current_strict/medium'],
 'all8_restoration_and_finalized_rows_equal_original_json':True,
 'objects':80,'restoration_errors':0,'survivors':54,'deleted_pending':26,'descendants_spawned':0,
 'job_log':fid(D/'job.log'),'original_test_log':ident(raw),
 'limits':['Only144 contiguous direct result lines exist; all155 unique case outcomes are not invented from interleaved output. Whole counts come from two original disjoint harness summaries.',
 'Eight-row completion marker and probe PASS are observation-only, not production isolation qualification.',
 'Unlike native4, this native5 has host/low complete and current_strict/medium interleaved. Missing JSON is never repaired.',
 'The successful partial read/legacy fixtures are observations at this actual source. Additional READ_CONTROL is not proved the sole cause.',
 'New host-control failure means combined-access ReOpenFile succeeded, so no-WRITE_DAC prerequisite was not established.',
 'Two ordinary-host Neither failures precede restricted-subject checks; four poisoned mutex failures are downstream nonexecution, not independent business failures.',
 'Directory ReOpen error5, strict external delete, normal loader/read-owner lifecycle and full B11 exit remain open.'],
 'native_tests_rerun_by_verifier':False,'all_blockers_closed':False}
out=ROOT/'hepta-audit-fifth/inputs/b11-native5-root-original-verification-v1.json'
out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'receipt':fid(out),'counts':result['combined_counts'],'B11':'OPEN'},ensure_ascii=False))
