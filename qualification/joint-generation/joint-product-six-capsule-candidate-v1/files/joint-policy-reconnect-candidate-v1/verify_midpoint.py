"""No-model reconstruction. Shares public parsers, not producer assertions."""
import json
from common import *
from content_input import convert
from persistence import binding
from route_contract import POLICY
from attempt import Attempt,parts

def verify(ready,expected_root):
 artifact_payload,artifact,raw=expected()
 if ready['freeze']!=FREEZE or ready['root_instance']!=expected_root or inst(SESSION)!=expected_root or ready['lock_instance']!=inst(SESSION/'.hepta-writer.lock'):raise ValueError('root/lock/freeze binding')
 if (FOLDER/'REQUEST.json').read_bytes()!=raw or (FOLDER/'ARTIFACT.json').read_bytes()!=canonical(artifact_payload):raise ValueError('independent exact request/artifact')
 bound=convert(raw,expected_artifact_sha256=artifact,sequence=POLICY,now_ns=2);identity=binding(raw,POLICY,bound.run_spec)
 namespace=sha(canonical({'objective_id':bound.run_spec.objective_id,'run_id':bound.run_spec.run_id}));record=ready['record']
 if type(record)is not dict or set(record)!={'namespace','name','bytes','sha256'}or record['namespace']!=namespace or record['name']!='piece-01-ack.json':raise ValueError('exact derived midpoint slot')
 path=SESSION/namespace/record['name']
 if file_ref(path)!={k:record[k]for k in ('bytes','sha256')}:raise ValueError('external record hash/bytes')
 if (SESSION/namespace/'claim.json').read_bytes()!=canonical(identity):raise ValueError('claim identity')
 a=Attempt.load(path,raw_request=raw,sequence=POLICY,expected_spec=bound.run_spec,expected_file_sha256=record['sha256'],now=2)
 route=json.loads(read('old_route'));route['artifact_sha256']=artifact;route['request_identity_sha256']=sha(canonical(identity));wire=read('old_wire')
 chunks=parts(wire);prefix={m:b''for m in ('text','image')}
 for mode,b in chunks[:2]:prefix[mode]+=b
 if a.identity!=identity or a.route!=route or a.wire!=wire or a.phase!='generated'or a.next_index!=2 or a.pending_chunk is not None:raise ValueError('complete route/midpoint state')
 if a.session.spent!={'controller':1,'generator':1,'output_bytes':8227}or any(a.session.prefix(m)!=prefix[m]for m in prefix):raise ValueError('prefix/charged work')
 if sha(canonical(route))!=ready['route_sha256']or sha(wire)!=ready['wire_sha256']or ready['artifact_sha256']!=artifact:raise ValueError('READY bindings')
 if len(chunks)!=6 or any((SESSION/namespace/n).exists()for n in ['piece-02-intent.json','cancel-intent.json','cancelled.json']):raise ValueError('midpoint no future effect')
 return {'schema':'local-policy-midpoint-handoff-v1','freeze':FREEZE,'producer_pid':ready['pid'],'record':record,'request_ref':file_ref(FOLDER/'REQUEST.json'),'artifact_sha256':artifact,'route_sha256':sha(canonical(route)),'wire_sha256':sha(wire),'root_instance':expected_root,'lock_instance':ready['lock_instance'],'namespace':namespace,'known_prefix_bytes':8227,'known_total_pieces':6,'verification':'full exact request/composite artifact/route/wire/session reconstruction; no model','clock_scope':'literal now2/deadline100, not real wall deadline or authority'}
