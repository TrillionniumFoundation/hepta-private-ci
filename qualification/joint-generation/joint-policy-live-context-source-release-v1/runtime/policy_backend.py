"""Isolated selective serving seam, explicit private upstream primitives.
No targets/labels enter this API; no updates. Both model states are bound.
"""
import numpy as np
from fashion_research.model import ContentModel,Actor,MODULES
from fashion_research import transport
from route_contract import PROFILE,POLICY,ACTIONS,canonical,sha,validate_route
from contracts import ContractError
class AllocContent(ContentModel):
 def __init__(self,seed):
  self.seed=seed;self.params={k:np.zeros(shape,dtype=np.float64)for n,(a,b)in MODULES.items()for k,shape in [(n+'.W',(a,b)),(n+'.b',(b,))]};self._moments={}
class AllocActor(Actor):
 def __init__(self,seed):
  self.seed=seed;self.params={k:np.zeros(shape,dtype=np.float64)for n,(a,b)in {'hidden':(32,8),'values':(8,3)}.items()for k,shape in [(n+'.W',(a,b)),(n+'.b',(b,))]};self._moments={}
def tensor_ref(a):return {'dtype':a.dtype.str,'shape':list(a.shape),'sha256':sha(a.tobytes(order='C'))}
def pixel_digest(x):return sha(canonical(tensor_ref(x)))
def inventory(model):return {k:tensor_ref(v)for k,v in model.to_arrays(include_optimizer=True).items()}
class PolicyBackend:
 def __init__(self,content_arrays,actor_arrays,source_freeze,provenance):
  self.content=AllocContent.from_arrays(content_arrays);self.actor=AllocActor.from_arrays(actor_arrays)
  self.source=source_freeze;self.provenance=provenance
  self.work={'allocation_restores':2,'fresh_models':0,'optimizer_steps':0,'serving_calls':0,'serving_actor_predictions':0,'serving_prefix_J':0,'serving_final_updates':{'T':0,'I':0,'J':0},'serving_encoded_rows':0,'reference_calls':0,'reference_actor_predictions':0,'reference_candidate_rows':0,'reference_encoded_rows':0}
 def checkpoint_payload(self):
  return {'schema':'paired-content-actor-serving-v1','profile':PROFILE,'policy':POLICY,'action_map':list(ACTIONS),'tie_rule':'first-index-argmax','source_freeze':self.source,'provenance':self.provenance,'content':{'parameter_digest':self.content.digest(),'optimizer_digest':self.content.optimizer_digest(),'arrays':inventory(self.content)},'actor':{'parameter_digest':self.actor.digest(),'optimizer_digest':self.actor.optimizer_digest(),'arrays':inventory(self.actor)}}
 def serve_bound(self,x,policy,identity):
  if policy!=POLICY or identity['sequence']!=POLICY or sha(canonical(self.checkpoint_payload()))!=identity['spec']['artifact_sha256']:raise ContractError('paired routing policy/artifact')
  if x.shape!=(1,784)or x.dtype!=np.float64 or x.flags.writeable:raise ContractError('qualified singleton input')
  self.work['serving_calls']+=1
  ctx,initial=self.content._context(x,False)
  state=self.content._advance(initial,'J',ctx);self.work['serving_prefix_J']+=1
  features=self.content._observe(state,ctx)[2].data.copy()
  values=self.actor.predict(features);self.work['serving_actor_predictions']+=1
  k=int(values[0].argmax());action=ACTIONS[k]
  final=self.content._advance(state,action,ctx);self.work['serving_final_updates'][action]+=1
  pred=self.content._prediction(final);wire=transport.encode(pred.p,pred.image);self.work['serving_encoded_rows']+=1
  route={'schema':'bound-actor-route-v1','profile':PROFILE,'policy':POLICY,'request_identity_sha256':sha(canonical(identity)),'artifact_sha256':identity['spec']['artifact_sha256'],'input_pixels_sha256':pixel_digest(x),'features':features[0].tolist(),'actor_values':values[0].tolist(),'selected_index':k,'sequence':'J'+action,'executed_actions':['J',action],'wire_sha256':sha(wire)}
  validate_route(route,identity,wire)
  return wire,route
 def reference(self,x):
  # Separate public control flow: computes all candidates; never called by serve.
  f,preds=self.content.j_candidates(x);v=self.actor.predict(f)
  self.work['reference_calls']+=1;self.work['reference_actor_predictions']+=1;self.work['reference_candidate_rows']+=3
  wires={s:transport.encode(p.p,p.image)for s,p in preds.items()};self.work['reference_encoded_rows']+=3
  return {'features':f[0].tolist(),'actor_values':v[0].tolist(),'selected_index':int(v[0].argmax()),'input_pixels_sha256':pixel_digest(x)},wires
