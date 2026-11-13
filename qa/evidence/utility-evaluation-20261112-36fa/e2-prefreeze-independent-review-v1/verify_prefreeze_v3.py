from pathlib import Path
import ast, copy, hashlib, json, re

OUT=Path('/tmp/hepta-36fa-e2-prefreeze-independent-review-v1')
ROOT=Path('/tmp/hepta-36fa-root-product-e2-proposal-v1')
VIEW=Path('/tmp/hepta-36fa-root-product-composition-v8/after')
PREFIX='codex-rs/hepta-agentd/src/'
HELPER=Path('/tmp/hepta-36fa-e2-registration-independent-review-v1/review_bytes_v2.py')
def pin(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def check(b,p):
 q=pin(b);assert q=={k:p[k] for k in q},(q,p);return q
def put(name,obj):
 b=(json.dumps(obj,sort_keys=True,ensure_ascii=False,indent=2)+'\n').encode()
 with (OUT/name).open('xb') as f:f.write(b)
 return {'path':str(OUT/name),**pin(b)}
ns={'re':re}
tree=ast.parse(HELPER.read_text());defs=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ['rust_code','balanced','declarations']]
assert len(defs)==3
exec(compile(ast.Module(body=defs,type_ignores=[]),'reviewer-only lexical helpers','exec'),ns)
decl=ns['declarations'];mask=ns['rust_code']
def function(text,name,impl=None):
 found=[f for f in decl(text) if f['name']==name and (impl is None or impl in (f['impl_header'] or ''))]
 assert len(found)==1,(name,impl,len(found))
 return found[0]
def describe_function(text,name,impl=None):
 f=function(text,name,impl);return {'name':name,'impl':f['impl_header'],'start_line':text.count('\n',0,f['start'])+1,'end_line':text.count('\n',0,f['end'])+1,'body_pin':pin(f['body'].encode()),'body':f['body']}

layers=[];composed={};base={};new_paths=[];deltas=[]
for name,oid,expected_files,expected_new,expected_splices in [
 ('prefreeze-source-layer-v1','c66c54e9989023b79f62b10575350293d21301a0',20,7,20),
 ('prefreeze-ready-increment-v1','3181789965054fd440568f0ac4d4e242194d34f3',9,2,24)]:
 D=ROOT/name;raw=(D/'SOURCE_PACKET.json').read_bytes();assert pin(raw)['git_blob']==oid
 packet=json.loads(raw);assert len(packet['entries'])==expected_files
 splices=json.loads((D/'EXACT_SOURCE_SPLICES.json').read_bytes())['splices'];assert len(splices)==expected_splices
 by={}
 for s in splices:by.setdefault(s['path'],[]).append(s)
 files=[];changed_functions=[];new_functions=[];unchanged_functions=0
 for row in packet['entries']:
  p=row['path'];before=row['before_utf8'];after=row['after_utf8'];check(after.encode(),row['after'])
  assert (D/'after'/p).read_bytes()==after.encode()
  if before is None:
   assert row['before'] is None and not (VIEW/p).exists(),p
   new_paths.append(p)
  else:
   check(before.encode(),row['before']);assert (D/'before'/p).read_bytes()==before.encode()
   if p in composed:assert composed[p]==before,p
   else:assert (VIEW/p).read_bytes()==before.encode(),p
   value=before; inverse_positions=[]
   for s in by.get(p,[]):
    assert value.count(s['before_utf8'])==1,(name,p,'nonunique before')
    at=value.index(s['before_utf8']); inverse_positions.append((at,s))
    value=value[:at]+s['after_utf8']+value[at+len(s['before_utf8']):]
   assert value==after,(name,p,'forward')
   for at,s in reversed(inverse_positions):
    assert value[at:at+len(s['after_utf8'])]==s['after_utf8'],(name,p,'inverse exact span')
    value=value[:at]+s['before_utf8']+value[at+len(s['after_utf8']):]
   assert value==before,(name,p,'inverse')
  if p not in base:base[p]=before
  composed[p]=after
  old={(f['impl_header'],f['name']):f for f in decl(before or '')}
  now={(f['impl_header'],f['name']):f for f in decl(after)}
  for key,f in now.items():
   if key not in old:new_functions.append({'path':p,'key':key,'body_pin':pin(f['body'].encode())})
   elif f['body']==old[key]['body']:unchanged_functions+=1
   else:changed_functions.append({'path':p,'key':key,'before_body':pin(old[key]['body'].encode()),'after_body':pin(f['body'].encode())})
  removed=[{'path':p,'key':k,'body_pin':pin(v['body'].encode())} for k,v in old.items() if k not in now]
  files.append({'path':p,'before':row['before'],'after':row['after'],'reverse_exact':before is not None,'new_file':before is None,'removed_function_definitions':removed})
 assert sum(f['new_file'] for f in files)==expected_new
 layers.append({'directory':str(D),'packet':pin(raw),'manifest':pin((D/'MANIFEST.json').read_bytes()),'splices':pin((D/'EXACT_SOURCE_SPLICES.json').read_bytes()),'api':pin((D/'API_CONTRACT.json').read_bytes()),'files':files,'splices_count':len(splices),'unchanged_functions':unchanged_functions,'changed_functions':changed_functions,'new_functions':new_functions})
assert len(composed)==23 and len(set(new_paths))==9,(len(composed),len(set(new_paths)))

def s(name):return composed[PREFIX+name]
channel_path=ROOT/'references/codex-rs/hepta-contracts/src/authority_host_peer.rs'
channel=channel_path.read_text();assert pin(channel.encode())['git_blob']=='36e4524baea04320b7610325579f0ff206690fab'
owner_channel_path=ROOT/'references'/ (PREFIX+'learning_owner_command_channel.rs')
owner_channel=owner_channel_path.read_text();assert pin(owner_channel.encode())['git_blob']=='f42d9f385ecafa17e02d993677ca261e02926beb'
journal_path=ROOT/'references'/(PREFIX+'circuit_task_source_journal.rs');journal=journal_path.read_text()
assert pin(journal.encode())['git_blob']=='0efe1917606802d2d47ed5ceda10e581a7c803c5'
wire_path=VIEW/(PREFIX+'circuit_task_source_material_wire.rs');wire=wire_path.read_text()
assert 'pub(crate) const LIMIT: u64 = 128;' in wire
assert 'Duration::from_millis(500)' in wire and 'pub(crate) const BOUND: usize = 16_384;' in wire

def ordered(body,needles):
 cursor=0;positions=[]
 for needle in needles:
  pos=body.index(needle,cursor);positions.append({'needle':needle,'byte_offset_utf8':len(body[:pos].encode())});cursor=pos+len(needle)
 return positions
server=function(s('authority_host_prefreeze_source.rs'),'serve_original_prefreeze')['body']
client=function(s('circuit_task_source_prefreeze.rs'),'read_prefreeze','impl Client')['body']
constructor=function(s('circuit_task_source_prefreeze.rs'),'from_original_prefreeze_root_stream')['body']
taskserve=function(s('circuit_task_remote_service.rs'),'serve')['body']
original_material=function(s('authority_host_session_material_source.rs'),'serve')['body']
assert original_material==function(base[PREFIX+'authority_host_session_material_source.rs'],'serve')['body']
flow={
 'server_ready_and_data':ordered(server,['original_owner_command_channel_v1(', 'let startup_end = startup_end.min(self.end)', 'original_prefreeze_is_pending(', 'self.source_ready.wait_original(startup_end)', 'read_original_prefreeze_source(', 'let hint = ready::frame', 'channel.request(&hint)', 'wire::before(startup_end)', 'for id in 2..=wire::LIMIT', 'let mut deadline = None', 'channel.exchange(|bytes|', 'let until = (Instant::now() + timeout).min(self.end)', 'read_original_prefreeze_source(', 'wire::response(', 'wire::before(until)', 'Ok(true)', 'channel.check_peer_lifetime()', 'wire::before(deadline.ok_or_else']),
 'client_ready':ordered(constructor,['let startup_end = startup_end.min(end)', 'original_owner_command_channel_v1(', 'ready::wait_first_frame(socket, startup_end)', 'original.check_peer_lifetime()', 'original.exchange(|bytes|', 'if bytes != expected', 'Ok(expected.clone())', 'if !acknowledged', 'wire::before(startup_end)', 'original.check_peer_lifetime()', 'request.require_evidence(', 'next: 2']),
 'client_data':ordered(client,['identity != &self.identity', 'self.slot.try_lock()', '.take().ok_or', 'let deadline = (Instant::now() + self.timeout).min(self.end)', 'self.require_current()', 'read_request(', 'checked_add(1)', 'channel.original.request(', 'wire::before(deadline)', 'wire::read_response(', 'decode_current_root_payload(', 'self.request.require_publication(', 'channel.original.check_peer_lifetime()', 'self.require_current()', 'self.slot.try_lock()', 'wire::before(deadline)', '*slot = Some(channel)', 'Ok(observed)']),
 'actual_publish':ordered(taskserve,['let publication = frame.operation == Operation::Publish', 'let response = handle(', 'original.source.require_original_remote_binding(binding)', 'require_root_current(root)', 'if publication', 'root.observe_original_root_source_publication()', 'Ok(response)']),
 'old_material_deadline':ordered(original_material,['for id in 1..=wire::LIMIT', 'let mut deadline = None', 'channel.exchange(|bytes|', 'let until = (Instant::now() + timeout).min(self.end)', 'deadline = Some(until)', 'wire::before(until)', 'Ok(true)', 'let until = deadline.ok_or_else', 'wire::before(until)']),
 'HAP_server':ordered(function(channel,'exchange_inner')['body'],['.read(stream, &mut length[..1], self.owner.end())', 'let deadline = self.owner.deadline(self.policy.timeout)', 'read_until(stream, &mut length[1..], deadline)', 'read_until(stream, &mut bytes, deadline)', 'let response = handle(&bytes)', 'self.owner.check(deadline)', 'write_until(stream, &response, deadline)', 'self.owner.check(deadline)']),
 'HAP_client':ordered(function(channel,'request')['body'],['self.stream.take()', 'let deadline = self.owner.deadline(self.policy.timeout)', 'write_until(&mut stream, request, deadline)', 'read_until(&mut stream, &mut response, deadline)', 'self.owner.check(deadline)'])}
assert 'std::process::id()' in owner_channel and 'let same_uid' in owner_channel
assert 'channel.check_peer_lifetime()' in owner_channel and 'request_bound: 16_384' in owner_channel
assert 'ProductEvaluationExecutionStoreErrorV1::Missing => Error::ReconciliationRequired' in journal
assert 'ProductEvaluationExecutionStateV1::Pending => Err(Error::ReconciliationRequired)' in journal
assert 'ProductEvaluationExecutionStoreErrorV1::Indeterminate => Error::CommitUncertain' in journal
new_public=[]
for p,text in composed.items():
 old={(f['impl_header'],f['name']) for f in decl(base[p] or '')}
 for f in decl(text):
  if (f['impl_header'],f['name']) not in old:
   new_public.append({'path':p,'name':f['name'],'visibility':f['visibility'],'impl':f['impl_header'],'line':text.count('\n',0,f['start'])+1,'body_pin':pin(f['body'].encode())})

timing=put('TIMING_CORRECTION.json',{
 'format':'hepta-prefreeze-material-time-boundary-correction-v1','state':'STATIC_CORRECTION_NO_SOURCE_OR_BUDGET_CHANGE',
 'corrects':'The first prefreeze author text and any repetition treating between-frame idle as 500ms. Frozen original sources and reports are preserved; this is a separate explanatory record.',
 'sources':{'HAP':{'path':str(channel_path),**pin(channel.encode())},'owner_channel':{'path':str(owner_channel_path),**pin(owner_channel.encode())},'old_material_serve_source':{'path':str(VIEW/(PREFIX+'authority_host_session_material_source.rs')),**pin(base[PREFIX+'authority_host_session_material_source.rs'].encode())},'prefreeze_source_after':pin(s('authority_host_prefreeze_source.rs').encode()),'prefreeze_client_after':pin(s('circuit_task_source_prefreeze.rs').encode())},
 'findings':[
  'HAP exchange_inner waits for its first length byte with owner.end(). Only after that byte does it compute owner.deadline(policy.timeout). The remaining frame, handler, response send and final success check use that same inflight deadline.',
  'Old Material::serve and final prefreeze data-loop set deadline=None before exchange. The outer now+timeout deadline is created inside the handler, after HAP has received the complete request. The post-exchange comparison uses that handler-created deadline. It therefore does not retroactively impose a 500ms between-frame idle limit.',
  'In both Material and prefreeze clients, the outer read deadline is created before HAP request(), and HAP request starts its own timeout before sending. The caller-initiated request/response therefore has a 500ms maximum here, additionally bounded by that client end.',
  'The new readiness exchange is separately bounded by the existing absolute startup_end. Root checks before/after hint.request; client checks before passive poll and after the exact echo. The poll uses only that startup deadline and no Source, Cell or Current lock. Data starts at id2 after ready spends id1.',
  'A late failure can follow a completed underlying read, append, hint or response send. Post-response deadline/current checks report rejection or Unknown; they do not prove no side effects or retract bytes already transmitted.',
  'Host lifetime/end, client configured lifetime, same-stream fixed counter, 16KiB wire bound and 128 aggregate frames remain unchanged. This explanation does not grant a renewed idle allowance, modify HAP, or extend any actual configured end.'
 ],'ordered_code_evidence':{k:flow[k] for k in ['old_material_deadline','server_ready_and_data','client_ready','client_data','HAP_server','HAP_client']},
 'HAP_exchange_inner':describe_function(channel,'exchange_inner'),'old_material_serve':describe_function(s('authority_host_session_material_source.rs'),'serve'),'H_calls':0,'project_execution':False})

proof=put('BYTE_AND_FLOW_PROOF.json',{'format':'hepta-prefreeze-two-layer-independent-byte-flow-v1','state':'STATIC_ONLY_NOT_COMPILED','layers':layers,'combined_paths':len(composed),'combined_new_paths':len(set(new_paths)),'sources':[{'path':p,**pin(text.encode())} for p,text in sorted(composed.items())],'new_declarations':new_public,'ordered_flow':flow,'original_references':[{'path':str(p),**pin(p.read_bytes())} for p in [channel_path,owner_channel_path,journal_path,wire_path]],'timing_correction':timing,'bound_algebra':{'ready':1,'source_ids_first':2,'source_ids_last':128,'maximum_source_reads':127,'total_same_stream_frames':128,'frame_bytes':64,'whole_response_bound':16384,'timeout_ms':500,'max_lifetime_seconds':300,'max_startup_seconds':30},'unchanged_original_material_serve_body':pin(original_material.encode()),'reviewer_lexer':{'path':str(HELPER),**pin(HELPER.read_bytes())},'executed_project_code':False,'H_calls':0,'source_write':False})
print(json.dumps({'proof':proof,'timing':timing,'new_declarations':len(new_public)},indent=2))
