"""Fixed orthonormal2x2 per-channel coordinates, not a representation restriction."""
from dataclasses import dataclass
import hashlib,json
import numpy as np
from model import JointModel
from source_scene import SourceSceneModel,MODE as SOURCE_MODE
MODE='source-fixed2x2-haar-coordinates-v1'
SCHEMA='rgb-8x8x3-orthonormal-haar-coordinate-v1'
@dataclass(frozen=True)
class HaarProfile:
    mode:str
    def __post_init__(self):
        if self.mode!=MODE:raise ValueError('explicit fixed Haar mode')
    def metadata(self):return dict(schema=SCHEMA,mode=self.mode,pixels=192,commands=10,shape=[8,8,3],layout='rowmajor; eachchannel block positions00=LL,01=LH,10=HL,11=HH',matrix_half_rows=['++++','+-+-','++--','+--+'],conversion='xH andH^T W, only first192 encoderrows; resetAdam')
    @property
    def key(self):return hashlib.sha256(json.dumps(self.metadata(),sort_keys=True,separators=(',',':')).encode()).hexdigest()
PROFILE=HaarProfile(MODE)
def haar_pixels(profile,values):
    if type(profile) is not HaarProfile:raise ValueError('explicit Haar profile')
    profile.__post_init__();x=np.asarray(values,dtype=np.float64)
    if x.ndim!=2 or x.shape[1]!=192 or not 1<=len(x)<=65536 or not np.isfinite(x).all():raise ValueError('finite bounded N x192 pixels')
    im=x.reshape(-1,8,8,3);a=im[:,0::2,0::2,:];b=im[:,0::2,1::2,:];c=im[:,1::2,0::2,:];d=im[:,1::2,1::2,:]
    out=np.empty_like(im)
    out[:,0::2,0::2,:]=(a+b+c+d)*.5
    out[:,0::2,1::2,:]=(a-b+c-d)*.5
    out[:,1::2,0::2,:]=(a+b-c-d)*.5
    out[:,1::2,1::2,:]=(a-b-c+d)*.5
    if not np.isfinite(out).all():raise ValueError('Haar overflow; no repair')
    return out.reshape(-1,192)
def haar_features(profile,values):
    x=np.asarray(values,dtype=np.float64)
    if x.ndim!=2 or x.shape[1]!=202 or not 1<=len(x)<=65536 or not np.isfinite(x).all():raise ValueError('finite bounded N x202 features')
    out=x.copy();out[:,:192]=haar_pixels(profile,x[:,:192]);return out
def encoder_coordinates(profile,encoder):
    w=np.asarray(encoder,dtype=np.float64)
    if w.shape!=(202,32) or not np.isfinite(w).all():raise ValueError('fixedfinite202x32encoder')
    out=w.copy();out[:192]=haar_pixels(profile,w[:192].T).T;return out
class HaarSourceModel(SourceSceneModel):
    def __init__(self,input_dim,classes,pixels,hidden=32,seed=0,*,mode):
        if mode!=MODE:raise ValueError('explicit Haar source mode')
        super().__init__(input_dim,classes,pixels,hidden=hidden,seed=seed,mode=SOURCE_MODE)
        self.haar_work={'input_transform_calls':0,'input_transform_rows':0,'encoder_conversion_calls':0};self.conversion_source_digest=None
    @property
    def mode(self):return MODE
    def _input(self,x):
        masked=SourceSceneModel._input(self,x);out=haar_features(PROFILE,masked)
        self.haar_work['input_transform_calls']+=1;self.haar_work['input_transform_rows']+=len(out);return out
    @classmethod
    def from_source(cls,source,*,mode):
        if mode!=MODE or type(source) is not SourceSceneModel or source.mode!=SOURCE_MODE:raise ValueError('conversion fromexactrawSource mode only')
        out=cls(*source.dimensions[:3],hidden=source.dimensions[3],mode=MODE)
        if any(not np.isfinite(v).all() for v in source.params.values()):raise ValueError('nonfinite sourceparams')
        out.params={name:value.copy() for name,value in source.params.items()};out.params['encoder']=encoder_coordinates(PROFILE,source.params['encoder']);out.haar_work['encoder_conversion_calls']=1;out.conversion_source_digest=source.digest();return out
    def clone(self):
        out=HaarSourceModel(*self.dimensions[:3],hidden=self.dimensions[3],mode=MODE);out.params={name:value.copy() for name,value in self.params.items()};out.conversion_source_digest=self.conversion_source_digest;return out
    def digest(self):return hashlib.sha256((PROFILE.key+'\0'+JointModel.digest(self)).encode()).hexdigest()
    def save(self,path):raise ValueError('Haar checkpoint unsupported; no old-format mixing')
    @classmethod
    def load(cls,path):raise ValueError('Haar checkpoint unsupported; no old-format mixing')
