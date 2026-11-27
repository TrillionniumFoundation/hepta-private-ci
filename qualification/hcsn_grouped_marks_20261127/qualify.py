"""Check source compatibility, four-coordinate routing, finite gradients, and real device computation."""
import argparse,hashlib,json,math,time
from pathlib import Path

import torch
from grouped_router import ARMS,build_model,grouped_mark


def state_signature(model, skip_router=False):
    h=hashlib.sha256()
    for name,val in model.state_dict().items():
        if skip_router and name.startswith('router.'):continue
        h.update(name.encode());h.update(val.detach().contiguous().cpu().numpy().tobytes())
    return h.hexdigest()


def run(device):
    torch.set_num_threads(1)
    torch.manual_seed(880099)
    tiny=torch.randn((3,4,16),device=device,dtype=torch.float64)
    hazards=[torch.sigmoid(torch.randn((3,1),device=device,dtype=torch.float64)).expand(3,4) for _ in range(3)]
    reference=torch.zeros_like(tiny[:,0]);rem=torch.ones_like(hazards[0][:,:1])
    for t,release in enumerate(hazards):
        mass=rem*release[:,:1];reference+=tiny[:,t]*mass;rem-=mass
    reference+=tiny[:,-1]*rem
    error=float((grouped_mark(tiny,hazards)-reference).abs().max())
    assert error<1e-12
    content=torch.tensor([[[1.,1.,1.,1.],[0.,0.,0.,0.],[0.,0.,0.,0.],[0.,0.,0.,0.]]],device=device)
    zero=torch.zeros((1,4),device=device);q=torch.tensor([[.9,.1,.1,.1]],device=device)
    a=grouped_mark(content,[q,zero,zero]);b=grouped_mark(content,[torch.roll(q,1,1),zero,zero])
    assert torch.equal(q.mean(1),torch.roll(q,1,1).mean(1)) or abs(float(q.mean()-torch.roll(q,1,1).mean()))<1e-6
    assert float((a-b).abs().max())>.79
    record={}
    images=torch.randint(0,256,(3,64,64,3),device=device,dtype=torch.uint8)
    tokens=torch.randint(0,3490,(3,31),device=device)
    for arm in ARMS:
        torch.manual_seed(6259);model=build_model(arm,3490).to(device)
        initial=state_signature(model);common=state_signature(model,True)
        pred=model(images,tokens)
        assert pred.shape==(3,31,3490) and torch.isfinite(pred).all()
        loss=torch.nn.functional.cross_entropy(pred.transpose(1,2),tokens)
        loss.backward()
        peak=0.
        for p in model.parameters():
            if p.grad is not None:
                assert torch.isfinite(p.grad).all()
                peak=max(peak,float(p.grad.abs().max()))
        assert peak>0
        grad=(float(model.router.drive.weight.grad.norm()) if hasattr(model.router,'drive') else None)
        if grad is not None:assert grad>0
        n_visual=model.router(model.patch(images.permute(0,3,1,2).float()/127.5-1).flatten(2).transpose(1,2)+model.image_pos).shape[1]
        assert n_visual==(16 if arm=='dense' else 4)
        record[arm]=dict(whole_state_sha256=initial,common_state_sha256=common,parameters=sum(x.numel() for x in model.parameters()),
                         marks=n_visual,drive_gradient_norm=grad,peak_parameter_abs_grad=peak)
    assert len({v['common_state_sha256'] for v in record.values()})==1
    assert record['hcsn']['whole_state_sha256']==record['grouped_hcsn']['whole_state_sha256']
    return dict(device=device,device_name=torch.cuda.get_device_name() if device=='cuda' else 'cpu',
            torch=str(torch.__version__),equal_hazard_max_error=error,marked_swap_output_gap=float((a-b).abs().max()),arms=record)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('device',choices=('cuda','cpu'));p.add_argument('destination',type=Path)
    a=p.parse_args();a.destination.write_text(json.dumps(run(a.device),sort_keys=True,indent=2)+'\n')
