"""Opt-in equal-group entropic risk over input views AND generated outputs.

The supplied row gradients differentiate NEGATIVE MEAN row CE, hence include1/n.
Group-chain multiplier K*softmax(-rho*CE) converts them to negative MEAN group CE.
Rewards/group membership are fixed constants. No anchor reweighting, STE or clipping.
"""
from dataclasses import dataclass
import hashlib,json,math
import numpy as np
from utility import joint_value_and_grad

MODE='equal-group-input-output-entropic-risk-v1'
SCHEMA='rgb-grouped-view-risk-objective-v1'

@dataclass(frozen=True)
class GroupRiskProfile:
    rho:float
    views:int
    mode:str
    def __post_init__(self):
        if self.mode!=MODE or type(self.rho) not in (int,float) or not math.isfinite(self.rho) or self.rho not in (0.,1.5):raise ValueError('explicit fixed group-risk mode/rho')
        if type(self.views) is not int or not 1<=self.views<=65536:raise ValueError('positive fixed equal group size')
    def metadata(self):
        return dict(schema=SCHEMA,mode=self.mode,rho=float(self.rho),views=self.views,grouping='contiguous blocks labelled0..G-1,exact equal K',row_gradient='negative mean rowCE incl1/n',anchor='not included; separately ordinary rowmean')
    @property
    def key(self):return hashlib.sha256(json.dumps(self.metadata(),sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def _groups(profile,labels,n):
    if type(profile) is not GroupRiskProfile:raise ValueError('explicit group profile, no old row objective')
    group=np.asarray(labels)
    if not 1<=n<=65536 or group.shape!=(n,) or group.dtype.kind not in 'iu' or n%profile.views:raise ValueError('nonempty integer equal groups')
    g=n//profile.views
    if not np.array_equal(group,np.repeat(np.arange(g),profile.views)):raise ValueError('contiguous canonical0..G-1 equalK group blocks')
    return g

def aggregate_rows(profile,row_ce,dtext,dimage,groups):
    """Compose fixed rowCE and negative-mean-row gradients; no target/anchor gradient."""
    values=np.asarray(row_ce,dtype=np.float64);dt=np.asarray(dtext,dtype=np.float64);di=np.asarray(dimage,dtype=np.float64)
    if values.ndim!=1:raise ValueError('per-row CE vector')
    n=len(values);g=_groups(profile,groups,n);k=profile.views
    if dt.shape!=(n,12) or di.shape!=dt.shape or not all(np.isfinite(x).all() for x in (values,dt,di)):raise ValueError('finite rowCE and twelve-class gradients')
    if k==1:
        return values.copy(),dt.copy(),di.copy(),np.ones(n)
    matrix=values.reshape(g,k)
    if profile.rho==0:
        means=matrix.mean(1)
        if not np.isfinite(means).all():raise ValueError('nonfinite group mean; no repair')
        return means,dt.copy(),di.copy(),np.ones(n)
    logs=-profile.rho*matrix;maximum=logs.max(1,keepdims=True)
    exponent=np.exp(logs-maximum);normalizer=exponent.sum(1,keepdims=True)
    weights=k*exponent/normalizer
    group_ce=-(maximum[:,0]+np.log(exponent.mean(1)))/profile.rho
    scale=weights.reshape(n)
    result=(group_ce,dt*scale[:,None],di*scale[:,None],scale)
    if not all(np.isfinite(x).all() for x in result):raise ValueError('nonfinite grouped risk; no repair')
    return result

def joint_group_value_and_grad(profile,p,q,rewards,groups):
    """Independent categorical output reference, fixed RGB bounded reward[-.35,1]."""
    pp=np.asarray(p,dtype=np.float64);qq=np.asarray(q,dtype=np.float64);r=np.asarray(rewards,dtype=np.float64)
    if pp.ndim!=2 or pp.shape[1]!=12 or qq.shape!=pp.shape:raise ValueError('fixed matching12class policies')
    _groups(profile,groups,len(pp))
    if r.shape!=(len(pp),12,12) or not np.isfinite(r).all() or np.any(r<-.35) or np.any(r>1.):raise ValueError('fixed bounded reward constants')
    ce,dt,di=joint_value_and_grad(pp,qq,r,profile.rho)
    return aggregate_rows(profile,ce,dt,di,groups)
