"""Real local CPU generator adapter; no external owner, grant or delivery service.

Only a fixed trusted output root is claimed. Different roots are NOT globally
deduplicated. Immutable deterministic slots block rolling an older state forward.
"""
import json,time,os
from pathlib import Path
from contracts import ContractError,digest
from content_input import convert,unique
from persistence import canonical,sha
from attempt import OutputBudgetExceeded,Attempt,parts
from live_control import available
from control_channel import FrameReader
from common import FREEZE,inst
class KnownOutputBudgetRejection(ContractError):
 def __init__(self,record):self.record=record;super().__init__('known generated result rejected by output budget')

class UncertainEffect(ContractError):
 def __init__(self,message,record):super().__init__(message);self.record=record
class BeforeGeneratorFailure(ContractError):
 def __init__(self,record):super().__init__('injected before generator');self.record=record
class GuardedDelivery:
 def __init__(self,backend,artifact,root,budget,clock,reader):
  self.clock=clock;self.reader=reader;self.control_ack=None;self.command_seen=None
  self.backend=backend;self.artifact=artifact;self.root=Path(root);self.budget=budget;self.blocked=set()
  self.work={'start_requests':0,'generator_attempts':0,'generated_wire_bytes':0,'generated_wire_sha256':[],'published_local_bytes':0,'unacknowledged_piece_bytes':0,'known_pre_generator_failures':0}
  self._assert_backend_identity()
 def _assert_backend_identity(self):
  self.budget.check(quote_ns=250_000_000,tail_ns=500_000_000,extra_bytes=65536)
  try:actual=sha(canonical(self.backend.checkpoint_payload()))
  except Exception as e:raise ContractError('backend checkpoint identity unavailable')from e
  if actual!=self.artifact:raise ContractError('backend full model/Adam artifact identity mismatch')
  return actual
 def _spec(self,raw,sequence,now):return convert(raw,expected_artifact_sha256=self.artifact,sequence=sequence,now_ns=now).run_spec
 def _namespace(self,spec):return sha(canonical({'objective_id':spec.objective_id,'run_id':spec.run_id}))
 def _save(self,a,name,now):
  now=self.clock.observe()
  ns=self._namespace(a.session.spec);path=self.root/ns/(name+'.json')
  payload_bytes=len(canonical(a.snapshot(now)))
  self.budget.check(quote_ns=250_000_000,tail_ns=500_000_000,extra_bytes=2*(payload_bytes+128)+65536)
  try:r=a.save(path,observed_ns=now)
  except FileExistsError as e:raise ContractError('immutable journal slot already exists; no replay')from e
  return {'namespace':ns,'name':path.name,'sha256':r['sha256'],'bytes':r['bytes']}
 def _path(self,record,spec):
  ns=self._namespace(spec)
  if type(record)is not dict or set(record)!={'namespace','name','sha256','bytes'}or record['namespace']!=ns or type(record['name'])is not str or Path(record['name']).name!=record['name']or type(record['bytes'])is not int or not 0<record['bytes']<=2*2**20:raise ContractError('local record binding')
  path=self.root/ns/record['name']
  if not path.is_file()or path.stat().st_size!=record['bytes']or sha(path.read_bytes())!=record['sha256']:raise ContractError('local record integrity')
  return path
 def start(self,raw,sequence,*,fault=None):
  now=self.clock.live()
  if fault not in (None,'before_generator','after_generator','rejection_before_write'):raise ContractError('fixed fault hooks only')
  self.work['start_requests']+=1;self._assert_backend_identity();self.budget.check(quote_ns=750_000_000,tail_ns=500_000_000,extra_bytes=65536)
  spec=self._spec(raw,sequence,self.clock.live());a=Attempt(raw,sequence,spec);ns=self._namespace(spec);directory=self.root/ns
  self.clock.bind(raw,self.artifact,ns,inst(self.root),FREEZE)
  try:directory.mkdir()
  except FileExistsError as e:raise ContractError('logical request already claimed/conflicting payload; no generator retry')from e
  claim=canonical(a.identity)
  with (directory/'claim.json').open('xb')as f:f.write(claim);f.flush();os.fsync(f.fileno())
  a.reserve(raw,sequence,now=self.clock.live());record=self._save(a,'reserved',now)
  if fault=='before_generator':
   a.fail();record=self._save(a,'failed-before-generator',now);self.work['known_pre_generator_failures']+=1;raise BeforeGeneratorFailure(record)
  terminal=self._boundary(a,record)
  if terminal is not None:return terminal
  self.clock.live();self.work['generator_attempts']+=1
  try:wire,route=self.backend.serve_bound(convert(raw,expected_artifact_sha256=self.artifact,sequence=sequence,now_ns=self.clock.live()).pixels,sequence,a.identity)
  except Exception as e:
   self.blocked.add(ns);raise UncertainEffect('generator entered, no confirmed saved result',record)from e
  self.work['generated_wire_bytes']+=len(wire);self.work['generated_wire_sha256'].append(sha(wire))
  try:self._assert_backend_identity()
  except Exception as e:
   self.blocked.add(ns);raise UncertainEffect('backend state changed during generation; no result commit',record)from e
  if fault=='after_generator':
   self.blocked.add(ns);raise UncertainEffect('returned generated bytes not committed',record)
  try:a.attach(wire,route);record=self._save(a,'generated',now)
  except OutputBudgetExceeded as e:
   try:
    observed=self.clock.live()
    value={'schema':'local-output-budget-rejected-v1','identity':a.identity,'manifest_sha256':self.clock.pin,'reserved_record':record,'session':a.session.checkpoint(),'route':route,'wire_hex':wire.hex(),'required_output_bytes':e.required,'allowed_output_bytes':e.allowed,'observed_ns':observed,'classification':'known_generation_publication_rejected'}
    rejected=self._save_rejection(a,value,fault=fault)
   except Exception as failure:
    self.blocked.add(ns);raise UncertainEffect('output rejection not committed',record)from failure
   self.blocked.add(ns);raise KnownOutputBudgetRejection(rejected)
  except Exception as e:
   self.blocked.add(ns);raise UncertainEffect('generated result not committed',record)from e
  terminal=self._boundary(a,record)
  return terminal if terminal is not None else (a,record)
 def restore(self,record,raw,sequence):
  now=self.clock.live()
  self.clock.bind(raw,self.artifact,self._namespace(self._spec(raw,sequence,now)),inst(self.root),FREEZE)
  spec=self._spec(raw,sequence,now);path=self._path(record,spec)
  a=Attempt.load(path,raw_request=raw,sequence=sequence,expected_spec=spec,expected_file_sha256=record['sha256'],now=now)
  a._live_readonly=True # this v1 offers audit-only recovery, never new effects
  return a,record
 def _save_rejection(self,a,value,*,fault):
  import tempfile
  raw=canonical(value)
  if len(raw)>256*1024:raise ContractError('bounded output rejection')
  self.budget.check(quote_ns=250_000_000,tail_ns=500_000_000,extra_bytes=2*len(raw)+65536)
  self.clock.live()
  if fault=='rejection_before_write':raise OSError('injected rejection failure before temp creation')
  ns=self._namespace(a.session.spec);target=self.root/ns/'output-budget-rejected.json'
  fd,temp=tempfile.mkstemp(prefix='.output-rejection-',dir=target.parent)
  try:
   with os.fdopen(fd,'wb')as f:f.write(raw);f.flush();os.fsync(f.fileno())
   os.link(temp,target)
  finally:os.unlink(temp)
  return {'namespace':ns,'name':target.name,'bytes':len(raw),'sha256':sha(raw)}
 def _terminal_guard(self,a):
  directory=self.root/self._namespace(a.session.spec)
  if (directory/'output-budget-rejected.json').exists():raise ContractError('output budget rejection terminal; no publication or replay')
  if (directory/'control-fault.json').exists():raise ContractError('control effect unknown; supervisor disposition required')
  for name,phases in (('cancel-intent.json',('reserved','generated','chunk_prepared','complete')),('cancelled.json',('cancelled',)),('failed-before-generator.json',('failed',))):
   path=directory/name
   if not path.exists():continue
   if not path.is_file():raise ContractError('namespace terminal marker invalid')
   with path.open('rb')as f:raw=f.read(2*2**20+1)
   if len(raw)>2*2**20:raise ContractError('bounded namespace terminal marker')
   try:data=json.loads(raw,object_pairs_hook=unique,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('nonfinite terminal marker')))
   except (ValueError,UnicodeError)as e:raise ContractError('invalid terminal JSON')from e
   if type(data)is not dict or set(data)!={'payload','sha256'}or type(data['payload'])is not dict:raise ContractError('terminal marker schema')
   payload=data['payload']
   if sha(canonical(payload))!=data['sha256']or payload.get('identity')!=a.identity or payload.get('phase')not in phases:raise ContractError('terminal marker identity/checksum mismatch')
   raise ContractError('namespace terminal, older acknowledgement may not advance')
  if (directory/'control-observed.json').exists():raise ContractError('cancel decision unresolved; no further output')
 def publish(self,a,record,*,stop_after=None):
  now=self.clock.live();cancel_after=None;lose_ack_at=None
  ns=self._namespace(a.session.spec);self._terminal_guard(a)
  if getattr(a,'_live_readonly',False):raise ContractError('live-control recovered view is read-only')
  if ns in self.blocked or a.phase!='generated':raise ContractError('not an acknowledged publishable attempt')
  path=self._path(record,a.session.spec);stored=json.loads(path.read_bytes())['payload']
  if a.snapshot(stored['observed_ns'])!=stored:raise ContractError('live attempt does not match acknowledged saved record')
  chunks=parts(a.wire)
  if sum(v is not None for v in (stop_after,cancel_after,lose_ack_at))>1:raise ContractError('one fixed interruption hook')
  if any(v is not None and(type(v)is not int or not 1<=v<=len(chunks))for v in (stop_after,cancel_after))or lose_ack_at is not None and(type(lose_ack_at)is not int or not 0<=lose_ack_at<len(chunks)):raise ContractError('bounded interruption hook')
  while a.phase=='generated':
   terminal=self._boundary(a,record)
   if terminal is not None:return terminal
   now=self.clock.live();index=a.next_index;mode,chunk=chunks[index]
   a.prepare_piece(index,digest(chunk));intent=self._save(a,'piece-%02d-intent'%index,now)
   terminal=self._boundary(a,intent)
   if terminal is not None:return terminal
   a.publish(index,digest(chunk),now=self.clock.live());self.work['published_local_bytes']+=len(chunk)
   if lose_ack_at==index:
    self.work['unacknowledged_piece_bytes']+=len(chunk);self.blocked.add(ns);raise UncertainEffect('local prefix append acknowledgement not saved',intent)
   record=self._save(a,'piece-%02d-ack'%index,now)
   if cancel_after is not None and a.next_index==cancel_after:
    # Persist the cancellation decision before changing volatile state.
    self._save(a,'cancel-intent',now)
    a.cancel();record=self._save(a,'cancelled',now);return a,record
   if stop_after is not None and a.next_index==stop_after:return a,record
  return a,record

 def _put_control(self,a,name,value):
  ns=self._namespace(a.session.spec);target=self.root/ns/(name+'.json');temp=target.with_suffix('.tmp')
  raw=canonical(value)
  if len(raw)>65536:raise ContractError('bounded control record')
  self.budget.check(quote_ns=250_000_000,tail_ns=500_000_000,extra_bytes=2*len(raw)+65536)
  with temp.open('xb')as f:f.write(raw);f.flush();os.fsync(f.fileno())
  try:os.link(temp,target)
  finally:temp.unlink()
  return {'namespace':ns,'name':target.name,'sha256':sha(raw),'bytes':len(raw)}
 def _fault(self,a,error):
  self.blocked.add(self._namespace(a.session.spec))
  # If saving this record fails, original reservation/fragment intent remains
  # uncertain. Same epoch alone never authorizes disk-only continuation.
  self._put_control(a,'control-fault',{'identity':a.identity,'manifest_sha256':self.clock.pin,'observed_ns':self.clock.observe(),'error':type(error).__name__+': '+str(error),'disposition':'unknown_no_automatic_replay'})
  raise ContractError('control channel fault; no further output')from error
 def _cancel(self,a,record,message,observed):
  if getattr(a,'_live_readonly',False):raise ContractError('live-control recovered view is read-only')
  raw=canonical(message)
  if self.command_seen is not None:
   if raw!=self.command_seen:raise ContractError('conflicting duplicate control')
   if self.control_ack is None:raise ContractError('cancel disposition uncertain')
   return a,self.control_ack['final_record']
  self.command_seen=raw;self.blocked.add(self._namespace(a.session.spec))
  observed_ref=self._put_control(a,'control-observed',{'identity':a.identity,'manifest_sha256':self.clock.pin,'message':message,'observed_ns':observed,'prior_record':record})
  intent=self._save(a,'cancel-intent',observed);intent_return=self.clock.observe()
  a.cancel();final=self._save(a,'cancelled',self.clock.observe())
  ack={'schema':'local-cancel-ack-v1','manifest_sha256':self.clock.pin,'command_sha256':sha(raw),'observed_ns':observed,'intent_return_ns':intent_return,'ack_pre_send_ns':self.clock.observe(),'observed_record':observed_ref,'intent_record':intent,'final_record':final}
  ack_ref=self._put_control(a,'control-ack',ack)
  self.control_ack={'ack':ack,'ack_record':ack_ref,'final_record':final}
  return a,final
 def _boundary(self,a,record,*,wait=False):
  self._terminal_guard(a)
  if self._namespace(a.session.spec)in self.blocked:raise ContractError('control blocked')
  n=self.clock.observe()
  if n>=self.clock.manifest['deadline_ns']:
   msg=self.clock.command();msg['reason']='deadline_expired'
   return self._cancel(a,record,msg,n)
  if wait or available(self.reader):
   if self.reader is None:raise ContractError('no control reader')
   try:
    message=self.reader.read(min(self.clock.manifest['deadline_ns'],n+(5_000_000_000 if wait else 100_000_000)))
    observed=self.clock.validate(message)
   except Exception as e:self._fault(a,e)
   return self._cancel(a,record,message,observed)
  return None
 def await_cancel(self,a,record):
  if getattr(a,'_live_readonly',False):raise ContractError('live-control recovered view is read-only')
  # Instrumented rendezvous at ack2, not arbitrary kernel preemption.
  path=self._path(record,a.session.spec);stored=json.loads(path.read_bytes())['payload']
  if a.snapshot(stored['observed_ns'])!=stored:raise ContractError('live checkpoint mismatch')
  return self._boundary(a,record,wait=True)
 def replay_control(self,a,record,message):
  if getattr(a,'_live_readonly',False):raise ContractError('live-control recovered view is read-only')
  # Same-process idempotent acknowledgement only; never restores authority.
  self.clock.validate(message)
  return self._cancel(a,record,message,self.clock.observe())
