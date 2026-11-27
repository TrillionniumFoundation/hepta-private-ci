"""Exercise the real HCSN model and tied/untied update before any COCO labels are fitted."""
import json
import time
import numpy as np
import torch
from study import ROOT, BASE, parent, candidate, Samples, closed_direction, indices, write

torch.set_num_threads(1)
torch.set_num_interop_threads(1)
base=parent('hcsn',17011,'random')
rng=np.random.default_rng(735)
im=rng.integers(0,256,(20,64,64,3),dtype=np.uint8)
tx=np.zeros((20,1,32),dtype=np.int16)
tx[:,:,0]=1;tx[:,:,1:11]=rng.integers(4,100,(20,1,10));tx[:,:,11]=2
support=Samples.__new__(Samples);support.pix=im;support.cap=tx
order=indices(17011,len(im))
direction,fit=closed_direction(base,support,order)
assert tuple(direction.shape)==(3490,96) and direction.abs().max()>0
assert fit['support_tokens']==20*11 and 0<fit['retained_mass']<=1.00001
pairs=support.batch(np.arange(5),np.zeros(5,dtype=int),torch.device('cpu'))
before=base(pairs[0],pairs[1][:,:-1]).detach()
res={}
for k in ['untied_edit16','tied_edit16','tied_gradient','full_gradient']:
    model,cost=candidate(base,k,4. if k.endswith('edit16') else .001,direction,support,order)
    actual=model(pairs[0],pairs[1][:,:-1]).detach()
    assert torch.isfinite(actual).all() and not torch.equal(actual,before)
    is_tied=model.pred.weight.data_ptr()==model.embed.weight.data_ptr()
    assert is_tied==(k!='untied_edit16')
    res[k]={'tied':is_tied,'maximum_logit_change':float((actual-before).abs().max()),'cost':cost}
assert float(res['tied_edit16']['maximum_logit_change'])!=float(res['untied_edit16']['maximum_logit_change'])
write(BASE/'qualification.json',{'synthetic_support_only':True,'direction':fit,'arms':res,'torch':str(torch.__version__)})
print('qualified',res,flush=True)
