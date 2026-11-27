"""Check causal, numerical and mechanism paths on development only, before fitting."""
import json,sys
import torch
from torch.nn import functional as F
from model import ARMS,Law
from study import Data,ROOT,net,write

def main():
    d=Data();pix,t,y=d.batch(d.index['development'][:3]);result={}
    for arm in ARMS:
        model=net(arm,109,d);pred=model(pix,t);loss=F.cross_entropy(pred.flatten(0,1),y.flatten(),ignore_index=0);loss.backward();stat={'params':sum(p.numel() for p in model.parameters()),'nll':float(loss.detach()),'early_patch_gradient_L1':float(model.patch.weight.grad.abs().sum())};assert stat['params']>=10_000_000 and stat['early_patch_gradient_L1']>0
        with torch.no_grad():
            altered=t.clone();altered[:,6:]=(altered[:,6:]+17)%850
            stat['future_to_prefix_max']=float((pred[:,:6]-model(pix,altered)[:,:6]).abs().max());assert stat['future_to_prefix_max']<2e-5
            if arm!='sdpa':
                stat['wire_gradient']=float(model.mixers[1].wire.weight.grad.abs().sum());stat['wire_intervention']=float((pred-model(pix,t,intervention={1:{'wire':.1}})).abs().max())
            if arm not in ('sdpa','lif'):
                _,details=model(pix,t,diagnostic=True);stat['mass_error']=float(max((z[...,1]+z[...,2]-1).abs().max() for z in details));assert stat['mass_error']<2e-5
                for j,name in enumerate(['equity','monetary_loss']):
                    h=t.new_zeros(2).float();h[j]=.05;stat[name+'_intervention']=float((pred-model(pix,t,intervention={1:{'prices':h}})).abs().max());stat[name+'_feedback_gradient']=float(model.mixers[1].feedback.grad[:,j].abs().sum())
                if arm=='literal':
                    stat['initial_release_mean_per_layer']=[float(x[...,0].mean()) for x in details];model.law=Law(ROOT/'law12.npz');p12,s12=model(pix,t,diagnostic=True)
                    stat['untrained_grid4_to_12']={'max_logit':float((pred-p12).abs().max()),'nll_delta':float((F.cross_entropy(p12.flatten(0,1),y.flatten(),ignore_index=0)-loss).detach()),'release_mean_abs_by_layer':[float((a[...,0]-b[...,0]).abs().mean()) for a,b in zip(details,s12)]}
            del model
        result[arm]=stat
    assert result['literal']['wire_intervention']>1e-6 and result['no_wire']['wire_intervention']==0
    for a,n in [('no_E','equity'),('no_L','monetary_loss')]:assert result['literal'][n+'_intervention']>1e-6 and result[a][n+'_intervention']==0
    write(ROOT/'qualification.json',result);print({k:v['params'] for k,v in result.items()})
if __name__=='__main__':main()
