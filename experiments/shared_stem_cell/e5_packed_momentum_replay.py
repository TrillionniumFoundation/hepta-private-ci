"""Research-only deterministic Packed Head SGD momentum checkpoint + replay."""
import hashlib,json,os
from pathlib import Path
import torch
import torch.nn.functional as F
from e5_sparse_packed_sgd import packed_bank,selected_indices,synthetic_inputs,frozen_hash,SHAPES
from e5_packed_head_fanout import packed_forward
SCHEMA='hepta.e5.packed-momentum-checkpoint.v1'
class Invalid(ValueError):pass
def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def checksum(v):return hashlib.sha256(v).hexdigest()
def initialize(logical,active,seed=20261014):
 if logical not in (64,256,1024,4096) or type(active) is not int or not 1<=active<=logical:raise Invalid('cohort')
 chosen=selected_indices(torch,logical,active,seed)
 return packed_bank(torch,logical,seed),{k:torch.zeros((active,*shape)) for k,shape in SHAPES.items()},chosen
def dormant(bank,chosen):
 return frozen_hash(bank,next(iter(bank.values())).shape[0],chosen.tolist())
def serialize(bank,momentum,chosen,scope,generation,step):
 if type(scope) is not str or not scope or type(generation) is not int or generation<1:raise Invalid('identity')
 logical=next(iter(bank.values())).shape[0];active=chosen.tolist()
 raw={'schema':SCHEMA,'scope':scope,'generation':generation,'steps':step,'logical':logical,'selected':active,
      'authority':'DENY_ALL','production_promotion_permitted':False,'dormant_sha256':dormant(bank,chosen),
      'weights':{},'momentum':{}}
 for name,shape in SHAPES.items():
  for field,t,length in [('weights',bank[name],logical),('momentum',momentum[name],len(active))]:
   if tuple(t.shape)!=(length,*shape) or not bool(torch.isfinite(t).all()):raise Invalid('tensor shape/numerics')
   raw[field][name]=t.detach().contiguous().numpy().astype('<f4',copy=False).tobytes().hex()
 raw['payload_sha256']=checksum(canonical(raw))
 return raw
def restore(raw,scope,generation,logical):
 if type(raw) is not dict or raw.get('schema')!=SCHEMA or raw.get('scope')!=scope or raw.get('generation')!=generation or raw.get('logical')!=logical or raw.get('authority')!='DENY_ALL' or raw.get('production_promotion_permitted') is not False:raise Invalid('identity/authority')
 expected=raw.get('payload_sha256')
 if type(expected) is not str or checksum(canonical({k:v for k,v in raw.items() if k!='payload_sha256'}))!=expected:raise Invalid('modified payload')
 active=raw.get('selected')
 if type(active) is not list or not active or active!=sorted(set(active)) or any(type(i) is not int or i<0 or i>=logical for i in active):raise Invalid('active lineage')
 if set(raw.get('weights',{}))!=set(SHAPES) or set(raw.get('momentum',{}))!=set(SHAPES):raise Invalid('inventory')
 bank={};momentum={}
 for name,shape in SHAPES.items():
  num=1
  for dim in shape:num*=dim
  for field,target,count in [('weights',bank,logical),('momentum',momentum,len(active))]:
   val=raw[field][name]
   if type(val) is not str or len(val)!=count*num*8:raise Invalid('byte length')
   try:bytestr=bytes.fromhex(val)
   except ValueError as ex:raise Invalid('hex') from ex
   tensor=torch.frombuffer(bytearray(bytestr),dtype=torch.float32).clone().reshape((count,*shape))
   if not bool(torch.isfinite(tensor).all()):raise Invalid('nonfinite')
   target[name]=tensor
 chosen=torch.tensor(active,dtype=torch.long)
 if dormant(bank,chosen)!=raw['dormant_sha256']:raise Invalid('dormant corruption')
 return bank,momentum,chosen
def train(bank,momentum,chosen,steps):
 torch.set_num_threads(1)
 initial=dormant(bank,chosen)
 active={k:torch.nn.Parameter(v.index_select(0,chosen).detach().clone()) for k,v in bank.items()}
 feature,state,labels=synthetic_inputs(torch,chosen);feature=feature.reshape(1,-1).expand(len(chosen),-1)
 losses=[]
 for _ in range(steps):
  for p in active.values():p.grad=None
  logits=packed_forward(torch,active,feature,state)
  loss=F.cross_entropy(logits,labels,reduction='sum');losses.append(float(loss.detach()))
  loss.backward()
  with torch.no_grad():
   for key,p in active.items():
    if p.grad is None or not bool(torch.isfinite(p.grad).all()):raise Invalid('gradient')
    momentum[key].mul_(.9).add_(p.grad)
    p.add_(momentum[key],alpha=-.01)
 with torch.no_grad():
  for key,p in active.items():bank[key].index_copy_(0,chosen,p)
 if dormant(bank,chosen)!=initial:raise Invalid('dormant cell mutation')
 return losses
def exact_replay(logical=64,active=8,seed=20261014,cut=2,total=4,scope='research',generation=1,checkpoint=None):
 if type(cut) is not int or type(total) is not int or not 1<=cut<total<=6:raise Invalid('steps')
 bank,m,selected=initialize(logical,active,seed);full=train(bank,m,selected,total)
 whole={k:v.clone() for k,v in bank.items()};whole_m={k:v.clone() for k,v in m.items()}
 bank,m,selected=initialize(logical,active,seed);before=train(bank,m,selected,cut)
 raw=serialize(bank,m,selected,scope,generation,cut)
 if checkpoint is not None:
  fd=os.open(checkpoint,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  with os.fdopen(fd,'wb') as f:f.write(canonical(raw)+b'\n');f.flush();os.fsync(f.fileno())
  raw=json.loads(Path(checkpoint).read_bytes())
 resumed,r_m,r_selected=restore(raw,scope,generation,logical)
 after=train(resumed,r_m,r_selected,total-cut)
 if before+after!=full or any(not torch.equal(resumed[k],whole[k]) or not torch.equal(r_m[k],whole_m[k]) for k in whole):raise Invalid('resume mismatch')
 return {'schema':'hepta.e5.packed-clean-restart-study.v1','logical_cells':logical,'active_cells':active,
  'checkpoint_sha256':raw['payload_sha256'],'step_count':total,'tensor_bit_exact':True,
  'momentum_bit_exact':True,'loss_sequence_bit_exact':True,'synthetic_data_only':True,
  'unclean_power_loss_or_wal_verified':False,'production_promotion_permitted':False,'authority':'DENY_ALL'}
