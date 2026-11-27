"""Causal multilevel gradients, cold recovery and local write constraints."""
import copy,io,json
from pathlib import Path
import torch
from literal.streaming import HeptaContinuousSpikingNetwork,StreamState,Population,inverse_local_drive
from literal.cell import LiteralCell
ROOT=Path(__file__).resolve().parent
def main():
    torch.set_num_threads(1);torch.manual_seed(7717)
    ref=LiteralCell();n=HeptaContinuousSpikingNetwork(widths=(8,));n.layers[0].load_state_dict(ref.state_dict())
    x=torch.randn(11,5,6,dtype=torch.float64,requires_grad=True)
    y=ref(x);z,_=n(x);g,=torch.autograd.grad(y[-1].sum(),x);g2,=torch.autograd.grad(z[-1].sum(),x)
    result={'single_layer_logit_diff':float((y-z).abs().max().detach()),'single_layer_input_grad_diff':float((g-g2).abs().max())}
    for widths in [(8,8),(8,12,6)]:
        model=HeptaContinuousSpikingNetwork(widths=widths)
        all_out,all_state=model(x)
        a,st=model(x[:4]);b,end=model(x[4:],st)
        y=torch.cat((a,b));assert end.tick==len(x)
        diff=float((y-all_out).abs().max().detach())
        gg,=torch.autograd.grad(y[-1].sum(),x,retain_graph=True);g1,=torch.autograd.grad(all_out[-1].sum(),x)
        silent,_=model(x,mute_links=True);gs,=torch.autograd.grad(silent[-1].sum(),x,allow_unused=True)
        # Store only tensors plus primitive metadata for an external weights-only load.
        buf=io.BytesIO();torch.save({'model':model.state_dict(),'state':[[t.detach() for t in p] for p in st.populations],'tick':st.tick},buf);buf.seek(0)
        sd=torch.load(buf,weights_only=True);nextmodel=HeptaContinuousSpikingNetwork(widths=widths);nextmodel.load_state_dict(sd['model'])
        tail,_=nextmodel(x[4:].detach(),StreamState(sd['tick'],tuple(Population(*p) for p in sd['state'])))
        eps=1e-5
        idx=tuple(int(v) for v in torch.unravel_index(gg.abs().argmax(),gg.shape))
        with torch.no_grad():
            v=x.detach().clone();v[idx]+=eps;p,_=model(v);v[idx]-=2*eps;m,_=model(v);fd=float((p[-1].sum()-m[-1].sum())/(2*eps))
        result[str(widths)]={'chunk_logits':diff,'chunk_grad':float((g1-gg).abs().max()),'first_grad_max':float(gg[0].abs().max()),'last_grad_max':float(gg[-1].abs().max()),'silent_grad':float(gs.abs().max()) if gs is not None else 0.,'cold_resume':float((b-tail).abs().max().detach()),'central_difference':abs(fd-float(gg[idx])),'tick':end.tick}
        assert diff<1e-12 and result[str(widths)]['cold_resume']<1e-12 and result[str(widths)]['central_difference']<1e-7
    law=n.layers[0].law
    expected=torch.linspace(-2,2,31,dtype=torch.float64)
    P=law.p.P0*(1+.28*expected.tanh());B=law.boundary(P)
    V=law.B0*torch.full_like(B,1.5)
    target=law.passage((V/B).log(),1)
    got=inverse_local_drive(law,V,target)
    c=.28*law.bp*law.p.P0/law.B0
    carrier=(B/law.B0).log();direct=torch.log1p(c*expected.tanh())
    rejected=False
    try:inverse_local_drive(law,V,torch.full_like(V,.999999))
    except ValueError:rejected=True
    result['local_inverse']={'max_drive_error':float((got-expected).abs().max()),'carrier_simple_gate_error':float((carrier-direct).abs().max()),'infeasible_rejected':rejected,'gate_constant':c}
    assert (got-expected).abs().max()<2e-12 and rejected
    (ROOT/'stream_checks.json').write_text(json.dumps(result,indent=2));print(result,flush=True)
if __name__=='__main__':main()
