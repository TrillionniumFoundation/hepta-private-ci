"""No-model reconstruction. Shares public parsers, not producer assertions."""
import json
from common import *
from content_input import convert
from persistence import binding
from route_contract import POLICY
from attempt import Attempt,parts

def verify(ready,expected_root,clock):
 artifact_payload,artifact,raw=expected()
 if ready['freeze']!=FREEZE or ready['root_instance']!=expected_root or inst(SESSION)!=expected_root or ready['lock_instance']!=inst(SESSION/'.hepta-writer.lock'):raise ValueError('root/lock/freeze binding')
 if (FOLDER/'REQUEST.json').read_bytes()!=raw or (FOLDER/'ARTIFACT.json').read_bytes()!=canonical(artifact_payload):raise ValueError('independent exact request/artifact')
 bound=convert(raw,expected_artifact_sha256=artifact,sequence=POLICY,now_ns=clock.live());identity=binding(raw,POLICY,bound.run_spec)
 namespace=sha(canonical({'objective_id':bound.run_spec.objective_id,'run_id':bound.run_spec.run_id}));record=ready['record']
 if type(record)is not dict or set(record)!={'namespace','name','bytes','sha256'}or record['namespace']!=namespace or record['name']!='piece-01-ack.json':raise ValueError('exact derived midpoint slot')
 path=SESSION/namespace/record['name']
 if file_ref(path)!={k:record[k]for k in ('bytes','sha256')}:raise ValueError('external record hash/bytes')
 if (SESSION/namespace/'claim.json').read_bytes()!=canonical(identity):raise ValueError('claim identity')
 a=Attempt.load(path,raw_request=raw,sequence=POLICY,expected_spec=bound.run_spec,expected_file_sha256=record['sha256'],now=clock.live())
 route=json.loads(read('old_route'));route['artifact_sha256']=artifact;route['request_identity_sha256']=sha(canonical(identity));wire=read('old_wire')
 chunks=parts(wire);prefix={m:b''for m in ('text','image')}
 for mode,b in chunks[:2]:prefix[mode]+=b
 if a.identity!=identity or a.route!=route or a.wire!=wire or a.phase!='generated'or a.next_index!=2 or a.pending_chunk is not None:raise ValueError('complete route/midpoint state')
 if a.session.spent!={'controller':1,'generator':1,'output_bytes':8227}or any(a.session.prefix(m)!=prefix[m]for m in prefix):raise ValueError('prefix/charged work')
 if sha(canonical(route))!=ready['route_sha256']or sha(wire)!=ready['wire_sha256']or ready['artifact_sha256']!=artifact:raise ValueError('READY bindings')
 if len(chunks)!=6 or any((SESSION/namespace/n).exists()for n in ['piece-02-intent.json','cancel-intent.json','cancelled.json']):raise ValueError('midpoint no future effect')
 return {'schema':'local-policy-midpoint-handoff-v1','freeze':FREEZE,'producer_pid':ready['pid'],'record':record,'request_ref':file_ref(FOLDER/'REQUEST.json'),'artifact_sha256':artifact,'route_sha256':sha(canonical(route)),'wire_sha256':sha(wire),'root_instance':expected_root,'lock_instance':ready['lock_instance'],'namespace':namespace,'known_prefix_bytes':8227,'known_total_pieces':6,'verification':'full exact request/composite artifact/route/wire/session reconstruction; no model','clock_scope':'local OS monotonic, external same-supervisor epoch, not owner authentication'}

def verify_ack(packet,ready,clock):
 if type(packet)is not dict or set(packet)!={'ack','ack_record','final_record'}:raise ValueError('ACK packet schema')
 ack=packet['ack'];expected_keys={'schema','manifest_sha256','command_sha256','observed_ns','intent_return_ns','ack_pre_send_ns','observed_record','intent_record','final_record'}
 if type(ack)is not dict or set(ack)!=expected_keys or ack['schema']!='local-cancel-ack-v1' or ack['manifest_sha256']!=clock.pin or ack['command_sha256']!=sha(canonical(clock.command())):raise ValueError('ACK identity')
 for key in ('observed_ns','intent_return_ns','ack_pre_send_ns'):
  if type(ack[key])is not int:raise ValueError('ACK strict time')
 if not clock.manifest['origin_ns']<=ack['observed_ns']<=ack['intent_return_ns']<=ack['ack_pre_send_ns']<=clock.observe():raise ValueError('ACK time order')
 ns=ready['record']['namespace']
 if inst(SESSION)!=ready['root_instance']or inst(SESSION/'.hepta-writer.lock')!=ready['lock_instance']:raise ValueError('ACK inode')
 values={}
 for k,name in [('observed_record','control-observed.json'),('intent_record','cancel-intent.json'),('final_record','cancelled.json'),('ack_record','control-ack.json')]:
  ref=packet[k]if k=='ack_record'else ack[k]
  if type(ref)is not dict or set(ref)!={'namespace','name','bytes','sha256'} or ref['namespace']!=ns or ref['name']!=name or type(ref['bytes'])is not int:raise ValueError('ACK fixed ref')
  path=SESSION/ns/name
  if file_ref(path)!={x:ref[x]for x in ('bytes','sha256')}:raise ValueError('ACK ref mismatch')
  values[k]=json.loads(path.read_bytes())
 if values['ack_record']!=ack or packet['final_record']!=ack['final_record']:raise ValueError('ACK persisted bytes')
 payload,artifact,raw=expected();bound=convert(raw,expected_artifact_sha256=artifact,sequence=POLICY,now_ns=clock.live());identity=binding(raw,POLICY,bound.run_spec)
 ob=values['observed_record']
 if ob!={'identity':identity,'manifest_sha256':clock.pin,'message':clock.command(),'observed_ns':ack['observed_ns'],'prior_record':ready['record']}:raise ValueError('control observation binding')
 states=[]
 for k in ('intent_record','final_record'):
  ref=ack[k];a=Attempt.load(SESSION/ns/ref['name'],raw_request=raw,sequence=POLICY,expected_spec=bound.run_spec,expected_file_sha256=ref['sha256'],now=clock.live());states.append(a)
 first,last=states
 expected_route=json.loads(read('old_route'));expected_route['artifact_sha256']=artifact;expected_route['request_identity_sha256']=sha(canonical(identity))
 if first.route!=expected_route or last.route!=expected_route or sha(canonical(expected_route))!=ready['route_sha256']or sha(first.wire)!=ready['wire_sha256']:raise ValueError('cancel exact midpoint route/wire binding')
 if first.phase!='generated'or last.phase!='cancelled'or first.next_index!=2 or last.next_index!=2 or first.wire!=read('old_wire')or last.wire!=first.wire or first.route!=last.route:raise ValueError('cancel state')
 if any(a.session.spent!={'controller':1,'generator':1,'output_bytes':8227}or len(a.session.prefix('text'))!=35 or len(a.session.prefix('image'))!=8192 for a in states):raise ValueError('cancel charges/prefix')
 if (SESSION/ns/'piece-02-intent.json').exists():raise ValueError('cancel output advanced')
 return {'packet':packet,'verified_ns':clock.observe(),'root_instance':inst(SESSION),'lock_instance':inst(SESSION/'.hepta-writer.lock'),'known_prefix_bytes':8227,'phase':'cancelled'}
