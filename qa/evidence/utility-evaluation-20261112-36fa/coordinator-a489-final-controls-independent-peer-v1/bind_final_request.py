"""Pure exact successor binding over independently GET-returned bytes."""
import ast,base64,gzip,json
from pathlib import Path
from review_fixed_controls import identity,pin,functions,pure_data,write

D=Path(__file__).resolve().parent
P=Path('/tmp/hepta-36fa-coordinator-a489-final-nonrust-preparation-v1')
C=P/'execution-candidate-v1';H=P/'launch-hold-v1'
manifest=json.loads((C/'ENCODING_MANIFEST.json').read_bytes())
encoding=next(x for x in manifest['members'] if x['name']=='ACTUAL_PROCESS_INPUT.candidate.json')
chunks=[];getobs=[]
for i,r in enumerate(encoding['parts'],1):
    name='candidate-process.part-%03d.b64'%i
    raw=(D/'inputs'/name).read_bytes()
    pin(raw,{k:r[k] for k in ('bytes','sha256','git_blob')})
    sdkraw=(D/'github'/(name+'.GET.original.json')).read_bytes();sdk=json.loads(sdkraw)
    assert sdk['structuredContent']['content'].encode()==raw
    assert raw.endswith(b'\n') and raw.count(b'\n')==1
    body=base64.b64decode(raw[:-1],validate=True)
    assert base64.b64encode(body)+b'\n'==raw
    assert r['decoded_offset']==sum(map(len,chunks));pin(body,r['decoded']);chunks.append(body)
    getobs.append({'name':name,'body':identity(raw),'actual_GET_SDK':identity(sdkraw),'full_readback_equal':True})
gz=b''.join(chunks);pin(gz,encoding['gzip']);typedraw=gzip.decompress(gz);pin(typedraw,encoding['raw'])
assert typedraw==(C/'ACTUAL_PROCESS_INPUT.candidate.json').read_bytes()
typed=json.loads(typedraw)
bootstrap=(D/'inputs/candidate-bootstrap.py').read_bytes();configraw=(D/'inputs/candidate-config.json').read_bytes()
assert bootstrap==(C/'ACTUAL_BOOTSTRAP.candidate.py').read_bytes()
assert configraw==(C/'APPROVED_CONFIG.candidate.json').read_bytes()
for name,raw in [('candidate-bootstrap.py',bootstrap),('candidate-config.json',configraw)]:
    sdkraw=(D/'github'/(name+'.GET.original.json')).read_bytes()
    assert json.loads(sdkraw)['structuredContent']['content'].encode()==raw
    getobs.append({'name':name,'body':identity(raw),'actual_GET_SDK':identity(sdkraw),'full_readback_equal':True})
config=json.loads(configraw);reviewboundraw=(C/'REVIEW_BOUND_HOLD_CONFIG.json').read_bytes();reviewbound=json.loads(reviewboundraw)
holdraw=(H/'APPROVED_CONFIG.HOLD.json').read_bytes();hold=json.loads(holdraw)
assert set(config)==set(reviewbound)==set(hold)
assert {k for k in hold if hold[k]!=reviewbound[k]}=={'root_input_review','source_peer_review','waiting_for'}
assert reviewbound['root_input_review']=='94c9d4fa5843806a0ae8e0a08296840c4ad625d9'
assert reviewbound['source_peer_review']=='7dce432cbecd7b349db5e8599a8e1c58a0b7f4bf'
assert reviewbound['waiting_for']==['Root final exact control approval pending.']
assert {k for k in config if config[k]!=reviewbound[k]}=={'status','root_execution_approved'}
assert config['status']=='ROOT_APPROVED_TO_EXECUTE' and config['root_execution_approved'] is True
assert reviewbound['status']=='HOLD_ROOT_EXACT_REVIEW_REQUIRED' and reviewbound['root_execution_approved'] is False
restore=dict(config);restore.update({k:reviewbound[k] for k in ('status','root_execution_approved')})
assert (json.dumps(restore,indent=2,sort_keys=True)+'\n').encode()==reviewboundraw
restore.update({k:hold[k] for k in ('root_input_review','source_peer_review','waiting_for')})
assert (json.dumps(restore,indent=2,sort_keys=True)+'\n').encode()==holdraw
definitions,resolve=pure_data(bootstrap);pins=resolve(definitions['PINS'])
oldbootstrap=(H/'ACTUAL_BOOTSTRAP.HOLD.py').read_bytes();olddefs,oldresolve=pure_data(oldbootstrap);oldpins=oldresolve(olddefs['PINS'])
assert set(pins)==set(oldpins)=={'driver.py','APPROVED_CONFIG.json','NONRUST_PACKET.json','MAINTENANCE_NORMAL.original.json'}
assert {k for k in pins if pins[k]!=oldpins[k]}=={'APPROVED_CONFIG.json'}
assert pins['APPROVED_CONFIG.json']==identity(configraw)
oldline=next(l for l in oldbootstrap.splitlines(keepends=True) if l.startswith(b'PINS = '))
newline=next(l for l in bootstrap.splitlines(keepends=True) if l.startswith(b'PINS = '))
assert bootstrap.count(newline)==1 and bootstrap.replace(newline,oldline,1)==oldbootstrap
original=(P/'inputs/ORIGINAL_9101_BOOTSTRAP.py').read_bytes();inverse=bootstrap
for name in ('BASE','PINS'):
    line=next(l for l in inverse.splitlines(keepends=True) if l.startswith((name+' = ').encode()))
    original_line=next(l for l in original.splitlines(keepends=True) if l.startswith((name+' = ').encode()))
    assert inverse.count(line)==1;inverse=inverse.replace(line,original_line,1)
assert inverse==original
for name in ('check','identity','real_parents','retain'):assert functions(bootstrap)[name][0]==functions(original)[name][0]
assert b'fcntl' not in bootstrap and b'flock' not in bootstrap
oldtyped=json.loads((H/'ACTUAL_PROCESS_INPUT.HOLD.json').read_bytes())
assert set(typed)==set(oldtyped)=={'args','cwd','executable','host','idempotency_key','stdin','timeout_seconds'}
assert {k for k in typed if typed[k]!=oldtyped[k]}=={'args','stdin'}
assert typed['host']=='desktop' and typed['executable']=='/usr/bin/python3' and typed['cwd']=='/home/qian-qi'
assert typed['args']==['-B','-c',bootstrap.decode()] and typed['timeout_seconds']==2100
assert typed['idempotency_key']=='hepta-utility-36fa-provider-coordinator-a489-final-nonrust-format-v1'
stdinraw=typed['stdin'].encode();assert stdinraw==(C/'ACTUAL_STDIN.candidate.json').read_bytes()
stdinenc=next(x for x in manifest['members'] if x['name']=='ACTUAL_STDIN.candidate.json');pin(stdinraw,stdinenc['raw'])
assert len(stdinraw)==751579 and len(typedraw)==757672 and max(len(stdinraw),len(typedraw))<1048576
stdin=json.loads(stdinraw);oldstdin=json.loads(oldtyped['stdin'])
assert set(stdin)=={'format','files'} and stdin['format']=='hepta-final-nonrust-format-bootstrap-v1'
assert set(stdin['files'])==set(pins)
assert {k for k in stdin['files'] if stdin['files'][k]!=oldstdin['files'][k]}=={'APPROVED_CONFIG.json'}
decoded={}
for name,encoded in stdin['files'].items():
    raw=base64.b64decode(encoded,validate=True)
    if name=='NONRUST_PACKET.json':raw=gzip.decompress(raw)
    pin(raw,pins[name]);decoded[name]=raw
assert decoded['APPROVED_CONFIG.json']==configraw
assert decoded['NONRUST_PACKET.json']==(D/'inputs/NONRUST_PACKET.exact.json').read_bytes()
assert decoded['driver.py']==(D/'inputs/driver27.HOLD.py').read_bytes()
assert config['driver']==pins['driver.py'] and config['nonrust_packet']==pins['NONRUST_PACKET.json']
assert config['source_peer_review']=='7dce432cbecd7b349db5e8599a8e1c58a0b7f4bf'
assert (config['preflight_seconds'],config['fmt_seconds'],config['record_seconds'],config['outer_seconds'])==(600,900,300,2100)
assert config['fmt_argv']==['just','fmt','--base','c0f78493f815780f68b9bf5e390a21314d79311f']
assert config['fix_authorized'] is config['test_commands_authorized'] is config['ref_updates_authorized'] is False
report={
 'format':'hepta-final-nonrust-exact-execution-candidate-independent-binding-v1',
 'decision':'NO_CONCRETE_STATIC_BLOCKER_IN_THIS_EXACT_REQUEST; ROOT_DISPATCH_DECISION_REQUIRED',
 'request':identity(typedraw),'request_full_GET_transport_gzip':identity(gz),'stdin':identity(stdinraw),
 'bootstrap':identity(bootstrap),'original_bootstrap':identity(original),'config':identity(configraw),
 'review_bound_HOLD':identity(reviewboundraw),'initial_HOLD':identity(holdraw),
 'review_binding_keys_only':['root_input_review','source_peer_review','waiting_for'],
 'approval_keys_only':['status','root_execution_approved'],
 'two_stage_config_inverse_whole_bytes_equal':True,
 'original_bootstrap_full_inverse_BASE_PINS_only':True,'four_original_helpers_byte_equal':True,
 'from_reviewed_HOLD_bootstrap_only_config_pin_changes':True,
 'request_fields':sorted(typed),'unchanged_request_fields':['host','cwd','executable','idempotency_key','timeout_seconds'],
 'idempotency_key':typed['idempotency_key'],'host':typed['host'],'cwd':typed['cwd'],'executable':typed['executable'],
 'args_shape':['-B','-c','exact 5700-byte bootstrap'],'no_env':True,'outer_seconds':2100,
 'four_fully_decoded_inputs':pins,'only_stdin_config_payload_changed':True,
 'original_input_cap_bytes':1048576,'actual_typed_bytes':len(typedraw),'actual_stdin_bytes':len(stdinraw),
 'strict_packet_expanded_bytes':len(decoded['NONRUST_PACKET.json']),'original_packet_cap_bytes':40000000,
 'unique_EX':'Only original unchanged thin main; neither bootstrap nor staging preholds EX.',
 'required_runtime_order':['memory verify exact four bounded inputs','create-only fixed control directory and full stable file readback','fsync and original execv','thin main sole existing-lock EX','actual complete source/Git/runtime checks','exact four existing100644 replacements','original fmt900','bounded full source/input/same-lock audits and retained result'],
 'source_peer':'7dce432cbecd7b349db5e8599a8e1c58a0b7f4bf',
 'control_HOLD_peer':'0216a7064812580ba6e2eb8db3fbc9ef71f19a8d',
 'control_byte_and_actual_dataflow':'476fc866d87c94c012b4c97796cb3b7218832fd2',
 'independent_full_GETs':getobs,
 'raw_large_request_standalone_GET_claimed':False,
 'qualification':False,'dispatch_authorized_by_this_peer':False,'H_calls':0,'source_or_ref_mutations':0,
 'future_canonical_alignment':'Separate e8d606 HOLD remains unapproved and lacks actual final-format/canonical proofs. This request neither aligns index/HEAD nor moves refs.',
 'unknown_policy':'Retain/reconcile the same exact job/key and actual partial source state. No automatic retry, new identity, rollback/reset, dependency install, fix or tests.'}
result=write('EXACT_REQUEST_REVIEW.json',report)
print(json.dumps({'output':str(D/'EXACT_REQUEST_REVIEW.json'),**result,'request':identity(typedraw),'native_dispatch':False}))
