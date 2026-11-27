"""Numerical checks separate from model quality or data-dependent fitting."""
import argparse
import json
import torch
from model import ARMS, Captioner, LawTable
from parent_cell import Published

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--device',default='cpu')
    args=p.parse_args()
    torch.set_num_threads(1)
    law=Published()
    table=LawTable()
    x=torch.linspace(.0001,1.9999,4096,dtype=torch.float64)
    drive=torch.linspace(-1,1,len(x),dtype=torch.float64)
    principal=law.p.P0*(1+.28*drive)
    a,f=law.values(x,principal)
    eq,slope,year,quarter,reset=table.lookup(x.float()).unbind(-1)
    error={'equity':float((a-eq.double()-slope.double()*(principal-law.p.P0)).abs().max()),
           'year':float((f-year).abs().max()),'quarter':float((law.passage(x,.25)-quarter).abs().max()),
           'step':float((law.move_mean(x)-reset).abs().max())}
    assert error['equity']<.001 and max(error[k] for k in ('year','quarter','step'))<2e-6,error
    assert torch.allclose(table.lookup(torch.tensor([-.4]))[0,2:4],torch.ones(2),atol=1e-7)
    common=None;stats={}
    for arm in ARMS:
        torch.manual_seed(5483);m=Captioner(arm,503).to(args.device)
        shared={k:v.detach().cpu() for k,v in m.state_dict().items() if not k.startswith('router.')}
        if common is None:common=shared
        else:assert all(torch.equal(shared[k],v) for k,v in common.items())
        torch.manual_seed(7531)
        im=torch.randint(256,(4,64,64,3),device=args.device,dtype=torch.uint8)
        tokens=torch.randint(503,(4,31),device=args.device)
        old=m(im,tokens)
        altered=tokens.clone();altered[:,16:]=(altered[:,16:]+31)%503
        assert torch.equal(m(im,altered)[:,:16],old[:,:16]),arm
        loss=old.square().mean();loss.backward()
        derivatives=[g.grad.norm().item() for g in m.router.parameters()]
        assert torch.isfinite(loss).item() and all(torch.isfinite(q.grad).all() for q in m.parameters() if q.grad is not None)
        if arm in ('hcsn','smooth','lif'):assert any(e>0 for e in derivatives)
        stats[arm]={'parameters':sum(v.numel() for v in m.parameters()),'router_gradient_norms':derivatives}
    print(json.dumps({'device':args.device,'reference_grid':len(x),'lookup_max_abs':error,'causality':'exact-prefix','shared_init':'identical','probe_vocab':503,'arms':stats},indent=2))

if __name__=='__main__':main()
