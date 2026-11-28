"""Check shared input/output causality and both actual writes using original training images only."""
import argparse
from pathlib import Path
import numpy as np
import torch
from torch.nn import functional as F
from caption_data import load_net,read,sha,sites,write
from fit import direct_step


def main(a):
    torch.set_num_threads(1)
    meta=read(a.parents/'data.json');pixels=np.load(meta['pixels'],mmap_mode='r')
    with np.load(a.parents/'data.npz') as d:
        rows=d['train'][:4];x=torch.tensor(d['inputs'][rows].astype('int64'));y=torch.tensor(d['targets'][rows].astype('int64'))
    pix=torch.tensor(pixels[rows]);report=[]
    for arch in ('literal','smooth'):
        net,reg=load_net(a.parents,arch,109);word,readout=sites(net)
        original=word.weight.detach().clone();p0=readout.weight.detach().clone();hid={}
        def collect(_,inp,out):hid['actual']=out.detach().clone()
        hook=net.final.register_forward_hook(collect)
        with torch.no_grad():
            z0=net(pix,x);h0=hid['actual']
            delta=torch.randn(original.shape,generator=torch.Generator().manual_seed(1971))*.003
            word.weight.add_(delta)
            both=net(pix,x);h1=hid['actual']
            word.weight.copy_(original)
            offset=F.embedding(x,delta)
            input_hook=word.register_forward_hook(lambda _,inp,out:out+offset)
            actual_input=net(pix,x)
            input_hook.remove()
            output_only=F.linear(h0,original+delta)
            predicted=F.linear(h1,original+delta)
            reconstructed=actual_input + (output_only-z0)+F.linear(h1-h0,delta)
            hook.remove()
            assert torch.allclose(both,predicted,atol=2e-6,rtol=1e-5)
            assert torch.allclose(both,reconstructed,atol=2e-5,rtol=1e-5)
            accepted=direct_step(net,(pix,x,y),'flow')
            changed=net(pix,x)
            tokenmask=y!=0
            report.append(dict(arch=arch,parent=reg['sha'],source_training_row=rows.tolist(),
                    input_site_rms=float((actual_input-z0).square().mean().sqrt()),
                    output_site_rms=float((output_only-z0).square().mean().sqrt()),
                    joint_rms=float((both-z0).square().mean().sqrt()),
                    shared_formula_error=float((both-reconstructed).abs().max()),argmax_unchanged_tested=False,
                    forward_step_accepted=accepted,changed_token_weights=float((word.weight-original).norm()),
                    changed_sixth_hidden_projection=float((readout.weight-p0).norm()),
                    before=float(F.cross_entropy(z0[tokenmask],y[tokenmask])),after=float(F.cross_entropy(changed[tokenmask],y[tokenmask]))))
    write(a.result,report)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('parents',type=Path);p.add_argument('result',type=Path)
    main(p.parse_args())
