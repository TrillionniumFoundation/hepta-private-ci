"""Isolated request/fragment state machine, not runtime authority or distributed once.

A reserved recovered checkpoint has uncertain generator effect and becomes
indeterminate. No automatic model retry is provided. Caller must persist a
reservation before any external generator; this module does not invoke one.
"""
import json,os,tempfile
from pathlib import Path
from contracts import RunSession,RunSpec,ContractError,digest
from persistence import canonical,sha,binding,stamp,MAX_BYTES
from content_input import unique
from fashion_research import transport
SCHEMA='local-fragment-attempt-v1'
def parts(wire):
 if type(wire)is not bytes or len(wire)>256*1024:raise ContractError('bounded generated wire')
 transport.decode(wire);value=json.loads(wire)
 if len(value['rows'])!=1:raise ContractError('one generated row')
 result=[]
 for mode in ('text','image'):
  raw=canonical(value['rows'][0][mode])
  for start in range(0,len(raw),8192):result.append((mode,raw[start:start+8192]))
 return result
class Attempt:
 def __init__(self,raw,sequence,spec):
  self.identity=binding(raw,sequence,spec);self.session=RunSession(spec)
  self.phase='fresh';self.reservations=0;self.wire=None;self.next_index=0;self._reservation_saved=False;self.pending_chunk=None;self._chunk_saved=False
 def identity_check(self,raw,sequence):
  if binding(raw,sequence,self.session.spec)!=self.identity:raise ContractError('request identity mismatch')
 def reserve(self,raw,sequence,*,now):
  self.identity_check(raw,sequence)
  if self.phase!='fresh':raise ContractError('request attempt already consumed/uncertain')
  self.session._live(now)
  if sum(self.session._spent.values())+2>self.session.spec.budget.compute_units:raise ContractError('two tickets required before reservation')
  self.session.charge('controller',1,now_ns=now);self.session.charge('generator',1,now_ns=now)
  self.phase='reserved';self.reservations=1
 def attach(self,wire):
  if self.phase!='reserved' or not self._reservation_saved:raise ContractError('persisted reserved live attempt required')
  try:
   chunks=parts(wire)
   if sum(len(chunk)for _,chunk in chunks)>self.session.spec.budget.output_bytes:raise ContractError('whole generated output does not fit')
  except Exception:self.phase='failed';raise
  self.wire=bytes(wire);self.phase='generated'
 def fail(self):
  if self.phase!='reserved':raise ContractError('reserved attempt required')
  self.phase='failed'
 def prepare_piece(self,index,chunk_sha256):
  if self.phase!='generated':raise ContractError('not preparable')
  chunks=parts(self.wire)
  if type(index)is not int or index!=self.next_index or index>=len(chunks):raise ContractError('chunk index replay/gap')
  mode,chunk=chunks[index]
  if digest(chunk)!=chunk_sha256:raise ContractError('chunk digest mismatch')
  self.pending_chunk=index;self.phase='chunk_prepared';self._chunk_saved=False
 def publish(self,index,chunk_sha256,*,now):
  if self.phase!='chunk_prepared' or not self._chunk_saved:raise ContractError('persisted chunk intent required')
  chunks=parts(self.wire)
  if type(index)is not int or index!=self.pending_chunk or index!=self.next_index or digest(chunks[index][1])!=chunk_sha256:raise ContractError('chunk intent mismatch')
  mode,chunk=chunks[index]
  self.session.publish(mode,chunk,expected_prefix_sha256=digest(self.session.prefix(mode)),now_ns=now)
  self.next_index+=1;self.pending_chunk=None;self._chunk_saved=False;self.phase='generated'
  if self.next_index==len(chunks):self.phase='complete'
 def cancel(self):self.session.cancel();self.phase='cancelled'
 def snapshot(self,observed_ns):
  return json.loads(canonical({'schema':SCHEMA,'identity':self.identity,'observed_ns':stamp(observed_ns),'session':self.session.checkpoint(),'phase':self.phase,'reservations':self.reservations,'wire_hex':self.wire.hex()if self.wire is not None else None,'next_index':self.next_index,'pending_chunk':self.pending_chunk}))
 def save(self,path,*,observed_ns):
  payload=self.snapshot(observed_ns);raw=canonical({'payload':payload,'sha256':sha(canonical(payload))})
  if len(raw)>MAX_BYTES:raise ContractError('bounded attempt snapshot')
  target=Path(path);fd,temp=tempfile.mkstemp(prefix='.attempt-',dir=target.parent)
  try:
   with os.fdopen(fd,'wb')as f:f.write(raw);f.flush();os.fsync(f.fileno())
   os.link(temp,target)
  finally:os.unlink(temp)
  if self.phase=='reserved':self._reservation_saved=True
  if self.phase=='chunk_prepared':self._chunk_saved=True
  return {'sha256':sha(raw),'bytes':len(raw),'crash_durable':False}
 @classmethod
 def load(cls,path,*,raw_request,sequence,expected_spec,expected_file_sha256,now):
  now=stamp(now)
  with open(path,'rb')as f:raw=f.read(MAX_BYTES+1)
  if len(raw)>MAX_BYTES or sha(raw)!=expected_file_sha256:raise ContractError('attempt file digest/length')
  try:data=json.loads(raw,object_pairs_hook=unique,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('nonfinite')))
  except (ValueError,UnicodeError)as e:raise ContractError('invalid attempt JSON')from e
  if type(data)is not dict or set(data)!={'payload','sha256'}:raise ContractError('attempt envelope')
  p=data['payload']
  if type(p)is not dict or set(p)!={'schema','identity','observed_ns','session','phase','reservations','wire_hex','next_index','pending_chunk'} or p['schema']!=SCHEMA or sha(canonical(p))!=data['sha256']:raise ContractError('attempt schema/checksum')
  if now<stamp(p['observed_ns'])or p['identity']!=binding(raw_request,sequence,expected_spec):raise ContractError('time/request binding')
  if type(p['session'])is not dict or set(p['session'])!={'payload','sha256'} or type(p['session']['payload'])is not dict or p['session']['payload'].get('spec')!=expected_spec.payload():raise ContractError('session binding')
  session=RunSession.restore(p['session'],expected_artifact_sha256=expected_spec.artifact_sha256,now_ns=now)
  phase=p['phase'];count=p['reservations'];index=p['next_index']
  if phase not in ('fresh','reserved','generated','complete','cancelled','failed','indeterminate','chunk_prepared','fragment_indeterminate')or type(count)is not int or count not in (0,1)or type(index)is not int or index<0:raise ContractError('attempt state inventory')
  wire=None
  if p['wire_hex']is not None:
   if type(p['wire_hex'])is not str or len(p['wire_hex'])>512*1024:raise ContractError('bounded wire hex')
   try:wire=bytes.fromhex(p['wire_hex'])
   except ValueError as e:raise ContractError('wire encoding')from e
  chunks=parts(wire)if wire is not None else []
  if index>len(chunks):raise ContractError('chunk cursor')
  prefixes={m:b''for m in session.spec.modalities}
  for mode,chunk in chunks[:index]:prefixes[mode]+=chunk
  if any(session.prefix(m)!=v for m,v in prefixes.items()):raise ContractError('prefix/chunk cursor mismatch')
  if session._spent!={'controller':count,'generator':count}:raise ContractError('reservation charge mismatch')
  if phase in ('reserved','failed','indeterminate')and(count!=1 or wire is not None or index!=0):raise ContractError('unresolved state')
  if phase=='fresh'and(count!=0 or wire is not None or index!=0):raise ContractError('fresh state')
  if phase in ('generated','complete','chunk_prepared','fragment_indeterminate')and(count!=1 or wire is None):raise ContractError('generated state')
  pending=p['pending_chunk']
  if pending is not None and(type(pending)is not int or pending!=index or index>=len(chunks)or phase not in ('chunk_prepared','fragment_indeterminate','cancelled')):raise ContractError('pending fragment state')
  if phase in ('chunk_prepared','fragment_indeterminate')and pending is None:raise ContractError('missing pending fragment')
  if phase=='generated'and index>=len(chunks)or phase=='complete'and index!=len(chunks):raise ContractError('completion cursor')
  if (phase=='cancelled')!=session.checkpoint()['payload']['cancelled']:raise ContractError('cancel binding')
  if phase=='cancelled'and(count==0 and(wire is not None or index!=0)):raise ContractError('cancel-before-reserve state')
  obj=object.__new__(cls);obj.identity=p['identity'];obj.session=session;obj.phase='indeterminate'if phase=='reserved'else('fragment_indeterminate'if phase=='chunk_prepared'else phase);obj.reservations=count;obj.wire=wire;obj.next_index=index;obj.pending_chunk=pending;obj._reservation_saved=False;obj._chunk_saved=False
  return obj
