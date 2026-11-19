"""Explicit immutable-batch session with prepare/commit/abort and bound recovery.

Single-process/saved-generation at-most-once token rejection; NOT distributed
exactly-once or crash durability. External callback effects are not rolled back.
"""
import hashlib,time,os,tempfile
from pathlib import Path
import numpy as np
from runtime import PixelTrainingRuntime,canonical,parse
from backend_registry import registered,input_width,restore,admit_step
MAX_BYTES=8*2**20
SCHEMA='explicit-pixel-session-v1'

def sha(raw):return hashlib.sha256(raw).hexdigest()
def validate_receipt(receipt):
 if type(receipt) is dict and receipt.get('backend')=='published-fashion-content-sparse-adam-v1':
  fields={'objective_calls','loss_grad_calls','optimizer_steps','gradient_parameter_elements','optimizer_parameter_elements','inference_calls','inference_rows','sequence_outputs','objective_CPU_seconds','transport_calls','transport_returned_bytes','transport_CPU_seconds'}
  if set(receipt)!={'backend','work','units_scope','full_legacy_unit_admission'} or receipt['full_legacy_unit_admission'] is not False or type(receipt['units_scope']) is not str or not receipt['units_scope'] or type(receipt['work']) is not dict or set(receipt['work'])!=fields:raise ValueError('Fashion receipt schema')
  for k,v in receipt['work'].items():
   if k.endswith('_CPU_seconds'):
    if type(v) not in (int,float) or not np.isfinite(v) or v<0:raise ValueError('Fashion CPU receipt')
   elif type(v) is not int or v<0:raise ValueError('Fashion component counter')
  return
 if type(receipt) is not dict or set(receipt)!={'work','units_scope','full_legacy_unit_admission'} or receipt['full_legacy_unit_admission'] is not False or type(receipt['units_scope']) is not str or not receipt['units_scope']:raise ValueError('component receipt scope')
 fields={'forward_calls','forward_rows','forward_MACs','pixel_tensor_elements','objective_calls','callback_CPU_seconds','gradient_calls','gradient_MACs','gradient_parameter_elements','optimizer_steps','optimizer_parameter_elements','clone_operations'}
 work=receipt['work']
 if type(work) is not dict or set(work)!=fields:raise ValueError('component receipt inventory')
 for key,value in work.items():
  if key=='callback_CPU_seconds':
   if type(value) not in (int,float) or not np.isfinite(value) or value<0:raise ValueError('component CPU receipt')
  elif type(value) is not int or value<0:raise ValueError('nonnegative component counters')
def state_hash(model):return sha(canonical(model.checkpoint_payload()))
def allocated_copy(model):
 # Validator copies every parameter and moment; no constructor/RNG.
 return restore(model.checkpoint_payload())
def batch_hash(x):return sha(canonical({'shape':list(x.shape),'dtype':'float64'})+x.astype('<f8',copy=False).tobytes(order='C'))

class Pending:
 def __init__(self,candidate,cursor,base_hash,token,loss):
  self.candidate=candidate;self.cursor=cursor;self.base_hash=base_hash;self.token=token;self.loss=loss;self.candidate_hash=state_hash(candidate)

class ExplicitSession:
 def __init__(self,model,batches,*,objective_profile,source_sha256,lr):
  if not registered(model) or model.updates!=0:raise ValueError('new session requires new zero-update model')
  self._bind(batches,objective_profile,source_sha256,lr,input_width(model))
  self.model=model;self.cursor=0;self.tokens={};self.attempts=[];self.pending=None
  self.initial_work=model.receipt()
 def _bind(self,batches,profile,source,lr,input_dim):
  if not isinstance(batches,tuple) or not 1<=len(batches)<=10000 or type(source) is not str or len(source)!=64 or any(c not in '0123456789abcdef' for c in source):raise ValueError('fixed schedule and source identity')
  if type(profile) is not dict or not profile or type(lr) not in (int,float) or not np.isfinite(lr) or not 0<lr<=1:raise ValueError('explicit objective/lr profile')
  self.profile=parse(canonical(profile));self.source=source;self.lr=float(lr);self.batches=[]
  if sum(np.asarray(x).size for x in batches)>1_000_000:raise ValueError('bounded batch schedule')
  for x in batches:
   a=np.asarray(x)
   if a.dtype!=np.float64 or a.ndim!=2 or not 1<=len(a)<=65536 or a.shape[1]!=input_dim or not np.isfinite(a).all():raise ValueError('finite explicit float64 batch')
   owned=a.copy();owned.flags.writeable=False;self.batches.append(owned)
  self.batches=tuple(self.batches)
  self.manifest={'schema':SCHEMA,'objective_profile':self.profile,'objective_source_sha256':source,'lr':self.lr,'batch_hashes':[batch_hash(x) for x in self.batches]}
  self.manifest_hash=sha(canonical(self.manifest))
 def prepare(self,*,expected_cursor,token,objective):
  if self.pending is not None or type(expected_cursor) is not int or expected_cursor!=self.cursor or self.cursor>=len(self.batches):raise ValueError('cursor/pending/schedule boundary')
  if type(token) is not str or not 1<=len(token)<=128 or token in self.tokens:raise ValueError('unique non-replay token required')
  admit_step(self.model,objective,self.profile,self.cursor)
  if self.lr!=self.manifest['lr'] or self.manifest_hash!=sha(canonical(self.manifest)) or batch_hash(self.batches[self.cursor])!=self.manifest['batch_hashes'][self.cursor]:raise ValueError('immutable schedule binding changed')
  self.tokens[token]='preparing';start=time.process_time();candidate=None
  try:
   base=state_hash(self.model);candidate=allocated_copy(self.model)
   loss=candidate.objective_step(self.batches[self.cursor],objective,lr=self.lr)
   self.pending=Pending(candidate,self.cursor,base,token,loss);self.tokens[token]='pending'
   return self.pending
  except Exception:
   self.tokens[token]='failed';raise
  finally:
   self.attempts.append({'token':token,'cursor':self.cursor,'CPU_seconds':time.process_time()-start,'candidate_work':candidate.receipt() if candidate is not None else None,'status_at_prepare_exit':self.tokens[token]})
 def commit(self,pending):
  if pending is not self.pending or pending is None:raise ValueError('unknown/consumed prepared transaction')
  if pending.cursor!=self.cursor or pending.base_hash!=state_hash(self.model):raise ValueError('stale source state')
  if pending.candidate_hash!=state_hash(pending.candidate) or pending.candidate.updates!=self.cursor+1 or self.tokens[pending.token]!='pending':raise ValueError('prepared candidate changed')
  self.model=pending.candidate;self.cursor+=1;self.tokens[pending.token]='committed';self.pending=None
  return pending.loss
 def abort(self,pending):
  if pending is not self.pending or pending is None:raise ValueError('unknown/consumed transaction')
  self.tokens[pending.token]='aborted';self.pending=None
 def advance(self,*,expected_cursor,token,objective):
  return self.commit(self.prepare(expected_cursor=expected_cursor,token=token,objective=objective))
 def payload(self):
  if self.pending is not None:raise ValueError('cannot snapshot an uncommitted candidate')
  if self.model.updates!=self.cursor or self.lr!=self.manifest['lr'] or self.manifest_hash!=sha(canonical(self.manifest)):raise ValueError('model/session clock or manifest mismatch')
  return parse(canonical({'schema':SCHEMA,'manifest':self.manifest,'manifest_sha256':self.manifest_hash,'cursor':self.cursor,'tokens':dict(self.tokens),'attempts':self.attempts,'initial_work':self.initial_work,'model':self.model.checkpoint_payload()}))
 def save(self,path):
  start=time.process_time();p=self.payload();raw=canonical({'payload':p,'sha256':sha(canonical(p))})
  if len(raw)>MAX_BYTES:raise ValueError('bounded session checkpoint')
  target=Path(path);fd,temp=tempfile.mkstemp(prefix='.pixel-session-',dir=target.parent)
  try:
   with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
   os.link(temp,target)
  finally:os.unlink(temp)
  return {'bytes_written':len(raw),'sha256':sha(raw),'CPU_seconds':time.process_time()-start,'crash_durable':False}
 @classmethod
 def load(cls,path,batches,*,objective_profile,source_sha256,lr):
  start=time.process_time()
  with open(path,'rb') as f:raw=f.read(MAX_BYTES+1)
  if len(raw)>MAX_BYTES:raise ValueError('bounded session checkpoint')
  outer=parse(raw)
  if type(outer) is not dict or set(outer)!={'payload','sha256'} or outer['sha256']!=sha(canonical(outer['payload'])):raise ValueError('session integrity')
  p=outer['payload'];fields={'schema','manifest','manifest_sha256','cursor','tokens','attempts','initial_work','model'}
  if type(p) is not dict or set(p)!=fields or p['schema']!=SCHEMA:raise ValueError('session schema')
  model=restore(p['model'])
  out=cls.__new__(cls);out._bind(batches,objective_profile,source_sha256,lr,input_width(model))
  if p['manifest']!=out.manifest or p['manifest_sha256']!=out.manifest_hash:raise ValueError('schedule/objective/source/lr mismatch')
  cur=p['cursor'];tokens=p['tokens'];attempts=p['attempts']
  if type(cur) is not int or not 0<=cur<=len(batches) or cur!=model.updates or type(tokens) is not dict or type(attempts) is not list or len(attempts)>10000:raise ValueError('session clocks/inventory')
  if any(type(k) is not str or not 1<=len(k)<=128 or v not in ('committed','aborted','failed') for k,v in tokens.items()):raise ValueError('terminal token state')
  if sum(v=='committed' for v in tokens.values())!=cur:raise ValueError('committed token count')
  if any(type(a) is not dict or set(a)!={'token','cursor','CPU_seconds','candidate_work','status_at_prepare_exit'} for a in attempts):raise ValueError('attempt inventory')
  if len(attempts)!=len(tokens) or len({a['token'] for a in attempts})!=len(attempts) or {a['token'] for a in attempts}!=set(tokens) or any(type(a['cursor']) is not int or not 0<=a['cursor']<len(batches) or type(a['CPU_seconds']) not in (int,float) or not np.isfinite(a['CPU_seconds']) or a['CPU_seconds']<0 for a in attempts):raise ValueError('attempt bindings')
  if [a['cursor'] for a in attempts if tokens[a['token']]=='committed']!=list(range(cur)):raise ValueError('committed cursor sequence')
  validate_receipt(p['initial_work'])
  for a in attempts:
   expected='failed' if tokens[a['token']]=='failed' else 'pending'
   if a['status_at_prepare_exit']!=expected:raise ValueError('attempt status binding')
   if a['candidate_work'] is not None:validate_receipt(a['candidate_work'])
   elif expected!='failed':raise ValueError('successful prepare missing work')
  out.model=model;out.cursor=cur;out.tokens=tokens;out.attempts=attempts;out.pending=None;out.initial_work=p['initial_work']
  return out,{'bytes_read':len(raw),'sha256':sha(raw),'CPU_seconds':time.process_time()-start,'prior_attempt_costs_retained':True,'external_RNG_state':'none used by session; arbitrary callback purity not enforced','scope':'same immutable explicit schedule and declared objective source identity; not arbitrary stochastic/distributed/exactly-once recovery'}
