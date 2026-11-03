"""Registered adapter for the unmodified published continuous-pixel ContentModel.

No dataset/runner/D-probe access. Sparse Adam clocks are preserved, not coerced
into the small RGB backend's all-parameter/equal-clock contract.
"""
import hashlib,time
import numpy as np
from fashion_research.model import ContentModel,MODULES,SEQUENCES
from fashion_research import transport
from runtime import canonical,tensor
SCHEMA='published-fashion-content-sparse-adam-v1'
STEP_SCHEMA='fixed-explicit-fashion-step-v1'
ACTIVITY={'random_model_initializations':0,'allocation_only_model_restores':0}
def sha(x):return hashlib.sha256(x).hexdigest()
def param_shapes():
 return {key:shape for name,(a,b) in MODULES.items() for key,shape in ((name+'.W',(a,b)),(name+'.b',(b,)))}
def initial_work():
 return {'objective_calls':0,'loss_grad_calls':0,'optimizer_steps':0,'gradient_parameter_elements':0,'optimizer_parameter_elements':0,'inference_calls':0,'inference_rows':0,'sequence_outputs':0,'objective_CPU_seconds':0.,'transport_calls':0,'transport_returned_bytes':0,'transport_CPU_seconds':0.}
def array_hash(x):return sha(canonical({'shape':list(x.shape),'dtype':x.dtype.str})+x.tobytes(order='C'))

class FixedFashionStep:
 def __init__(self,clean,labels,terminal_noise,*,sequence,objective):
  if sequence not in SEQUENCES or objective not in ('anchor','A','N'):raise ValueError('fixed published sequence/objective')
  c=np.asarray(clean);y=np.asarray(labels);z=np.asarray(terminal_noise)
  if c.dtype!=np.float64 or c.ndim!=2 or not 1<=len(c)<=64 or c.shape[1]!=784 or not np.isfinite(c).all() or np.any(c<0) or np.any(c>1):raise ValueError('explicit clean training pixels')
  if y.dtype!=np.int64 or y.shape!=(len(c),) or np.any(y<0) or np.any(y>=10):raise ValueError('explicit labels')
  if z.dtype!=np.float64 or z.shape!=(len(c),4,784) or not np.isfinite(z).all():raise ValueError('explicit terminal-noise tensor')
  self.clean=c.copy();self.labels=y.copy();self.noise=z.copy();self.sequence=sequence;self.objective=objective
  for a in (self.clean,self.labels,self.noise):a.flags.writeable=False
  self._key=self._current_key()
 def _current_key(self):
  return sha(canonical({'schema':STEP_SCHEMA,'sequence':self.sequence,'objective':self.objective,'clean':array_hash(self.clean),'labels':array_hash(self.labels),'terminal_noise':array_hash(self.noise)}))
 def key(self):
  if self._current_key()!=self._key:raise ValueError('immutable training-step binding changed')
  return self._key

class _AllocationOnlyContent(ContentModel):
 def __init__(self,seed):
  if type(seed) is not int or not 0<=seed<2**63:raise ValueError('source seed profile')
  # Same frozen MODULES insertion order; inherited from_arrays validates/copies.
  self.seed=seed;self.params={name:np.zeros(shape,dtype=np.float64) for name,shape in param_shapes().items()};self._moments={}
  ACTIVITY['allocation_only_model_restores']+=1

class FashionBackend:
 def __init__(self,seed):
  self.model=ContentModel(seed);ACTIVITY['random_model_initializations']+=1
  self.updates=0;self.work=initial_work();self.last_gradient_keys=()
 def objective_step(self,x,objective,lr=.001):
  if not isinstance(objective,FixedFashionStep):raise ValueError('registered fixed step only')
  objective.key();start=time.process_time();self.work['objective_calls']+=1
  try:
   loss,g,metrics=self.model.loss_grad(x,objective.clean,objective.labels,objective.sequence,None,terminal_noise=objective.noise,objective=objective.objective)
   self.work['loss_grad_calls']+=1
   if not g:raise ValueError('nonempty sparse gradient required')
   self.work['gradient_parameter_elements']+=sum(v.size for v in g.values())
   self.model.adam_step(g,lr=lr);self.updates+=1
   self.work['optimizer_steps']+=1;self.work['optimizer_parameter_elements']+=sum(v.size for v in g.values());self.last_gradient_keys=tuple(g)
   return loss
  finally:self.work['objective_CPU_seconds']+=time.process_time()-start
 def infer(self,x,sequence):
  result=self.model.infer(x,sequence);self.work['inference_calls']+=1;self.work['inference_rows']+=len(result.p);self.work['sequence_outputs']+=len(result.p)
  return result
 def all_sequences(self,x):
  results=self.model.all_sequences(x);self.work['inference_calls']+=1;self.work['inference_rows']+=len(next(iter(results.values())).p);self.work['sequence_outputs']+=sum(len(v.p)for v in results.values())
  return results
 def serve(self,x,sequence):
  prediction=self.infer(x,sequence);start=time.process_time()
  raw=transport.encode(prediction.p,prediction.image);transport.decode(raw)
  self.work['transport_calls']+=1;self.work['transport_returned_bytes']+=len(raw);self.work['transport_CPU_seconds']+=time.process_time()-start
  return raw
 def digest(self):return self.model.digest()
 def receipt(self):
  return {'backend':SCHEMA,'work':dict(self.work),'units_scope':'call/row/parameter/byte counts plus objective/transport CPU, not full operator pricing; autodiff math, allocation, RNG for fresh model, snapshot JSON/hash/IO/import remain in whole child costs','full_legacy_unit_admission':False}
 def checkpoint_payload(self):
  ps=self.model.params;sh=param_shapes()
  if list(ps)!=list(sh) or type(self.updates) is not int or not 0<=self.updates<=1_000_000:raise ValueError('published parameter order/count')
  for k,s in sh.items():
   if ps[k].shape!=s or ps[k].dtype!=np.float64 or not np.isfinite(ps[k]).all():raise ValueError('finite source parameters')
  clocks={k:self.model._moments[k][2] if k in self.model._moments else 0 for k in sh}
  if max(clocks.values())!=self.updates:raise ValueError('global update/accounting clock mismatch')
  arrays=self.model.to_arrays(include_optimizer=True)
  return {'schema':SCHEMA,'seed':self.model.seed,'updates':self.updates,'clocks':clocks,'params':{k:v.tolist()for k,v in ps.items()},'moments':{k:{'m':arrays['adam.m.'+k].tolist(),'v':arrays['adam.v.'+k].tolist(),'step':arrays['adam.t.'+k].item()}for k in self.model._moments},'parameter_digest':self.model.digest(),'optimizer_digest':self.model.optimizer_digest()}
 @classmethod
 def from_checkpoint_payload(cls,p):
  fields={'schema','seed','updates','clocks','params','moments','parameter_digest','optimizer_digest'}
  if type(p) is not dict or set(p)!=fields or p['schema']!=SCHEMA or type(p['seed']) is not int or not 0<=p['seed']<2**63:raise ValueError('registered checkpoint schema/seed')
  u=p['updates'];sh=param_shapes()
  if type(u) is not int or not 0<=u<=1_000_000 or type(p['params']) is not dict or set(p['params'])!=set(sh) or type(p['clocks']) is not dict or set(p['clocks'])!=set(sh) or type(p['moments']) is not dict:raise ValueError('parameter/clock inventory')
  if any(type(t) is not int or not 0<=t<=u for t in p['clocks'].values()) or max(p['clocks'].values())!=u or set(p['moments'])!={k for k,t in p['clocks'].items()if t}:raise ValueError('sparse optimizer clock inventory')
  arrays={k:tensor(p['params'][k],s)for k,s in sh.items()}
  arrays.update(_version=np.array(1,dtype=np.int64),_seed=np.array(p['seed'],dtype=np.int64),_kind=np.array(ContentModel.kind),_has_optimizer=np.array(True))
  for k,z in p['moments'].items():
   if type(z) is not dict or set(z)!={'m','v','step'} or type(z['step']) is not int or z['step']!=p['clocks'][k]:raise ValueError('sparse moment record')
   arrays['adam.m.'+k]=tensor(z['m'],sh[k]);arrays['adam.v.'+k]=tensor(z['v'],sh[k]);arrays['adam.t.'+k]=np.array(z['step'],dtype=np.int64)
  model=_AllocationOnlyContent.from_arrays(arrays)
  if model.digest()!=p['parameter_digest'] or model.optimizer_digest()!=p['optimizer_digest']:raise ValueError('published digest binding')
  out=cls.__new__(cls);out.model=model;out.updates=u;out.work=initial_work();out.last_gradient_keys=();return out
