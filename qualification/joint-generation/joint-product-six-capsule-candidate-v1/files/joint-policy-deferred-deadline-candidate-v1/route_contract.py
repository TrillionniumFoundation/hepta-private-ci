"""Non-authorizing local route binding; finite schema, not learned-quality proof."""
import json,hashlib,math
from contracts import ContractError
PROFILE='fashion-j-actor-selective-v1'
POLICY='actor-J-v1'
ACTIONS=('T','I','J')
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode('ascii')
def sha(x):return hashlib.sha256(x).hexdigest()
def issha(x):return type(x)is str and len(x)==64 and all(c in '0123456789abcdef'for c in x)
def validate_route(r,identity,wire):
 if len(canonical(r))>8192:raise ContractError('bounded route record')
 fields={'schema','profile','policy','request_identity_sha256','artifact_sha256','input_pixels_sha256','features','actor_values','selected_index','sequence','executed_actions','wire_sha256'}
 if type(r)is not dict or set(r)!=fields or r['schema']!='bound-actor-route-v1'or r['profile']!=PROFILE or r['policy']!=POLICY:raise ContractError('route schema/profile')
 if r['request_identity_sha256']!=sha(canonical(identity))or r['artifact_sha256']!=identity['spec']['artifact_sha256']or r['wire_sha256']!=sha(wire)or not issha(r['input_pixels_sha256']):raise ContractError('route request/artifact/wire binding')
 for key,n in [('features',32),('actor_values',3)]:
  if type(r[key])is not list or len(r[key])!=n or any(type(v)is not float or not math.isfinite(v)for v in r[key]):raise ContractError('finite route numeric rows')
 k=r['selected_index'];expected=max(range(3),key=lambda i:r['actor_values'][i])
 if type(k)is not int or k!=expected or r['sequence']!='J'+ACTIONS[k]or r['executed_actions']!=['J',ACTIONS[k]]:raise ContractError('route argmax/action binding')
 return r
