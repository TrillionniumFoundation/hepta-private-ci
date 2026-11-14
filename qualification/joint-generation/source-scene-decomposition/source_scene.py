"""Explicit FIT source-scene supervision; command-blind learned perception.

Known request words are composed only by the existing external serving transport.
This adds FIT source-scene supervision, not new serving metadata or capacity.
Nominal parameter count unchanged; last10 encoder input rows are inactive.
No checkpoint format is defined; save/load are deliberately disabled.
"""
import hashlib
from model import JointModel

MODE='source-scene-FIT-supervised-v1'
class SourceSceneModel(JointModel):
    def __init__(self,input_dim,classes,pixels,hidden=32,seed=0,*,mode):
        if mode!=MODE or (input_dim,classes,pixels,hidden)!=(202,12,192,32):raise ValueError('explicit fixed source-scene mode/dimensions')
        super().__init__(input_dim,classes,pixels,hidden=hidden,seed=seed)
    @property
    def mode(self):return MODE
    def _input(self,x):
        clean=super()._input(x).copy()
        clean[:,-10:]=0.
        return clean
    def clone(self):
        out=SourceSceneModel(*self.dimensions[:3],hidden=self.dimensions[3],mode=MODE)
        out.params={name:value.copy() for name,value in self.params.items()}
        return out
    def digest(self):
        return hashlib.sha256((MODE+'\0'+super().digest()).encode()).hexdigest()
    def save(self,path):raise ValueError('source-scene checkpoint unsupported; no old-format mixing')
    @classmethod
    def load(cls,path):raise ValueError('source-scene checkpoint unsupported; no old-format mixing')
