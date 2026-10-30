"""Explicit maximal semantic coupling after transport; default remains separate.

For semantic marginals p,q put min(p_s,q_s) on each matching pair. The residual
marginals have disjoint semantic support; couple them by their normalized product.
This maximizes agreement among ALL joint laws with those marginals. It uses no
target label, reward, source image, model update, or invented decoder outcome.
Marginal preservation is mathematical; implemented checks allow 1e-12 roundoff.
"""
from dataclasses import dataclass
import hashlib
import json
import math
from control import _canonical, _policy
from transport import TransportProfile, TRANSPORT_MODE

SCHEMA = 'rgb-maximal-semantic-coupling-v1'
COUPLING_MODE = 'transport-then-maximal-semantic-coupling'


@dataclass(frozen=True)
class CouplingProfile:
    transport: TransportProfile
    mode: str

    def __post_init__(self):
        if type(self.transport) is not TransportProfile or self.mode != COUPLING_MODE:
            raise ValueError('explicit coupling profile required')

    def metadata(self):
        return dict(schema=SCHEMA,mode=self.mode,transport_profile=json.loads(self.transport.dumps()))

    @property
    def key(self):
        return hashlib.sha256(_canonical(self.metadata()).encode()).hexdigest()

    def dumps(self):
        return _canonical(dict(profile=self.metadata(),profile_key=self.key))

    @classmethod
    def loads(cls,payload,*,expected_model_sha256,expected_mode):
        if type(payload) is not str or len(payload.encode())>32768:
            raise ValueError('bounded coupling document required')
        def unique(pairs):
            result={}
            for key,value in pairs:
                if key in result:raise ValueError('duplicate field')
                result[key]=value
            return result
        obj=json.loads(payload,object_pairs_hook=unique)
        if type(obj) is not dict or set(obj)!={'profile','profile_key'}:raise ValueError('exact coupling envelope')
        p=obj['profile']
        if (type(p) is not dict or set(p)!={'schema','mode','transport_profile'} or p['schema']!=SCHEMA
                or p['mode']!=expected_mode or expected_mode!=COUPLING_MODE):
            raise ValueError('explicit coupling schema/mode mismatch')
        transport=TransportProfile.loads(_canonical(p['transport_profile']),expected_model_sha256=expected_model_sha256,expected_mode=TRANSPORT_MODE)
        result=cls(transport,expected_mode)
        if obj['profile_key']!=result.key:raise ValueError('altered coupling identity')
        return result

    def apply(self,text,image,command,*,observed_model_sha256):
        law=self.transport.apply(text,image,command,observed_model_sha256=observed_model_sha256)
        p,q=law['text'],law['image'];_policy(p);_policy(q)
        image_inverse={s:j for j,s in enumerate(self.transport.base.image_semantics)}
        joint=[[0.0]*12 for _ in range(12)];left=list(p);right=list(q)
        for i,s in enumerate(self.transport.base.text_semantics):
            j=image_inverse[s];mass=min(p[i],q[j]);joint[i][j]=mass
            left[i]-=mass;right[j]-=mass
        residual_t=math.fsum(left);residual_i=math.fsum(right)
        # Exact zero only, not epsilon branch, clipping or renormalization.
        if residual_t>0 and residual_i>0:
            for i in range(12):
                for j in range(12):joint[i][j]+=left[i]*right[j]/residual_t
        if (any(abs(math.fsum(joint[i])-p[i])>1e-12 for i in range(12))
                or any(abs(math.fsum(joint[i][j] for i in range(12))-q[j])>1e-12 for j in range(12))):
            raise ValueError('incompatible normalized masses; no epsilon repair')
        total=math.fsum(x for row in joint for x in row)
        if (total<=0 or any(abs(math.fsum(joint[i])/total-p[i])>1e-12 for i in range(12))
                or any(abs(math.fsum(joint[i][j] for i in range(12))/total-q[j])>1e-12 for j in range(12))):
            raise ValueError('CDF-normalized law does not preserve marginals; no repair')
        return dict(text=p,image=q,joint=tuple(map(tuple,joint)),profile_key=self.key,command=command.values)


def sample_joint(joint,uniform):
    """Draw a pair with one supplied U[0,1) variate; no RNG or hidden fallback.

    CDF uses the actual finite-precision table total. For CouplingProfile outputs,
    the normalized marginals have a separate1e-12 guard. An arbitrary accepted
    input table has no such marginal guarantee; this function samples table/total.
    """
    if type(uniform) not in (int,float) or not math.isfinite(uniform) or not 0<=uniform<1:
        raise ValueError('explicit uniform variate in [0,1) required')
    if type(joint) is not tuple or len(joint)!=12 or any(type(row) is not tuple or len(row)!=12 for row in joint):
        raise ValueError('immutable 12x12 joint law required')
    entries=[x for row in joint for x in row]
    if any(type(x) not in (int,float) or not math.isfinite(x) or x<0 for x in entries):
        raise ValueError('finite nonnegative joint law required')
    total=math.fsum(entries)
    if abs(total-1)>1e-10:raise ValueError('normalized joint law required')
    threshold=uniform*total
    for index in range(144):
        if entries[index]>0 and threshold<math.fsum(entries[:index+1]):return divmod(index,12)
    raise ValueError('unresolved finite-precision CDF; no fallback')
