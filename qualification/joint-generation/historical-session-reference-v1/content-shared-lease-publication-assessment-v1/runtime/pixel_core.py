"""Isolated request-conditioned learned pixel path; legacy source remains unchanged.

This API takes a freshly evaluated loss VJP on actual decoded pixels. It never
accepts a cached reward table as if that were a derivative through the decoder.
No task, dataset, optimizer trajectory or quality claim is built into this module.
"""
import numpy as np
from model import JointModel
MODE='request-conditioned-joint-pixel-v1'
class RequestPixelModel(JointModel):
    def __init__(self,input_dim,classes,pixels,hidden=32,seed=0,*,mode):
        if mode!=MODE:raise ValueError('new explicit pixel profile required')
        if any(type(n) is not int or n<1 for n in (input_dim,classes,pixels,hidden)):raise ValueError('positive integer dimensions')
        if input_dim*hidden+hidden+2*hidden*classes+2*classes+classes*pixels+pixels+hidden*pixels>4_000_000:
            raise ValueError('total pixel model capacity exceeded')
        super().__init__(input_dim,classes,pixels,hidden=hidden,seed=seed)
        self.params['pixel_context']=np.zeros((hidden,pixels),dtype=np.float64)
    @property
    def mode(self):return MODE
    def _content(self,x):
        x,h,p,q=self._forward(x)
        if len(x)*self.dimensions[1]*self.dimensions[2]>4_000_000:raise ValueError('bounded current-pixel tensor')
        z=self.params['decoder'][None,:,:]+self.params['decoder_bias'][None,None,:]+(h@self.params['pixel_context'])[:,None,:]
        if not np.isfinite(z).all() or np.max(np.abs(z))>40:raise ValueError('bounded finite pixel logits required')
        v=1/(1+np.exp(-z))
        return x,h,p,q,v
    def forward_content(self,x):
        _,_,p,q,v=self._content(x)
        return p,q,v
    def decode_images(self,class_ids,*,x=None):
        if x is None:raise ValueError('new pixel decoder requires legal request features')
        ids=np.asarray(class_ids);_,_,_,_,v=self._content(x)
        if ids.shape!=(len(v),) or ids.dtype.kind not in 'iu' or np.any(ids<0) or np.any(ids>=self.dimensions[1]):raise ValueError('one valid image code per request')
        return v[np.arange(len(v)),ids]
    def objective_gradients(self,x,objective):
        """objective(p,q,pixels) -> scalar loss, dlogits_p,dlogits_q,dpixels.

        VJPs must already include the objective's batch reduction. The callback
        receives read-only detached arrays; it must evaluate current pixels and
        use TRAIN-only targets outside serving. No reward semantics are implicit.
        """
        x,h,p,q,v=self._content(x)
        args=[]
        for value in (p,q,v):
            snapshot=value.copy();snapshot.flags.writeable=False;args.append(snapshot)
        result=objective(*args)
        if not isinstance(result,tuple) or len(result)!=4:raise ValueError('explicit scalar and three VJPs required')
        loss,dt,di,dv=result
        if np.ndim(loss)!=0 or not np.isfinite(loss):raise ValueError('finite scalar objective')
        dt,di,dv=(np.asarray(z,dtype=np.float64) for z in (dt,di,dv))
        if any(a.shape!=b.shape or not np.isfinite(a).all() for a,b in ((dt,p),(di,q),(dv,v))):raise ValueError('finite VJP shapes')
        dz=dv*v*(1-v);pooled=dz.sum(axis=1)
        dh=(dt@self.params['text'].T+di@self.params['image'].T+pooled@self.params['pixel_context'].T)*(1-h*h)
        grads={'encoder':x.T@dh,'bias':dh.sum(axis=0),'text':h.T@dt,'text_bias':dt.sum(axis=0),
               'image':h.T@di,'image_bias':di.sum(axis=0),'decoder':dz.sum(axis=0),
               'decoder_bias':dz.sum(axis=(0,1)),'pixel_context':h.T@pooled}
        if any(not np.isfinite(g).all() for g in grads.values()):raise ValueError('nonfinite full gradient')
        return float(loss),grads
    def objective_step(self,x,objective,lr=.003):
        loss,grads=self.objective_gradients(x,objective)
        # Existing checked global-norm Adam updates every supplied parameter.
        self.apply_gradients(grads,lr)
        return loss
    def utility_step(self,*args,**kwargs):raise ValueError('old cached reward-table utility interface forbidden; use current-pixel objective')
    def fit_decoder(self,*args,**kwargs):raise ValueError('old decoder-only fit interface forbidden in new profile')
    def clone(self):
        out=RequestPixelModel(*self.dimensions[:3],hidden=self.dimensions[3],mode=MODE)
        out.params={k:v.copy() for k,v in self.params.items()}
        return out
    def digest(self):
        import hashlib
        return hashlib.sha256((MODE+'\0'+super().digest()).encode()).hexdigest()
    def save(self,path):raise ValueError('new pixel checkpoint ABI not yet qualified')
    @classmethod
    def load(cls,path):raise ValueError('no old checkpoint reinterpretation')
