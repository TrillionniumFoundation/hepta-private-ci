import json,hashlib,base64,gzip,re,datetime
from pathlib import Path
p=json.load(open('/tmp/hepta-36fa-boxing-build-deep-review-input.json'))
sha=lambda b:hashlib.sha256(b).hexdigest()
git=lambda b:hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
checked=[]
for k,v in p.items():
 if isinstance(v,dict) and isinstance(v.get('content'),str) and v.get('sha'):
  b=v['content'].encode()
  assert git(b)==v['sha'],(k,git(b),v['sha'])
  checked.append({'key':k,'blob':v['sha'],'bytes':len(b),'sha256':sha(b)})
m=json.loads(p['native_panel_boxing_manifest']['content'])
before=p['native_panel_boxing_before']['content']; after=p['native_panel_boxing_after']['content']
for key in ('after','patch'):
 b=p['native_panel_boxing_'+key]['content'].encode()
 assert len(b)==m[key]['bytes'] and sha(b)==m[key]['sha256']
start=before.index('    async fn completed(')
end=before.index('\n    async fn read(',before.index('    async fn completed_for_publication('))
astart=after.index('    fn completed(')
aend=after.index('\n    async fn read(',after.index('    fn completed_for_publication(')+8)
assert before[:start]==after[:astart]
assert before[end:]==after[aend:]
body=before[before.index('        let (original',start):end]
assert body.endswith('    }\n')
body=body[:-6]
abody=after[after.index('            let (original',astart):aend]
assert abody.endswith('        })\n    }\n')
abody=abody[:-17]
dedented=''.join(x[4:] if x.strip() else x for x in abody.splitlines(True))
assert body==dedented,(repr(body[-100:]),repr(dedented[-100:]))
macro_re=r'\bassert(?:_eq|_ne)?!\s*'
asserts_before=re.findall(macro_re,before);asserts_after=re.findall(macro_re,after)
assert asserts_before==asserts_after
assert before.count('#[tokio::test')==after.count('#[tokio::test')==3
assert after.count('Box::pin(async move {')==before.count('Box::pin(async move {')+1
selected=json.load(open('/tmp/hepta-36fa-panel-static-selected-prologues.json'))
full=p['native_panel_static_full_prologues']['content']
static=json.loads(p['native_panel_static_result']['content'])
assert sha(full.encode())==static['combined_disassembly']['sha256']
assert len(full.encode())==static['combined_disassembly']['bytes']==97755
allocations={}
for f in selected['files']:
 b=f['text'].encode()
 assert f['eof'] and len(b)==f['size'] and sha(b)==f['sha256']
 assert f['text'] in full
 lines=f['text'].splitlines()
 instructions='\n'.join(lines[7:21])
 loop=re.search(r'sub\s+\$0x([0-9a-f]+),%r11',instructions)
 rsp=[int(x,16) for x in re.findall(r'sub\s+\$0x([0-9a-f]+),%rsp',instructions)]
 if loop:
  assert rsp[0]==4096
  alloc=int(loop.group(1),16)+sum(rsp[1:])
 else: alloc=sum(rsp)
 allocations[Path(f['path']).name]=alloc
expect={'frame-31-prologue.txt':1586536,'frame-21-prologue.txt':2867912,'frame-20-prologue.txt':662856,'frame-19-prologue.txt':1861448,'frame-17-prologue.txt':1186072,'frame-16-prologue.txt':104936,'frame-13-prologue.txt':33208,'frame-14-prologue.txt':11144,'frame-15-prologue.txt':5576,'frame-00-prologue.txt':1576}
for k,v in expect.items():assert allocations[k]==v,(k,allocations[k],v)
assert sum(allocations[k] for k in list(expect)[:5])==8164824
build=json.loads(p['native_v4_actual_result']['content']);buildraw=p['native_v4_complete_raw']['content'].encode()
assert len(buildraw)==build['execution']['log_bytes']==82091
assert sha(buildraw)==build['execution']['log_sha256']
buildgz=base64.b64decode(p['native_v4_complete_gzip_b64']['content'])
assert gzip.decompress(buildgz)==buildraw
assert git(buildgz)=='f96eff393976d08a755c8556a5b3e8af5bded4d6'
assert build['execution']['returncode']==0 and not build['execution']['timed_out'] and build['tests_executed']==0
assert build['source_before']==build['source_after']
deep=json.loads(p['native_deep_v2_actual_result']['content'])
deepraw=p['native_deep_v2_actual_raw']['content'].encode()
assert len(deepraw)==deep['raw']['bytes']==100716 and sha(deepraw)==deep['raw']['sha256']
deepgz=base64.b64decode(p['native_deep_v2_actual_gzip_b64']['content'])
assert len(deepgz)==11229 and sha(deepgz)==deep['raw']['gzip_sha256']
assert gzip.decompress(deepgz)==deepraw and git(deepgz)=='6768bb5457093bc8067830968c82f8760e0d18c8'
assert deep['execution']['returncode']==0 and not deep['execution']['timed_out'] and deep['test_started']
assert deep['source_before']==deep['source_after'] and deep['original_stack_contract']['adjusted_rlimit']==False
stop=json.loads(p['native_deep_v2_actual_time_stop']['content'])
assert stop['delay_seconds']==55 and stop['signal_sent']
text=deepraw.decode()
thread42=text.split('Thread 42 (',1)[1].split('\nThread ',1)[0]
chain=['Digest32::of_bytes','FrozenLearningScopeV2::validate_request','FrozenLearningScopeV2::validate_snapshot','require_original_material_signatures','read_current_material','current_material','require_current_in_lane','require_original_source_capture']
indices=[thread42.index(x) for x in chain]
assert indices==sorted(indices)
threads=re.findall(r'^Thread (\d+) \(',text,re.M)
report={'schema':'hepta.utility.root-boxing-build-deep-review.v1','reviewed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'checked_blobs':checked,
'boxing':{'source_path':m['path'],'before_blob':m['before_blob'],'after_blob':m['after']['blob'],'outside_constructor_block_byte_equal':True,'original_async_body_exact_after_dedent':True,'assertion_macro_calls_before':len(asserts_before),'assertion_macro_calls_after':len(asserts_after),'tokio_test_attributes':3,'forwarder_await_removed':True,'boxed_async_body_preserved':True,'prepared_only':True,'compiled_or_executed':False},
'static_evidence':{'selected_original_files':len(selected['files']),'all_selected_bytes_in_full_original':True,'full_disassembly_bytes':len(full.encode()),'full_disassembly_sha256':sha(full.encode()),'directly_parsed_frame_allocations':{k:allocations[k] for k in expect},'five_fixture_and_test_frames_total':8164824,'original_thread_stack_bytes':8388608,'conclusion':'Measured nested fixture and test frames account for most of the unchanged 8 MiB stack; earlier guard-page fault is consistent with accumulated large frames. This does not establish that every overflowing case is fixed.'},
'new_build':{'label':'NEW_BUILD_DIAGNOSTIC','raw_bytes':len(buildraw),'raw_sha256':sha(buildraw),'original_gzip_matches':True,'metadata_and_binary_list_only':True,'exit_code':0,'tests_executed':0,'source_before_after_identical':True},
'deep_debugger':{'raw_bytes':len(deepraw),'raw_sha256':sha(deepraw),'original_gzip_matches':True,'thread_sections':len(threads),'unique_thread_ids':len(set(threads)),'delay_seconds':55,'gdb_exit_code':0,'outer_child_wrapper_exit_code':1,'outer_wrapper_status_literal_error_preserved':True,'source_before_after_identical':True,'stack_contract_unchanged':True,'observed_active_thread_42_chain':chain,'conclusion':'One snapshot shows active hashing and original source validation while other owner/channel threads wait. It does not establish a deadlock or identify a safe performance optimization. No test PASS, full-gate PASS or A/B/C qualification is inferred.'},
'limits':['Prepared boxing patch requires formatting, compilation and fresh original-case execution on the new frozen source.','The e8 focused gate remains failed.','No original-source, authority, freshness, stack-size or timeout condition is relaxed.']}
out=Path('/tmp/hepta-36fa-boxing-build-deep-root-review.json');out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'output':str(out),'bytes':out.stat().st_size,'sha256':sha(out.read_bytes()),'boxing':report['boxing'],'static':report['static_evidence'],'deep':report['deep_debugger']},ensure_ascii=False))

