"""Explicit work-matched representation benchmark; not deployment speed policy."""
import numpy as np
from model import JointModel
from source_scene import SourceSceneModel,MODE as SOURCE_MODE
from factorized_source import FactorizedSourceModel,PROFILE,MODE as FACTOR_MODE,project,pullback
WRAPPER_MODE='compute-both-direct-factor-select-v1'
WORK={}
def reset_work():WORK.clear()
class MatchedSourceModel(FactorizedSourceModel):
    def __init__(self,input_dim,classes,pixels,hidden=32,seed=0,*,representation,wrapper_mode):
        if wrapper_mode!=WRAPPER_MODE or representation not in ('direct','factor'):raise ValueError('explicit matched representation')
        self._representation=representation
        super().__init__(input_dim,classes,pixels,hidden=hidden,seed=seed,mode=FACTOR_MODE)
        self.matched_work={}
    @property
    def representation(self):return self._representation
    @property
    def mode(self):return SOURCE_MODE if self.representation=='direct' else FACTOR_MODE
    def identity(self):return dict(wrapper_mode=WRAPPER_MODE,representation=self.representation,selected_mode=self.mode,factor_profile_key=PROFILE.key,work='both laws andboth parameter-gradient dictionaries, selectonly')
    def _count(self,key,n=1):
        self.matched_work[key]=self.matched_work.get(key,0)+n
        k=self.representation+':'+key;WORK[k]=WORK.get(k,0)+n
    def _raw_matched(self,x):
        raw=JointModel._forward(self,x);self._count('raw_forward_calls');self._count('raw_forward_rows',len(raw[0]));return raw
    def forward(self,x):
        _,_,pt,pi=self._raw_matched(x);ft,fi=project(PROFILE,pt),project(PROFILE,pi)
        self._count('projection_calls',2);self._count('projection_rows',2*len(pt))
        return (pt,pi) if self.representation=='direct' else (ft,fi)
    def gradients(self,x,dtext,dimage):
        x,h,pt,pi=self._raw_matched(x);dt,di=np.asarray(dtext),np.asarray(dimage)
        if dt.shape!=pt.shape or di.shape!=pi.shape or not np.isfinite(dt).all() or not np.isfinite(di).all():raise ValueError('invalid matched logit gradients')
        ft,fi=pullback(PROFILE,pt,dt),pullback(PROFILE,pi,di)
        self._count('projection_calls',2);self._count('projection_rows',2*len(pt));self._count('pullback_calls',2);self._count('pullback_rows',2*len(pt))
        def paramgrad(a,b):
            dh=(a@self.params['text'].T+b@self.params['image'].T)*(1-h*h)
            return {'encoder':x.T@dh,'bias':dh.sum(axis=0),'text':h.T@a,'text_bias':a.sum(axis=0),'image':h.T@b,'image_bias':b.sum(axis=0)}
        rawgrad=paramgrad(dt,di);factorgrad=paramgrad(ft,fi)
        self._count('raw_parameter_gradient_dicts');self._count('factor_parameter_gradient_dicts');self._count('parameter_gradient_rows',len(x))
        return rawgrad if self.representation=='direct' else factorgrad
    def clone(self):
        out=MatchedSourceModel(*self.dimensions[:3],hidden=self.dimensions[3],representation=self.representation,wrapper_mode=WRAPPER_MODE)
        out.params={name:value.copy() for name,value in self.params.items()};return out
    def digest(self):
        return SourceSceneModel.digest(self) if self.representation=='direct' else FactorizedSourceModel.digest(self)
    def save(self,path):raise ValueError('matched checkpoint unsupported')
    @classmethod
    def load(cls,path):raise ValueError('matched checkpoint unsupported')
