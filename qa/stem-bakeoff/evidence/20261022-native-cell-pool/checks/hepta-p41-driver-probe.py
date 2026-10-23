import hashlib,json,math,struct,subprocess,sys
from pathlib import Path
sys.path.insert(0,'/tmp/hepta-p41-pool/qa/stem-bakeoff')
import native_task_head_pool as pool
root=Path('/tmp/hepta-p41-driver-probe')
root.mkdir()
sha=lambda x:hashlib.sha256(x).hexdigest()
identity=dict(encoder_sha256='1'*64,checkpoint_revision='3'*40,preprocess_sha256='2'*64,
              generation=1,scope_id='unit-execution',purpose='research',revocation_epoch=0)
weights=[0.0]*36
weights[24],weights[29]=1.0,-1.0
raw=struct.pack('<36f',*weights)
manifest=dict(schema='hepta.native-task-head.v1',numeric_profile='f32-io-f64-accum-gelu-erf-v1',
 state_contract='zero_state_only',mode='SHADOW_ONLY',authority='DENY_ALL',
 feature_layout='concat-text-image-product-absolute-difference-cosine-v1',feature_identity=identity,
 width=5,state_width=8,adapter_rank=1,task_count=2,temperature=0.25,confidence_threshold=0.7,
 required_present_mask=3,source_head_manifest_sha256='4'*64,source_head_weights_sha256='5'*64,
 weights_sha256=sha(raw),weights_bytes=len(raw))
mf=pool.canonical(manifest)
(root/'manifest.json').write_bytes(mf)
(root/'weights.f32le').write_bytes(raw)
rows=[dict(identity=identity,features=[0.5,0.25,0.125,0.25,0.8],present_mask=3,
           source_record_digest=sha(str(i).encode())) for i in range(256)]
requests=b''.join(pool.canonical(row) for row in rows)
(root/'requests.jsonl').write_bytes(requests)
binary='/tmp/hepta-p40-target/release/examples/native_task_head_pool'
base=['/usr/bin/prlimit',f'--as={pool.MEMORY_BYTES}:{pool.MEMORY_BYTES}',
      '--fsize=524288:524288','--cpu=90:90','--',binary,
      str(root/'manifest.json'),str(root/'weights.f32le'),sha(mf),str(root/'requests.jsonl'),sha(requests)]
reference=[dict(source_record_digest=row['source_record_digest'],prediction=dict(
 task_logits=[0.5,-0.5],task_probabilities=[1/(1+math.exp(-4)),1/(1+math.exp(4))],
 predicted_class=0,accepted=True,gate=0.5,mode='SHADOW_ONLY',authority='DENY_ALL')) for row in rows]
artifact=dict(manifest_sha256=sha(mf),weights_sha256=sha(raw),weights_bytes=len(raw))
outcomes={}
for cells in (1,32):
 actual=pool.execute_child(base+[str(cells)],root/f'{cells}.json',root/f'{cells}.stderr',10)
 result=pool.summarize(actual,cells,artifact,sha(requests),reference)
 outcomes[f'actual_pool_{cells}']={'status':'PASS','private_bytes':result['private_weights_payload_bytes']}
def reject(name,command):
 result=subprocess.run(command,capture_output=True,timeout=10)
 assert result.returncode!=0 and not result.stdout
 outcomes[name]={'status':'REJECTED','returncode':result.returncode,'stderr':result.stderr.decode()[:400]}
reject('unsupported_count',base+['2'])
bad=base.copy();bad[-1]='f'*64
reject('request_digest',bad+['1'])
bad=base.copy();bad[-3]='f'*64
reject('manifest_digest',bad+['1'])
reject('missing_memory_limit',[binary,*base[6:],'1'])
for kind in ('missing_modality','wrong_identity'):
 changed=json.loads(json.dumps(rows))
 if kind=='missing_modality':changed[0]['present_mask']=1
 else:changed[0]['identity']['encoder_sha256']='f'*64
 payload=b''.join(pool.canonical(row) for row in changed)
 path=root/(kind+'.jsonl');path.write_bytes(payload)
 bad=base.copy();bad[-2]=str(path);bad[-1]=sha(payload)
 reject(kind,bad+['1'])
receipt={'schema':'hepta.p41-driver-execution-probe.v1','status':'PASS','semantic_quality_evidence':False,
 'native_binary_sha256':sha(Path(binary).read_bytes()),'probe_source_sha256':sha(Path(__file__).read_bytes()),
 'outcomes':outcomes}
(root/'receipt.json').write_bytes(pool.canonical(receipt))
print(json.dumps(receipt,sort_keys=True))
