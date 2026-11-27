"""Adaptation-only coordinate conversion with equal transform auxiliary work."""
import numpy as np
from source_scene import SourceSceneModel,MODE as SOURCE_MODE
from haar_coordinate import HaarSourceModel,PROFILE,MODE as HAAR_MODE,haar_features,encoder_coordinates
MODE='matched-raw-haar-input-coordinates-v1'
WORK={}
def reset_work():WORK.clear()
class MatchedHaarModel(SourceSceneModel):
    def __init__(self,input_dim,classes,pixels,hidden=32,seed=0,*,representation,mode):
        if mode!=MODE or representation not in ('raw','haar'):raise ValueError('explicitmatchedcoordinates')
        self._representation=representation;super().__init__(input_dim,classes,pixels,hidden=hidden,seed=seed,mode=SOURCE_MODE);self.coordinate_work={};self.conversion_source_digest=None
    @property
    def representation(self):return self._representation
    @property
    def mode(self):return SOURCE_MODE if self.representation=='raw' else HAAR_MODE
    def identity(self):return dict(wrapper_mode=MODE,representation=self.representation,selected_mode=self.mode,haar_profile_key=PROFILE.key,work='oneinputHaar botharms, oneencoderHaar bothconversions; rawdiscard',conversion_source_digest=self.conversion_source_digest)
    def _count(self,key,n=1):
        self.coordinate_work[key]=self.coordinate_work.get(key,0)+n;k=self.representation+':'+key;WORK[k]=WORK.get(k,0)+n
    def _input(self,x):
        masked=SourceSceneModel._input(self,x);transformed=haar_features(PROFILE,masked);self._count('input_transform_calls');self._count('input_transform_rows',len(masked));return masked if self.representation=='raw' else transformed
    @classmethod
    def from_source(cls,source,*,representation,mode):
        if type(source) is not SourceSceneModel or source.mode!=SOURCE_MODE:raise ValueError('exactrawSource conversiononly')
        out=cls(*source.dimensions[:3],hidden=source.dimensions[3],representation=representation,mode=mode)
        if any(not np.isfinite(v).all() for v in source.params.values()):raise ValueError('nonfinitesourceparams')
        converted=encoder_coordinates(PROFILE,source.params['encoder']);out._count('encoder_transform_calls');out._count('encoder_transform_rows',32)
        out.params={name:value.copy() for name,value in source.params.items()}
        if representation=='haar':out.params['encoder']=converted
        out.conversion_source_digest=source.digest();return out
    def clone(self):
        out=MatchedHaarModel(*self.dimensions[:3],hidden=self.dimensions[3],representation=self.representation,mode=MODE);out.params={k:v.copy() for k,v in self.params.items()};out.conversion_source_digest=self.conversion_source_digest;return out
    def digest(self):return SourceSceneModel.digest(self) if self.representation=='raw' else HaarSourceModel.digest(self)
    def save(self,path):raise ValueError('matchedHaar checkpoint unsupported')
    @classmethod
    def load(cls,path):raise ValueError('matchedHaar checkpoint unsupported')
