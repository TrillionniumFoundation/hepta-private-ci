"""Explicit full-pixel training, resumable Adam state, and honest work receipts.

Numerical operation counters are component inventories, NOT a complete legacy
arithmetic ledger. Callback and runtime overhead remain timed and explicitly
unpriced. Checkpoints are bounded JSON data, never pickle or executable code.
"""
import hashlib,json,math,os,tempfile,time
from pathlib import Path
import numpy as np
from pixel_core import RequestPixelModel as Core,MODE as CORE_MODE
MODE='request-pixel-train-runtime-v1'
SCHEMA='request-pixel-adam-json-v1'
MAX_BYTES=4*2**20
MAX_ELEMENTS=100_000

def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode('ascii')
def reject_constant(x):raise ValueError('nonfinite JSON number')
def unique(pairs):
 d={}
 for k,v in pairs:
  if k in d:raise ValueError('duplicate JSON key')
  d[k]=v
 return d

def parse(raw):return json.loads(raw,parse_constant=reject_constant,object_pairs_hook=unique)
def shapes(dims):
 if not isinstance(dims,list) or len(dims)!=4 or any(type(v) is not int or v<1 for v in dims):raise ValueError('four positive integer dimensions')
 i,c,p,h=dims
 s={'encoder':(i,h),'bias':(h,),'text':(h,c),'text_bias':(c,),'image':(h,c),'image_bias':(c,),'decoder':(c,p),'decoder_bias':(p,),'pixel_context':(h,p)}
 if c>256 or h>512 or any(v>65536 for v in dims) or sum(math.prod(v) for v in s.values())>MAX_ELEMENTS:raise ValueError('bounded checkpoint model')
 return s

def tensor(value,shape):
 def validate(x,remaining):
  if remaining:
   if type(x) is not list or len(x)!=remaining[0]:raise ValueError('tensor nested shape')
   for y in x:validate(y,remaining[1:])
  elif type(x) not in (float,int) or not math.isfinite(x):raise ValueError('finite numeric tensor only')
 validate(value,shape)
 return np.asarray(value,dtype=np.float64)

class PixelTrainingRuntime(Core):
 def __init__(self,input_dim,classes,pixels,hidden=32,seed=0,*,mode):
  if mode!=MODE:raise ValueError('explicit runtime mode')
  shapes([input_dim,classes,pixels,hidden])
  super().__init__(input_dim,classes,pixels,hidden=hidden,seed=seed,mode=CORE_MODE)
  self.work={'forward_calls':0,'forward_rows':0,'forward_MACs':0,'pixel_tensor_elements':0,'objective_calls':0,'callback_CPU_seconds':0.,'gradient_calls':0,'gradient_MACs':0,'gradient_parameter_elements':0,'optimizer_steps':0,'optimizer_parameter_elements':0,'clone_operations':0}
 @property
 def mode(self):return MODE
 def _forward(self,x):
  out=super()._forward(x);n=len(out[0]);i,c,p,h=self.dimensions
  self.work['forward_calls']+=1;self.work['forward_rows']+=n;self.work['forward_MACs']+=n*(i*h+2*h*c)
  return out
 def _content(self,x):
  result=super()._content(x);n=len(result[0]);i,c,p,h=self.dimensions
  self.work['forward_MACs']+=n*h*p;self.work['pixel_tensor_elements']+=n*c*p
  return result
 def objective_gradients(self,x,objective):
  if not callable(objective):raise ValueError('callable current-pixel objective')
  def measured(p,q,v):
   start=time.process_time();self.work['objective_calls']+=1
   try:return objective(p,q,v)
   finally:self.work['callback_CPU_seconds']+=time.process_time()-start
  loss,g=super().objective_gradients(x,measured);n=len(x);i,c,p,h=self.dimensions
  # Encoder backward x.T@dh, two head forward-adjoint and weight products,
  # pixel-context forward-adjoint and weight product.
  self.work['gradient_calls']+=1;self.work['gradient_MACs']+=n*(i*h+4*h*c+2*h*p)
  self.work['gradient_parameter_elements']+=sum(v.size for v in g.values())
  return loss,g
 def apply_gradients(self,grads,lr):
  if set(grads)!=set(self.params):raise ValueError('full nine-parameter objective only')
  super().apply_gradients(grads,lr)
  self.work['optimizer_steps']+=1;self.work['optimizer_parameter_elements']+=sum(v.size for v in grads.values())
 def train_step(self,*args,**kwargs):raise ValueError('legacy categorical-only training forbidden')
 def supervised_step(self,*args,**kwargs):raise ValueError('declare supervised loss through full objective_step')
 def train_fixed(self,batches,objective_factory,*,steps,lr=.003):
  if type(steps) is not int or not 1<=steps<=10000 or not isinstance(batches,tuple) or len(batches)!=steps or not callable(objective_factory):raise ValueError('fixed explicit schedule required')
  # Shape validation before any updates; no automatic epoch/retry/adaptive stopping.
  for x in batches:self._input(x)
  result=[]
  for index,x in enumerate(batches):result.append(self.objective_step(x,objective_factory(index),lr=lr))
  return tuple(result)
 def clone(self):
  out=PixelTrainingRuntime(*self.dimensions[:3],hidden=self.dimensions[3],mode=MODE)
  out.params={k:v.copy() for k,v in self.params.items()};self.work['clone_operations']+=1
  return out
 def digest(self):
  return hashlib.sha256((MODE+'\0'+super().digest()).encode()).hexdigest()
 def receipt(self):
  return {'work':dict(self.work),'units_scope':'component MAC and element inventory only; non-MAC arithmetic, callback math, RNG, snapshot copies, JSON/hash/IO/import/runtime overhead not assigned old operator units','full_legacy_unit_admission':False}
 def checkpoint_payload(self):
  expected=shapes(list(self.dimensions))
  if set(self.params)!=set(expected) or type(self.updates) is not int or not 0<=self.updates<=1_000_000:raise ValueError('state schema')
  if (self.updates==0 and self._moments) or (self.updates>0 and set(self._moments)!=set(expected)):raise ValueError('complete optimizer state required')
  ps={};ms={}
  for k,s in expected.items():
   value=self.params[k]
   if value.shape!=s or value.dtype!=np.float64 or not np.isfinite(value).all():raise ValueError('finite parameter state')
   ps[k]=value.tolist()
   if self.updates:
    m,v,t=self._moments[k]
    if m.shape!=s or v.shape!=s or not np.isfinite(m).all() or not np.isfinite(v).all() or np.any(v<0) or type(t) is not int or t!=self.updates:raise ValueError('coherent Adam state')
    ms[k]={'m':m.tolist(),'v':v.tolist(),'step':t}
  return {'schema':SCHEMA,'mode':MODE,'dimensions':list(self.dimensions),'updates':self.updates,'params':ps,'moments':ms,'parameter_digest':self.digest()}
 def save(self,path):
  start=time.process_time();payload=self.checkpoint_payload();body=canonical(payload)
  raw=canonical({'payload':payload,'sha256':hashlib.sha256(body).hexdigest()})
  if len(raw)>MAX_BYTES:raise ValueError('bounded checkpoint bytes')
  target=Path(path)
  fd,temp=tempfile.mkstemp(prefix='.pixel-checkpoint-',dir=target.parent)
  try:
   with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
   os.link(temp,target) # Atomic no-overwrite publication, including existing symlinks.
  finally:os.unlink(temp)
  return {'bytes_written':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'CPU_seconds':time.process_time()-start,'optimizer_state_included':True,'work_snapshot_in_checkpoint':False,'cost_scope':'model work remains external; this receipt adds serialization/hash/IO CPU and bytes'}
 @classmethod
 def load(cls,path):
  start=time.process_time()
  with open(path,'rb') as f:raw=f.read(MAX_BYTES+1)
  if len(raw)>MAX_BYTES:raise ValueError('bounded checkpoint bytes')
  outer=parse(raw)
  if type(outer) is not dict or set(outer)!={'payload','sha256'} or outer['sha256']!=hashlib.sha256(canonical(outer['payload'])).hexdigest():raise ValueError('checkpoint integrity')
  out=cls.from_checkpoint_payload(outer['payload'])
  return out,{'bytes_read':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'CPU_seconds':time.process_time()-start,'resumed_updates':out.updates,'new_work_segment':True,'model_initialization':False,'prior_and_current_costs_must_be_combined':True}
 @classmethod
 def from_checkpoint_payload(cls,p):
  fields={'schema','mode','dimensions','updates','params','moments','parameter_digest'}
  if type(p) is not dict or set(p)!=fields or p['schema']!=SCHEMA or p['mode']!=MODE:raise ValueError('checkpoint profile')
  ss=shapes(p['dimensions']);u=p['updates']
  if type(u) is not int or not 0<=u<=1_000_000 or type(p['params']) is not dict or set(p['params'])!=set(ss) or type(p['moments']) is not dict:raise ValueError('checkpoint state')
  if set(p['moments'])!=(set(ss) if u else set()):raise ValueError('complete optimizer inventory')
  params={k:tensor(p['params'][k],s) for k,s in ss.items()};moments={}
  for k in p['moments']:
   z=p['moments'][k]
   if type(z) is not dict or set(z)!={'m','v','step'} or type(z['step']) is not int or z['step']!=u:raise ValueError('optimizer clock')
   m=tensor(z['m'],ss[k]);v=tensor(z['v'],ss[k])
   if np.any(v<0):raise ValueError('nonnegative second moment')
   moments[k]=(m,v,u)
  # Allocation-only reconstruction: deliberately no RNG/model initialization.
  out=cls.__new__(cls);out.dimensions=tuple(p['dimensions']);out.params=params;out._moments=moments;out.updates=u
  out.work={'forward_calls':0,'forward_rows':0,'forward_MACs':0,'pixel_tensor_elements':0,'objective_calls':0,'callback_CPU_seconds':0.,'gradient_calls':0,'gradient_MACs':0,'gradient_parameter_elements':0,'optimizer_steps':0,'optimizer_parameter_elements':0,'clone_operations':0}
  if out.digest()!=p['parameter_digest']:raise ValueError('parameter digest binding')
  return out
