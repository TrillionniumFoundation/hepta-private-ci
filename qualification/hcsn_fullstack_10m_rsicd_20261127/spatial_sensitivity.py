"""Switch the physical bin quadrature at unchanged trained parameters on fixed development rows."""
import json,sys
from pathlib import Path
import numpy as np
import torch
from torch.nn import functional as F
from model import Law
from study import Data,ROOT,SEEDS,net,sha,write

def summarize(logits,y):
    return F.cross_entropy(logits.transpose(1,2),y,ignore_index=0,reduction='sum').item()/int((y!=0).sum())
def main():
    data=Data();root=ROOT;selected=json.loads((root/'seal.json').read_text());rows=data.index['development'][:16];out={}
    for s in SEEDS:
        a=selected[f'literal-{s}']['cpu300'];model=net('literal',s,data);state=root/'runs'/f'literal-{s}'/a['state'];assert sha(state)==a['sha']
        model.load_state_dict(torch.load(state,weights_only=True,map_location='cpu'));model.eval();p,x,y=data.batch(rows)
        with torch.no_grad():
            before,db=model(p,x,diagnostic=True);model.law=Law(root/'law12.npz');after,da=model(p,x,diagnostic=True)
            pert=x.clone();pert[:,6:]=(pert[:,6:]+17)%850;prefix=float((after[:,:6]-model(p,pert)[:,:6]).abs().max());assert prefix<2e-5
            out[str(s)]={'state':a['sha'],'four_bin_nll':summarize(before,y),'twelve_bin_nll':summarize(after,y),'max_abs_logit':(before-after).abs().max().item(),'mean_abs_logit':(before-after).abs().mean().item(),'per_layer_mean_absolute_release_difference':[float((old[...,0]-new[...,0]).abs().mean()) for old,new in zip(db,da)],'four_bin_mean_release':[v[...,0].mean().item() for v in db],'twelve_bin_mean_release':[v[...,0].mean().item() for v in da],'max_twelve_bin_mass_error':float(max((v[...,1]+v[...,2]-1).abs().max() for v in da)),'max_twelve_bin_prefix_error':prefix}
    write(root/'trained_spatial_sensitivity.json',{'rows':rows.tolist(),'target_tokens':int((y!=0).sum()),'same_weights':True,'retrained':False,'by_seed':out})
if __name__=='__main__':main()
