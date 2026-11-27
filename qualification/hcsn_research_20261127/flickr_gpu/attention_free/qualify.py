"""Verify a causal input/output graph, nonzero gradients and an active physical boundary wire."""
import torch
from study import BASE, SRC, ARMS, Captioner, F, write, state_identity, sha

torch.set_num_threads(1);torch.set_num_interop_threads(1);torch.manual_seed(40023)
seed=17011
images=torch.randint(256,(3,64,64,3),dtype=torch.uint8)
tokens=torch.randint(4,3490,(3,13));other=tokens.clone();other[:,5:]=torch.randint(4,3490,(3,8))
result={};init={};common=set()
for arm in ARMS:
    model=Captioner(arm,seed);common.add(state_identity(model,True));init[arm]=state_identity(model)
    assert model.words.weight.data_ptr()==model.head.weight.data_ptr()
    model.eval()
    with torch.no_grad():
        a=model(images,tokens);b=model(images,other)
        causality=float((a[:,:5]-b[:,:5]).abs().max());assert causality<2e-5
        upstream_change=None
        if arm in ('hcsn','no_wire'):
            hidden=torch.randn(3,9,64);lower=torch.randn(3,9,8)*.2
            pa,ma=model.mixers[1](hidden,lower)
            pb,mb=model.mixers[1](hidden,torch.zeros_like(lower))
            upstream_change=float((pa-pb).abs().amax()+(ma-mb).abs().amax())
            assert (upstream_change>1e-6)==(arm=='hcsn')
    model.train();opt=torch.optim.AdamW(model.parameters(),lr=.0005,weight_decay=.01)
    pred=model(images,tokens);loss=F.cross_entropy(pred.transpose(1,2),tokens.roll(-1,1));loss.backward()
    grad=float(torch.nn.utils.clip_grad_norm_(model.parameters(),1));assert grad>0 and torch.isfinite(loss)
    route_grad=sum(float(p.grad.abs().sum()) for layer in model.mixers for p in layer.parameters() if p.grad is not None)
    assert route_grad>0
    if arm in ('hcsn','no_wire'):
        receiver_grad=float(model.mixers[1].receiver.weight.grad.abs().sum())
        assert (receiver_grad>1e-9)==(arm=='hcsn')
    else:receiver_grad=None
    before=model.words.weight.detach().clone();opt.step();assert not torch.equal(before,model.words.weight)
    result[arm]=dict(max_prefix_difference=causality,upstream_mark_intervention=upstream_change,
        gradient_norm=grad,nonzero_mixer_gradient_L1=route_grad,upper_wire_weight_gradient_L1=receiver_grad,
        params=sum(p.numel() for p in model.parameters()),initial=init[arm])
assert len(common)==1 and init['hcsn']==init['no_wire']
write(BASE/'qualification.json',dict(arms=result,shared_common_initial=common.pop(),original_model=sha(SRC/'free_boundary_decoder.py'),qualification=sha(SRC/'qualify.py'),torch=str(torch.__version__),device='cpu'))
print('verified six causal candidates',flush=True)
