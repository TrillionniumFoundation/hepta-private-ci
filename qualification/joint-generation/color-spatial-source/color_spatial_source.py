"""Fixed color/spatial source independence prior, not decoded-semantic assurance."""
from dataclasses import dataclass
import hashlib,json
import numpy as np
from model import JointModel
from source_scene import SourceSceneModel,MODE as SOURCE_MODE
MODE='canonical-color-spatial-source-v1'
SCHEMA='rgb-canonical-3x4-color-spatial-source-v1'
ATTRS=tuple((k//4,k%4) for k in range(12))
NORMALIZATION_TOL=1e-12
@dataclass(frozen=True)
class ColorSpatialProfile:
    mode:str
    attributes:tuple=ATTRS
    def __post_init__(self):
        if (self.mode!=MODE or type(self.attributes) is not tuple or len(self.attributes)!=12
            or any(type(row) is not tuple or len(row)!=2 or any(type(v) is not int for v in row) for row in self.attributes)
            or self.attributes!=ATTRS):raise ValueError('explicit canonical integer tuple attribute profile only')
    def metadata(self):return dict(schema=SCHEMA,mode=self.mode,attributes=ATTRS,normalization_tolerance=NORMALIZATION_TOL,positive_policy=True,gradient='virtual factor-logit gradient; row sum tolerance1e-12; centered residual',prior='source label factors, not observed decoder semantics')
    @property
    def key(self):return hashlib.sha256(json.dumps(self.metadata(),sort_keys=True,separators=(',',':')).encode()).hexdigest()
PROFILE=ColorSpatialProfile(MODE)
def _project(profile,raw):
    if type(profile) is not ColorSpatialProfile:raise ValueError('explicit factor profile')
    profile.__post_init__();p=np.asarray(raw,dtype=np.float64)
    if p.ndim!=2 or p.shape[1]!=12 or not 1<=len(p)<=65536 or not np.isfinite(p).all() or np.any(p<=0):raise ValueError('nonempty strictly positive finite12-class rows')
    total=p.sum(1,keepdims=True)
    if not np.isfinite(total).all() or np.any(np.abs(total-1)>NORMALIZATION_TOL):raise ValueError('normalized raw policy required')
    p=p/total;attrs=np.asarray(ATTRS);m=[np.stack([p[:,attrs[:,axis]==v].sum(1) for v in range(size)],axis=1) for axis,size in enumerate((3,4))]
    product=np.ones_like(p)
    for axis in range(2):product*=m[axis][:,attrs[:,axis]]
    normalizer=product.sum(1,keepdims=True)
    if not np.isfinite(product).all() or np.any(product<=0) or not np.isfinite(normalizer).all() or np.any(normalizer<=0):raise ValueError('factor product underflow/nonfinite; no repair')
    q=product/normalizer
    if not np.isfinite(q).all() or np.any(q<=0):raise ValueError('normalized factor policy nonfinite/underflow')
    for axis,size in enumerate((3,4)):
        recovered=np.stack([q[:,attrs[:,axis]==v].sum(1) for v in range(size)],axis=1)
        if np.any(np.abs(recovered-m[axis])>NORMALIZATION_TOL):raise ValueError('factor marginal closure')
    return p,q,m

def project(profile,raw):return _project(profile,raw)[1]
def pullback(profile,raw,g):
    p,q,m=_project(profile,raw);g=np.asarray(g,dtype=np.float64)
    if g.shape!=p.shape or not np.isfinite(g).all():raise ValueError('finite matching log-policy cotangent')
    if np.any(np.abs(g.sum(1))>NORMALIZATION_TOL):raise ValueError('virtual factor-logit gradients must have near-zero row sums')
    # Explicit product-normalization centering retains finite sum residuals.
    # Arbitrary probability gradients are NOT accepted by this contract.
    centered=g-q*g.sum(1,keepdims=True);attrs=np.asarray(ATTRS);chain=np.zeros_like(p)
    for axis,size in enumerate((3,4)):
        G=np.stack([centered[:,attrs[:,axis]==v].sum(1) for v in range(size)],axis=1)
        chain+=(p/m[axis][:,attrs[:,axis]])*G[:,attrs[:,axis]]
    result=chain-p*chain.sum(1,keepdims=True)
    if not np.isfinite(result).all():raise ValueError('nonfinite pullback; no repair')
    return result

class ColorSpatialSourceModel(SourceSceneModel):
    def __init__(self,input_dim,classes,pixels,hidden=32,seed=0,*,mode):
        if mode!=MODE:raise ValueError('explicit color-spatial source mode')
        super().__init__(input_dim,classes,pixels,hidden=hidden,seed=seed,mode=SOURCE_MODE)
        self.factor_operations={'raw_forward_calls':0,'project_calls':0,'pullback_calls':0,'project_rows':0,'pullback_rows':0}
    @property
    def mode(self):return MODE
    def _raw_once(self,x):
        result=JointModel._forward(self,x);self.factor_operations['raw_forward_calls']+=1;return result
    def forward(self,x):
        _,_,pt,pi=self._raw_once(x);self.factor_operations['project_calls']+=2;self.factor_operations['project_rows']+=2*len(pt)
        return project(PROFILE,pt),project(PROFILE,pi)
    def gradients(self,x,dtext,dimage):
        x,h,pt,pi=self._raw_once(x)
        self.factor_operations['project_calls']+=2;self.factor_operations['project_rows']+=2*len(pt)
        self.factor_operations['pullback_calls']+=2;self.factor_operations['pullback_rows']+=2*len(pt)
        dt,di=pullback(PROFILE,pt,dtext),pullback(PROFILE,pi,dimage)
        dh=(dt@self.params['text'].T+di@self.params['image'].T)*(1-h*h)
        return {'encoder':x.T@dh,'bias':dh.sum(0),'text':h.T@dt,'text_bias':dt.sum(0),'image':h.T@di,'image_bias':di.sum(0)}
    def clone(self):
        out=ColorSpatialSourceModel(*self.dimensions[:3],hidden=self.dimensions[3],mode=MODE)
        out.params={name:value.copy() for name,value in self.params.items()};return out
    def digest(self):return hashlib.sha256((PROFILE.key+'\0'+JointModel.digest(self)).encode()).hexdigest()
    def save(self,path):raise ValueError('color-spatial checkpoint unsupported; no old mixing')
    @classmethod
    def load(cls,path):raise ValueError('color-spatial checkpoint unsupported; no old mixing')
