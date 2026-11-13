from pathlib import Path
import hashlib,json
D=Path('/tmp/hepta-36fa-e2-ipc-independent-peer-v1')
P=Path('/tmp/hepta-36fa-root-product-e2-proposal-v1/ipc-purpose-increment-v1')
B=Path('/tmp/hepta-36fa-root-product-e2-proposal-v1/ipc-layer-v1')
def pin(b):
 return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
p=(P/'SOURCE_PACKET.json').read_bytes()
assert pin(p)['git_blob']=='69d6d5eda401ff59f7e89b1e659f77a431274248'
packet=json.loads(p)
rows=[]
for e in packet['entries']:
 before=(P/'before'/e['path']).read_bytes();after=(P/'after'/e['path']).read_bytes()
 assert before==(B/'after'/e['path']).read_bytes()
 assert pin(before)==e['before'] and pin(after)==e['after']
 assert before==e['before_utf8'].encode() and after==e['after_utf8'].encode()
 s=after.decode()
 if e['path'].endswith('circuit_task_remote_wire.rs'):
  enum='#[derive(Clone, Copy, Debug, Eq, PartialEq)]\npub(super) enum LanePurpose { Task, Loan }\n\n'
  assert s.count(enum)==1
  s=s.replace(enum,'').replace('purpose: LanePurpose','task_lane: bool')
  s=s.replace('            purpose, budget })','            task_lane, budget })')
  assert s.count('(self.purpose == LanePurpose::Task)')==2
  s=s.replace('(self.purpose == LanePurpose::Task)','self.task_lane')
 else:
  assert s.count('LanePurpose::Task')==s.count('LanePurpose::Loan')==1
  s=s.replace('Lane, LanePurpose, Operation','Lane, Operation')
  s=s.replace('LanePurpose::Task','true').replace('LanePurpose::Loan','false')
 assert s.encode()==before
 rows.append({'path':e['path'],'before':pin(before),'after':pin(after),'whole_file_inverse_equal':True})
assert len(rows)==3
report={'scope':'Exact private LanePurpose successor only; no project code execution.',
 'source_packet':pin(p),'rows':rows,'four_call_sites_exact_direction_preserved':True,
 'wire_domain_nonce_sequence_operation_values_budget_deadline_unchanged':True,
 'root_h_rust_formatter_tests_qa_collector_called':False}
body=(json.dumps(report,indent=2,sort_keys=True)+'\n').encode()
(D/'PURPOSE_INCREMENT_REVIEW.json').write_bytes(body)
print(pin(body))
