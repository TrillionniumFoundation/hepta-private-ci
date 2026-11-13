from pathlib import Path
import ast,json,hashlib,datetime
R=Path('/tmp/hepta-36fa-v8-single-archive-restoration-root-review-v1')
N=Path('/tmp/hepta-36fa-v8-single-archive-restoration-v1')
def identity(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def definitions(raw):
 s=raw.decode();lines=s.splitlines(keepends=True)
 return {n.name:''.join(lines[n.lineno-1:n.end_lineno]).encode() for n in ast.parse(s).body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
raw=(R/'driver.py').read_bytes();request_raw=(R/'request.json').read_bytes();cfg_raw=(R/'config.json').read_bytes()
assert identity(raw)['git_blob']=='aae1063cff9d2b95bac5d1db09c831164b4cd060'
assert identity(request_raw)=={'bytes':39070,'sha256':'1adf53833dc2d2d99957d59edcc4f4293d376cd7a17c7b1d30489cfb4d6a3123','git_blob':'b3eb87deffe130b7b839c305988275ab28386775'}
assert identity(cfg_raw)['git_blob']=='8c2b0c402ad78d1708ca976cee875b78caaca19f'
request=json.loads(request_raw);cfg=json.loads(cfg_raw)
assert set(request)=={'host','executable','args','cwd','idempotency_key','timeout_seconds','stdin'}
assert request['host']=='desktop' and request['executable']=='/usr/bin/python3' and request['cwd']=='/home/qian-qi'
assert request['args']==['-B','-c',raw.decode()] and request['stdin'].encode()==cfg_raw
assert request['idempotency_key']=='hepta-utility-36fa-v8-single-archive-restore-v1' and request['timeout_seconds']==900
inverse=dict(cfg);inverse['status']='HOLD_ROOT_EXACT_APPROVAL_REQUIRED';inverse['root_execution_approved']=False
assert (json.dumps(inverse,indent=2)+'\n').encode()==(N/'CONFIG.HOLD.json').read_bytes()
prior=(N/'driver.HOLD.py').read_bytes()
old=b"'allowed_parent_metadata_change': str(V8_DIR) + ' directory timestamps/size caused by the one new entry only'"
new=b"'parent_metadata_comparison_scope': str(V8_DIR) + ' dev/inode/mode/uid/gid/nlink are equal; size/mtime/ctime may differ. No directory enumeration or exclusive cause attribution; any cause beyond this observed operation remains unknown.'"
assert prior.count(old)==raw.count(new)==1 and raw.replace(new,old)==prior
runtime=(R/'original-runtime.py').read_bytes();v5=(R/'original-v5.py').read_bytes()
assert identity(runtime)['git_blob']=='b1d214e4fe3c036884f5c0bf99e1dc9d618a5d56'
assert identity(v5)['git_blob']=='6632d0cc1e0a127db9ee3324b32bf2d2fc2f7735'
actual=definitions(raw);a=definitions(runtime);b=definitions(v5);reused=json.loads((N/'STATIC_REUSE_REVIEW.json').read_text())['preserved_original_functions']['functions'];matches=[]
for row in reused:
 name=row['name'];source=b if name=='active_build_processes' else a
 assert actual[name]==source[name],name;matches.append({'name':name,'actual_body':identity(actual[name])})
ob=json.loads(Path('/tmp/hepta-36fa-isolated-native-v8-readonly-diagnostic-v1/OBSERVATION.original.json').read_text())
assert ob['parent_observations_before']==ob['parent_observations_after']
for row,mode in zip(ob['parent_observations_after'],[0o755,0o700,0o700]):
 assert row['lstat']['st_uid']==row['lstat']['st_gid']==1000 and row['lstat']['st_mode']&0o777==mode
record={'format':'hepta-root-exact-single-archive-review-v1','reviewed_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'EXACT_MATERIAL_ONLY_REQUEST_ACCEPTED','driver':identity(raw),'request':identity(request_raw),'configuration':identity(cfg_raw),'request_fields':sorted(request),'configuration_two_field_inverse_exact':True,'script_only_wording_inverse_exact':True,'preserved_original_definitions':matches,'actual_fixed_parent_permissions_match_readonly_observation':True,'operation_seconds':600,'retention_seconds':180,'outer_seconds':900,'per_download_seconds':120,'source_full_before_after_required':True,'original_guard_preserved':True,'original_archive_exact_bytes':29366352,'original_archive_sha256':'a35c75d1f26e6a983885a45b33490a4ebe54f05050568b32b89cfb421b30b583','original_archive_git_blob':'c6941f7873bdfb8ac18577c9844f234e76dc5ed6','destination_write':'Original missing pathname only, after full spool identity verification, with O_EXCL/O_NOFOLLOW; retain partial failures and never overwrite/retry.','scope':['The complete candidate driver was read; static AST/body comparisons only, not executed.','Exact historical HTTPS downloader/redirect/size/hash/120s checks and V5 process guard are unchanged.','No source, refs, raw index, existing binding, inherited environment or native test budget is changed.','The only child commands are closed readonly Git argv with owned-process cleanup.','Parent metadata is checked only to the expressly stated extent; no exclusive causal attribution.','No new native qualification or provider execution is authorized.'],'H_calls_by_this_review':0,'qualification':False,'real_qualified_task_chains':0}
(R/'REVIEW.json').write_text(json.dumps(record,indent=2)+'\n')
approval={'format':'hepta-root-exact-single-archive-dispatch-approval-v1','status':'APPROVED_ONCE_MATERIAL_ONLY','approved_at_utc':record['reviewed_at_utc'],'executor':'/root/native_ci_audit','request':identity(request_raw),'driver':identity(raw),'configuration':identity(cfg_raw),'review':identity((R/'REVIEW.json').read_bytes()),'idempotency_key':request['idempotency_key'],'authorization_scope':'One execution of this exact seven-field request. Reconcile an uncertain response only with this same original key and request. No automatic retry, new key, repair variation, native main, tests, source/ref/index mutation, or environment/limit changes. Preserve all originals, partial files and Unknown outcomes.','dispatch_occurred_in_this_record':False,'qualification':False}
(R/'APPROVAL.json').write_text(json.dumps(approval,indent=2)+'\n')
print(json.dumps({'review':identity((R/'REVIEW.json').read_bytes()),'approval':identity((R/'APPROVAL.json').read_bytes()),'reused_definitions':len(matches),'dispatch':False}))
