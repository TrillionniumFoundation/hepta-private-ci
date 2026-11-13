#!/usr/bin/env python3
"""Fixed-byte/static review only. Does not import project or execute tests."""
import difflib, hashlib, json, re
from pathlib import Path
D=Path('/tmp/hepta-36fa-root-product-e2-proposal-v1/material-source-mechanism-tests-layer-v1')
O=Path('/tmp/hepta-36fa-material-source-tests-independent-review-v1')
R=Path('/tmp/hepta-36fa-root-product-e2-proposal-v1/references')
P='codex-rs/hepta-agentd/src/'
def pin(b): return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def read(p):
 p=Path(p);a=p.stat();b=p.read_bytes();z=p.stat()
 assert (a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns)==(z.st_dev,z.st_ino,z.st_size,z.st_mtime_ns,z.st_ctime_ns)
 return b
def emit(n,v):
 b=(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
 with (O/n).open('xb') as f:f.write(b)
 return pin(b)
raw=read(D/'SOURCE_PACKET.json');j=json.loads(raw);mf=json.loads(read(D/'MANIFEST.json'));author=json.loads(read(D/'REVIEW.json'))
assert pin(raw)==mf['packet']=={'bytes':23193,'sha256':'4bc66d55dc7a3030f24a5756b82296d230a814e5df5b9ccb17f01f2c8deb2d3b','git_blob':'e120273ac730addd8cc47f31e829692afa17bc0d'}
for n,k in [('SOURCE_DELTA.patch','patch'),('REVIEW.json','review'),('REGISTRATION_IMPACT.json','registration')]:assert pin(read(D/n))==mf[k]
assert len(j['entries'])==2
rows=[];patch=[]
for e in j['entries']:
 a=e['after_utf8'].encode();assert pin(a)==e['after'] and read(D/'after'/e['path'])==a
 b=b'' if e['before'] is None else e['before_utf8'].encode()
 if e['before'] is not None:
  assert pin(b)==e['before'] and read(D/'before'/e['path'])==b
  prior=Path('/tmp/hepta-36fa-root-product-e2-proposal-v1/material-source-loan-layer-v1/after')/e['path']
  assert read(prior)==b
  assert a==b+b'\n#[cfg(test)]\n#[path = "circuit_task_source_material_tests.rs"]\nmod tests;\n'
 rows.append({'path':e['path'],'before':e['before'],'after':e['after']})
 patch.extend(difflib.unified_diff(b.decode().splitlines(True),a.decode().splitlines(True),fromfile='a/'+e['path'] if b else '/dev/null',tofile='b/'+e['path']))
assert ''.join(patch).encode()==read(D/'SOURCE_DELTA.patch')
t=j['entries'][1]['after_utf8'];assert t.endswith('    Ok(())\n')
# Fixed source contains ordinary strings and line comments only; remove those
# before retaining exact brace-stack locations. This is not a Rust parser.
masked=re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*',lambda m:''.join('\n' if c=='\n' else ' ' for c in m[0]),t)
stack=[]
for i,c in enumerate(masked):
 if c=='{':stack.append(i)
 elif c=='}':
  assert stack
  stack.pop()
assert len(stack)==1
start=t.index('async fn material_source_encoding_refuses_withdrawn_original_for_all_views')
assert stack[0]==t.index('{',start)
methods=re.findall(r'#\[tokio::test\]\nasync fn (\w+)\(',t)
assert methods==author['methods'] and len(methods)==3
assert t.index('drop(driver);')<t.index('store.close().await;')<t.index('publication: body?')
refs=[]
for r in author['source_references']:
 p=R/r['path'];b=read(p);want={k:r[k] for k in ('bytes','sha256','git_blob')};assert pin(b)==want
 refs.append({'local':str(p),'path':r['path'],**want})
for needle in ['driver.execute(&request, CircuitTaskModeV1::Drive','source.publish_result(&identity, &record, &receipt)?','publication.history_digest() == receipt.trace().history_digest()','actual == fixture.publication','request == owner.read("request", "A")?','input == owner.read("input", "A")?','result == owner.read("result", "A")?','changed.publication_digest = cell::d("another original publication")','changed.record.snapshot.run_id = cell::id("another-run")','fixture.source.withdraw_source(&cell::id("A"))?','for current in [&view, &alias]','== Err(Error::Unavailable)','== Err(Error::InvalidBinding)']:assert needle in t
proof={'state':'STATIC_BYTE_CHECK_COMPLETED_WITH_CONFIRMED_SOURCE_SYNTAX_BLOCKER','packet':pin(raw),'files':rows,'production_body_plus_exact_test_mount':True,'complete_patch_equal':True,'test_methods':methods,'unclosed_function':{'name':methods[-1],'declaration_line':t[:start].count('\n')+1,'opening_brace_line':t[:stack[0]].count('\n')+1,'total_lines':len(t.splitlines()),'tail_utf8':t[-220:],'missing_exact_termination':'}\n','after_utf8_and_local_exact':True,'brace_stack_after_comment_and_string_mask':[{'offset':p,'line':t[:p].count('\n')+1} for p in stack]},'reference_pins':refs,'project_execution':False,'native_h_calls':0}
bp=emit('BYTE_AND_SCOPE_PROOF.json',proof)
review={'format':'hepta-material-source-mechanism-tests-independent-review-v1','state':'STATIC_BLOCKER_FOUND_NOT_COMPILED_NOT_EXECUTED','candidate':{'local':str(D/'SOURCE_PACKET.json'),**pin(raw)},'manifest':pin(read(D/'MANIFEST.json')),'byte_proof':bp,'concrete_blockers':[{'id':'B01_UNCLOSED_LAST_TEST_FUNCTION','file':P+'circuit_task_source_material_tests.rs','pin':j['entries'][1]['after'],'finding':'The exact 7,528-byte new test file and packet end at Ok(()) followed by LF. The third async test, declared on line 128, is not closed. Comment/string-masked brace analysis retains its one opening brace. This is a static syntax blocker, not a compiler/test result.','requested_successor':'Preserve original packet e120273 and test 1c8ea959; author may freeze a separate two-byte closing-brace-plus-LF increment. No reviewer source edit or runtime retry.'}],
 'nonblocking_semantic_review':[{'case':methods[0],'scope':'Uses an actual Source/Cell journal and witness, original AutomationStore and CircuitTaskDriver, obtains the Driver private receipt, publishes through the original Source and checks its history digest. Full payload decode equals the publication; binding and exact request/input/result bytes independently match the actual local Source owner records. All four journal/witness bytes remain equal and controlled model invocation count remains one.'},{'case':methods[1],'scope':'Separately mutates only the cloned publication digest and then original record run id; each must return exact InvalidBinding. Unchanged publication remains a positive control with identical payload, all four original files unchanged and no extra inference.'},{'case':methods[2],'scope':'Calls the actual original Source withdrawal, retains two local readback aliases, requires exact Unavailable from encode and original read_run_publication on both; reads preserve post-withdrawal bytes and model count one. This case currently has the syntax blocker.'}],
 'cleanup':'The fixture captures operation Result, drops the Driver and awaits original AutomationStore.close before propagating body?. No fallible Result step intervenes between store opening and that captured body. Earlier constructor failures drop local owned values. Outer future cancellation is explicitly not a joined-task or physical shutdown proof.',
 'controlled_materials':['Existing original::record carries controlled RunStart fixture authentication; no real owner signature or task authorization is demonstrated.','Existing cell::Model is controlled inference and increments its original call counter; private Circuit Driver Receipt is still produced by the real Driver, not supplied by the test.'],
 'unchanged':'The parent production module is exact f86baedb plus a 75-byte cfg(test) child mount. No production protocol/body, budgets or authority constructor changes occur in this test layer.',
 'not_proven':['Root/Material IPC, peer PID/UID/pidfd/nonce or host authority','Cross-process full chain or process cold recovery','Remote client cancellation or concurrency','Inference quality or real task authorization','Any successful compilation or test run'],
 'execution':{'python_static_only':True,'tests_run':0,'qa_run':0,'compiler_run':0,'H_calls':0,'source_or_ref_writes':False,'git_upload_by_reviewer':False},
 'storage':'All report pins are local computed content identities for Root archival; original candidate remains byte-for-byte unchanged.'}
rp=emit('REVIEW.json',review)
names=['review_static.py','BYTE_AND_SCOPE_PROOF.json','REVIEW.json']
idx={'format':'hepta-closed-static-review-index-v1','root':str(O),'state':'LOCAL_COMPUTED_ONLY','entries':[{'name':n,**pin(read(O/n))} for n in names]}
ip=emit('CLOSED_FILE_INDEX.json',idx)
print(json.dumps({'REVIEW':rp,'PROOF':bp,'INDEX':ip,'blocker':'last async test unclosed'},ensure_ascii=False))
