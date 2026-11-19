"""Explicit global64 input/output risk; ordinary anchor is outside this API."""
from dataclasses import dataclass
import hashlib,json,math
import numpy as np
from grouped_risk import GroupRiskProfile,MODE as GROUP_MODE,aggregate_rows
MODE='global-batch-input-output-entropic-risk-v1'
SCHEMA='rgb-global64-risk-objective-v1'
@dataclass(frozen=True)
class GlobalRiskProfile:
    rho:float
    batch_rows:int
    mode:str
    def __post_init__(self):
        if self.mode!=MODE or type(self.rho) not in (int,float) or not math.isfinite(self.rho) or self.rho not in (0.,1.5):raise ValueError('explicit global risk mode and fixed rho')
        if type(self.batch_rows) is not int or self.batch_rows!=64:raise ValueError('fixed64 rows')
    def metadata(self):
        return dict(schema=SCHEMA,mode=self.mode,rho=float(self.rho),batch_rows=self.batch_rows,grouping='one whole64-row batch; heterogeneous content allowed',row_gradient='negative mean rowCE includes1/64',anchor='excluded; caller adds ordinary mean separately')
    @property
    def key(self):return hashlib.sha256(json.dumps(self.metadata(),sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def global_rows(profile,row_ce,dtext,dimage):
    if type(profile) is not GlobalRiskProfile:raise ValueError('explicit global profile; old group profile rejected')
    profile.__post_init__()
    values=np.asarray(row_ce,dtype=np.float64)
    if values.shape!=(64,):raise ValueError('exact64 per-row CEs')
    return aggregate_rows(GroupRiskProfile(profile.rho,64,GROUP_MODE),values,dtext,dimage,np.zeros(64,dtype=np.int64))
