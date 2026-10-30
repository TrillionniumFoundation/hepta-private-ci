"""Fixed-zero exponential reward score; ordinary anchor remains outside API."""
from dataclasses import dataclass
import hashlib,json,math
import numpy as np
MODE='fixed-zero-exponential-score-v1'
SCHEMA='rgb-fixed64-exponential-utility-score-v1'
@dataclass(frozen=True)
class ScoreProfile:
    rho:float
    batch_rows:int
    mode:str
    def __post_init__(self):
        if self.mode!=MODE or type(self.rho) not in (float,int) or not math.isfinite(self.rho) or self.rho not in (0.,1.5):raise ValueError('explicit score mode/fixed rho')
        if type(self.batch_rows) is not int or self.batch_rows!=64:raise ValueError('fixed64 rows')
    def metadata(self):
        return dict(schema=SCHEMA,mode=self.mode,rho=float(self.rho),batch_rows=64,reward_zero=0.,reward_units='unchanged original RGB reward',row_gradient='negative mean rowCE includes1/64',anchor='excluded; caller adds ordinary mean separately')
    @property
    def key(self):return hashlib.sha256(json.dumps(self.metadata(),sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def score_rows(profile,row_ce,dtext,dimage):
    if type(profile) is not ScoreProfile:raise ValueError('explicit score profile only')
    profile.__post_init__()
    c=np.asarray(row_ce,dtype=np.float64);dp=np.asarray(dtext,dtype=np.float64);dq=np.asarray(dimage,dtype=np.float64)
    if c.shape!=(64,) or dp.shape!=(64,12) or dq.shape!=dp.shape or not all(np.isfinite(x).all() for x in (c,dp,dq)):raise ValueError('finite64 CE andalready-mean12class gradients')
    if profile.rho==0:
        mean=c.mean()
        if not np.isfinite(mean):raise ValueError('nonfinite score mean; no repair')
        return np.array([mean]),dp.copy(),dq.copy(),np.ones(64)
    # Fixed analytic composition, NOT a frozen reweighting/STE nor differentiation
    # through a detached scale. c must correspond to this same rho upstream.
    scales=np.exp(-profile.rho*c);values=-np.expm1(-profile.rho*c)/profile.rho
    result=(np.array([values.mean()]),scales[:,None]*dp,scales[:,None]*dq,scales)
    if not all(np.isfinite(x).all() for x in result):raise ValueError('nonfinite score; no floor or repair')
    return result
