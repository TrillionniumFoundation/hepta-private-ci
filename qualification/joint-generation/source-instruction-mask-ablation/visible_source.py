"""FIT-source supervision with instruction-visible input; matched copy, no zeroing.

Same nominal model, optimizer and serving law as masked source mode. Only input
instruction zeroing differs numerically. Distinct mode/digest; no checkpoints.
"""
import hashlib
from model import JointModel

MODE='source-scene-FIT-instruction-visible-v1'
class SourceInstructionVisibleModel(JointModel):
    def __init__(self,input_dim,classes,pixels,hidden=32,seed=0,*,mode):
        if mode!=MODE or (input_dim,classes,pixels,hidden)!=(202,12,192,32):raise ValueError('explicit fixed visible-source mode/dimensions')
        super().__init__(input_dim,classes,pixels,hidden=hidden,seed=seed)
    @property
    def mode(self):return MODE
    def _input(self,x):return super()._input(x).copy()
    def clone(self):
        out=SourceInstructionVisibleModel(*self.dimensions[:3],hidden=self.dimensions[3],mode=MODE)
        out.params={name:value.copy() for name,value in self.params.items()}
        return out
    def digest(self):return hashlib.sha256((MODE+'\0'+super().digest()).encode()).hexdigest()
    def save(self,path):raise ValueError('visible-source checkpoint unsupported; no old-format mixing')
    @classmethod
    def load(cls,path):raise ValueError('visible-source checkpoint unsupported; no old-format mixing')
