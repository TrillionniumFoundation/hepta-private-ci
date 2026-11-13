from pathlib import Path,PurePosixPath
import hashlib,json,base64,gzip
D=Path('/tmp/hepta-36fa-source65a-transported-originals-hold-v1')
A=Path('/tmp/hepta-36fa-source65a-path-provenance-independent-review-v1')
O=Path('/tmp/hepta-36fa-source65a-transport-data-independent-review-v1')
O.mkdir(mode=0o700,exist_ok=True)
def pin(b):
 return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def pairs(p):
 r={}
 for k,v in p:
  if k in r:raise ValueError('duplicate JSON key: '+k)
  r[k]=v
 return r
def parse(b):return json.loads(b,object_pairs_hook=pairs)
def onlypin(v):return {k:v[k] for k in ('bytes','sha256','git_blob')}
def put(name,obj):
 b=(json.dumps(obj,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
 with (O/name).open('xb') as f:f.write(b)
 return pin(b)
manifest_raw=(D/'TRANSPORT_MANIFEST.HOLD.json').read_bytes()
m=parse(manifest_raw);s=parse((D/'STAGING_WRITE_MANIFEST.HOLD.json').read_bytes())
original=parse((A/'CAPTURED_PATH_MATRIX.json').read_bytes())['rows']
known={r['path']:{'pin':r['pin'],'consumers':r['consumers'],'evidence':r['historical_path_evidence']} for r in original}
assert len(known)==len(original)==54
oldenv='/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/MAINTENANCE_STARTED.original.json'
known[oldenv]={'pin':{'bytes':1154,'git_blob':'69a3d38ff1cf800813f1fbf1f30bca224157f223','sha256':'f9372b818186526929ae25be698d108a4fee17d6612a18f36b8e950172c02ce1'},'consumers':['V5.environment_preflight.ENVIRONMENT_FILE'],'evidence':'content_pin_known_no_original_path_read_in_finite_input_set'}
assert len(m['rows'])==m['historical_original_count']==55
assert {r['original_path'] for r in m['rows']}==set(known)
assert len({r['role'] for r in m['rows']})==len({r['transport_path'] for r in m['rows']})==55
assert m['control']=='/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1'
assert m['source_control']=='/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-v2'
assert m['root_execution_approved'] is False and m['qualification'] is False
for r in m['rows']:
 original=known[r['original_path']]
 assert r['pin']==original['pin'] and r['original_consumers']==original['consumers'] and r['original_path_evidence']==original['evidence']
 assert r['transport_path']==m['control']+'/originals/'+r['role']+'.original'
 assert '..' not in PurePosixPath(r['transport_path']).parts
 assert r['original_path']!=r['transport_path']
assert sum(r['pin']['bytes'] for r in m['rows'])==m['raw_original_bytes']==7976106
assert s['history_manifest']==pin(manifest_raw)
assert s['root_execution_approved'] is False and s['qualification'] is False and s['automatic_retry'] is False
assert len(s['writes'])==17
offset=0;chunks=[];writes=[]
for seq,row in enumerate(s['writes'],1):
 assert row['sequence']==seq and row['decoded_offset']==offset
 raw=Path(row['request']['path']).read_bytes();assert pin(raw)==onlypin(row['request'])
 req=parse(raw);assert set(req)=={'host','path','data_base64','expected_version'}
 assert req['host']=='desktop' and req['expected_version']=='absent'
 path=m['control']+'.payload.json.gz.part-'+str(seq).zfill(3)
 assert req['path']==row['native_path']==path
 assert str(PurePosixPath(path).parent)=='/home/qian-qi/hepta-utility-36fa-evidence'
 encoded=Path(row['encoded_part']['path']).read_bytes();assert pin(encoded)==onlypin(row['encoded_part'])
 assert encoded==(req['data_base64']+'\n').encode()
 body=base64.b64decode(req['data_base64'],validate=True);assert pin(body)==row['decoded_pin']
 assert len(raw)<=1048576 and len(body)<=307200 and len(encoded)<=512000
 assert seq==17 or len(body)==307200
 writes.append({'sequence':seq,'request':pin(raw),'decoded':pin(body),'native_path':path,'expected_version':'absent'})
 chunks.append(body);offset+=len(body)
gz=b''.join(chunks);assert pin(gz)==s['gzip']
raw=gzip.decompress(gz);assert pin(raw)==s['packet']
packet=parse(raw)
assert set(packet)=={'files','format','manifest'} and packet['manifest']==pin(manifest_raw)
assert len(packet['files'])==55
expected={r['role']:r for r in m['rows']}
assert {r['role'] for r in packet['files']}==set(expected)
ledger=parse((D/'ORIGINAL_RECOVERY_LEDGER.json').read_bytes());assert isinstance(ledger,list) and len(ledger)==55
recover={r['role']:r for r in ledger};assert set(recover)==set(expected)
identities=set();body_rows=[]
for row in packet['files']:
 assert set(row)=={'role','data_base64'}
 body=base64.b64decode(row['data_base64'],validate=True)
 role=row['role'];exp=expected[role]
 assert pin(body)==exp['pin']
 local=D/'originals'/(role+'.original');assert local.read_bytes()==body
 rec=recover[role];assert rec['retained']['path']==str(local) and onlypin(rec['retained'])==pin(body)
 identities.add(pin(body)['git_blob'])
 body_rows.append({'role':role,'original_path':exp['original_path'],'transport_path':exp['transport_path'],'pin':pin(body),'capture_evidence':exp['original_path_evidence'],'producer_job_id':exp['producer_job_id']})
assert len(identities)==50
report={
 'format':'hepta-source65a-transport-data-independent-review-v1',
 'status':'FIXED_DATA_AND_REQUEST_BYTES_RECONCILED; SUCCESSOR_RUNTIME_CODE_NOT_REVIEWED_OR_APPROVED',
 'inputs':{'manifest':pin(manifest_raw),'write_manifest':pin((D/'STAGING_WRITE_MANIFEST.HOLD.json').read_bytes()),'matrix':pin((A/'CAPTURED_PATH_MATRIX.json').read_bytes()),'additional_v5_record':pin((A/'ORIGINAL_V5_HISTORY_ADDENDUM.json').read_bytes())},
 'closed_set':{'roles':55,'distinct_bodies':50,'raw_original_bytes':7976106,'matrix_54_paths_and_one_immutable_v5_history_only':True,'original_paths_pins_consumers_and_capture_classifications_unchanged':True,'no_new_live_subject_in_map':True,'present_original_path_availability':'Unknown'},
 'transport':{'gzip':pin(gz),'packet':pin(raw),'write_count':17,'max_typed_bytes':max(r['request']['bytes'] for r in writes),'max_decoded_bytes':max(r['decoded']['bytes'] for r in writes),'typed_limit':1048576,'part_evidence_limit':512000,'writes':writes},
 'complete_originals':body_rows,
 'remaining_runtime_conditions':['The future h successor may replace exactly the four fixed historical read call sites; current m V5 and all live source/Git/index/metadata/ownership/tools/materials/environment/target/coordination-lock checks remain original.','The closed data mapping itself does not prove historical receipt reads are selected only for historical roles at runtime; the exact consumer code still needs review.','Absent-only typed writes, parent/directory state, create-only extraction, strict manifest pin and every transported original full readback must be checked by separately reviewed staging/launcher controls; none has run.','No old-path aliases, overwrite, source changes, restored failure claims, generic missing-path fallback, runtime callback/monkeypatch or unbounded retry is permitted.','Historical source, Git and metadata snapshot bytes are evidence receipts only; they do not substitute for current live reads.','The manifest still states HOLD/qualification false. Any executing request needs separate exact Root approval.'],
 'execution':{'H_calls':0,'native_probes':0,'source_ref_writes':0,'Git_writes':0,'project_code_or_tests':0,'author_preparation_script_executed':False},
 'local_inspection_error':{'kind':'read-only summary script assumed all JSON roots were dictionaries','error':"AttributeError: 'list' object has no attribute 'items'",'file':'ORIGINAL_RECOVERY_LEDGER.json','correction':'Full independent check requires the actual list schema explicitly; no input source or control changed.','classification':'local reviewer inspection only, not source or H failure'},
 'durability':'This report has a local computed identity only; no Git object was created by this reviewer.'
}
print(json.dumps({'path':str(O/'REVIEW.json'),**put('REVIEW.json',report)}))
