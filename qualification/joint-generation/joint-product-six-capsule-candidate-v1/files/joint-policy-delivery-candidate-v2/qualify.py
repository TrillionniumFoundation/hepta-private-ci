import sys,os,json,hashlib,fcntl,copy,io
from pathlib import Path
ROOT=Path(__file__).resolve().parent;WS=ROOT.parent;OUT=ROOT/'RUN_ONCE'
sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
lock=open(sys.argv[1],'rb');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
import numpy as np
from policy_backend import PolicyBackend,pixel_digest
from route_contract import canonical,sha,POLICY
from guarded_delivery import GuardedDelivery
from attempt import parts
from contracts import ContractError
from content_input import convert
from cost import Budget
from multimodal_contract import SCHEMA
cfg=json.loads((ROOT/'INPUTS.json').read_bytes());checks=[];refusals=[]
def check(name,ok):
 if not ok:raise AssertionError(name)
 checks.append(name)
def read(k):
 r=cfg['inputs'][k];b=(WS/r['path']).read_bytes()
 if len(b)!=r['bytes']or sha(b)!=r['sha256']:raise ValueError('input pin '+k)
 return b
def arr(k):
 with np.load(io.BytesIO(read(k)),allow_pickle=False)as z:return {n:z[n].copy()for n in z.files}
def write(name,value,raw=False):
 b=value if raw else canonical(value);p=OUT/name
 with p.open('xb')as f:f.write(b);f.flush();os.fsync(f.fileno())
 return {'name':name,'bytes':len(b),'sha256':sha(b)}
def inv(root):return {str(p.relative_to(root)):{'bytes':p.stat().st_size,'sha256':sha(p.read_bytes())}for p in sorted(root.rglob('*'))if p.is_file()}
def no(name,fn):
 try:fn()
 except (ValueError,ContractError)as e:refusals.append({'name':name,'error':str(e)});return
 raise AssertionError('expected refusal '+name)
for k in cfg['inputs']:read(k)
state=json.loads(read('state'));complete=json.loads(read('complete'))
check('completed_export_pin',state['stage']=='export'and state['index']==6 and complete['state_ref']['sha256']==sha(read('state'))and complete['identity']==state['identity'])
s=state['state'];ca=arr('content');aa=arr('actor');fixture=arr('fixture')
check('state_payload_refs',all(s['refs'][name]['sha256']==cfg['inputs'][key]['sha256']for name,key in [('content','content'),('actor_full','actor'),('fixture','fixture')]))
backend=PolicyBackend(ca,aa,sha((ROOT/'FREEZE.json').read_bytes()),{'completed_export_sha256':sha(read('complete')),'content_sha256':cfg['inputs']['content']['sha256'],'actor_full_sha256':cfg['inputs']['actor']['sha256']})
check('paired_model_digests',backend.content.digest()==s['content_digest']and backend.content.optimizer_digest()==s['content_optimizer_digest']and backend.actor.digest()==s['actor_digests']['actor_full']and backend.actor.optimizer_digest()==s['actor_optimizer_digests']['actor_full'])
before=canonical(backend.checkpoint_payload());artifact=sha(before);write('PAIRED_ARTIFACT.json',before,True)
budget=Budget(OUT,total_ns=5_000_000_000,byte_cap=16*2**20,rss_cap=256*2**20)
root=OUT/'delivery';root.mkdir();d=GuardedDelivery(backend,artifact,root,budget);cases=[]
for row,mode in [(0,'success'),(5,'cancel')]:
 rgb=np.repeat(fixture['z'][row].astype(np.float32).reshape(28,28,1),3,axis=2)
 value={'schema':SCHEMA,'sync_tolerance_ns':0,'objective_id':'synthetic-policy-delivery','run_id':'row-'+str(row),'artifact_sha256':artifact,'budget':{'compute_units':2,'input_bytes':10000,'output_bytes':50000},'deadline_ns':100,'decoding':{'mode':'greedy','seed':0},'outputs':['text','image'],'streams':[{'stream_id':'image','modality':'image','timing':{'clock_id':'literal','sync_group':'one','start_ns':1,'end_ns':2},'payload':{'dtype':'float32','color_space':'RGB','pixels':rgb.tolist()}}]}
 raw=canonical(value);write(mode+'-REQUEST.json',raw,True);bound=convert(raw,expected_artifact_sha256=artifact,sequence=POLICY,now_ns=2)
 check(mode+'_actual_converted_input',np.array_equal(bound.pixels,fixture['z'][row:row+1].astype(np.float32).astype(np.float64))and not bound.pixels.flags.writeable)
 if mode=='success':
  pre=inv(root);w=copy.deepcopy(value);w['artifact_sha256']='b'*64
  no('wrong_artifact_before_inference',lambda:d.start(canonical(w),POLICY,now=2))
  no('old_literal_sequence_not_policy',lambda:d.start(raw,'J',now=2))
  check('preflight_refusals_no_write_or_model',inv(root)==pre and backend.work['serving_calls']==0)
 reference,wires=backend.reference(bound.pixels)
 write(mode+'-REFERENCE.json',reference)
 for seq,wire in wires.items():write(mode+'-REF-'+seq+'.json',wire,True)
 a,g=d.start(raw,POLICY,now=2);route=copy.deepcopy(a.route)
 check(mode+'_feature_parity',np.max(np.abs(np.asarray(route['features'])-reference['features']))<=1e-12)
 check(mode+'_actor_value_parity',np.max(np.abs(np.asarray(route['actor_values'])-reference['actor_values']))<=1e-12)
 check(mode+'_exact_choice_and_wire',route['selected_index']==reference['selected_index']and a.wire==wires[route['sequence']])
 check(mode+'_request_route_wire_bound',route['input_pixels_sha256']==pixel_digest(bound.pixels)and route['request_identity_sha256']==sha(canonical(a.identity))and route['wire_sha256']==sha(a.wire))
 write(mode+'-WIRE.json',a.wire,True);write(mode+'-ROUTE.json',route)
 if mode=='success':
  recordfile=root/g['namespace']/g['name'];bad=json.loads(recordfile.read_bytes());bad['payload']['route']['request_identity_sha256']='0'*64;bad['sha256']=sha(canonical(bad['payload']));badraw=canonical(bad);badpath=root/g['namespace']/'wrong-route.json';badpath.write_bytes(badraw)
  badref={**g,'name':badpath.name,'bytes':len(badraw),'sha256':sha(badraw)};pre=inv(root);calls=copy.deepcopy(backend.work)
  no('tampered_route_hash_rebound_still_rejected',lambda:d.restore(badref,raw,POLICY,now=2))
  altered=copy.deepcopy(value);altered['streams'][0]['payload']['pixels'][0][0]=[0.,0.,0.]
  no('different_raw_request_restore_refused',lambda:d.restore(g,canonical(altered),POLICY,now=2))
  check('restore_refusals_no_effect',pre==inv(root)and calls==backend.work)
  a,record=d.publish(a,g,now=2)
  check('success_complete',a.phase=='complete'and a.next_index==len(parts(a.wire)) and a.route==route)
 else:
  a,record=d.publish(a,g,now=2,cancel_after=2)
  check('cancel_keeps_partial_prefix',a.phase=='cancelled'and a.next_index==2 and len(a.session.prefix('text'))>0 and len(a.session.prefix('image'))==8192 and a.route==route)
  frontier=root/record['namespace']/'piece-01-ack.json';fr={'namespace':record['namespace'],'name':frontier.name,'bytes':frontier.stat().st_size,'sha256':sha(frontier.read_bytes())}
  d.close();d=GuardedDelivery(backend,artifact,root,budget);old,rr=d.restore(fr,raw,POLICY,now=2);pre=inv(root);calls=copy.deepcopy(backend.work)
  no('cancelled_stale_frontier_refused',lambda:d.publish(old,rr,now=2))
  check('cancel_refusal_no_output_or_model',pre==inv(root)and calls==backend.work and not(root/record['namespace']/'piece-02-intent.json').exists())
 text=a.session.prefix('text');image=a.session.prefix('image');write(mode+'-text.part',text,True);write(mode+'-image.part',image,True)
 cases.append({'row':row,'mode':mode,'generated':g,'terminal':record,'route':route,'spent':a.session.spent,'phase':a.phase,'text_bytes':len(text),'image_bytes':len(image)})
d.close()
for name,model,key in [('CONTENT_AFTER.npz',backend.content,'content'),('ACTOR_AFTER.npz',backend.actor,'actor')]:
 b=io.BytesIO();np.savez(b,**model.to_arrays(include_optimizer=True));write(name,b.getvalue(),True)
 check(name+'_arrays_same',all(np.array_equal(v,(ca if key=='content'else aa)[k])for k,v in model.to_arrays(include_optimizer=True).items()))
check('paired_full_inventory_unchanged',canonical(backend.checkpoint_payload())==before)
w=backend.work
check('exact_work',w['allocation_restores']==2 and w['fresh_models']==w['optimizer_steps']==0 and w['serving_calls']==w['serving_prefix_J']==w['serving_actor_predictions']==w['serving_encoded_rows']==2 and sum(w['serving_final_updates'].values())==2 and w['reference_calls']==w['reference_actor_predictions']==2 and w['reference_candidate_rows']==w['reference_encoded_rows']==6)
for k in cfg['inputs']:read(k)
check('all_original_inputs_terminal_unchanged',True)
write('RESULT.json',{'status':'PASS_CONDITIONAL_POLICY_LOCAL_TEXT_RGB','checks':checks,'refusals':refusals,'cases':cases,'work':w,'budget_prefix':budget.snapshot(),'artifact_sha256':artifact,'source_freeze_sha256':sha((ROOT/'FREEZE.json').read_bytes()),'scope':'Two known synthetic rows0/5. Fresh singleton float32-converted references fully charged. Class-word text/grayscale RGB, not speech/freeform language/scientific gain. Same-process lease handover not OS crash qualification. Unknown actual generation not newly injected. Local cooperative authority only.'})
print(json.dumps({'status':'PASS','checks':len(checks),'refusals':len(refusals)}))
