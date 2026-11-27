"""Cross-check the new recurrent composition against independently shipped #7149 primitives."""
import json
import sys
from pathlib import Path
import torch
from model import FeedbackBoundary, GAINS
from qualification.hcsn_closure_20261124.boundary_fix import BoundaryControlHCSN

ROOT=Path(__file__).resolve().parent
torch.set_num_threads(1)
torch.set_num_interop_threads(1)
torch.manual_seed(9281)
x=torch.randn(8,4,6).double().requires_grad_()
results={}
models={}
for arm in GAINS:
    torch.manual_seed(16)
    model=FeedbackBoundary(arm).double()
    full, features,state=model(x,return_features=True,trace=True)
    trace=model.last_trace
    previous,_,mid=model(x[:3],return_features=True)
    remaining,_,end=model(x[3:],state=mid,return_features=True)
    resume_error=float((full-torch.cat((previous,remaining))).abs().max().detach())
    assert resume_error<2e-13
    assert float((state.physical.density-end.physical.density).abs().max().detach())<1e-12
    future=x.detach().clone();future[4:]+=1.
    assert torch.equal(model(future)[:4],full.detach()[:4])
    assert max(f["mass"] for f in trace)<1e-10
    d=torch.autograd.grad((full[-1,:,1]-full[-1,:,0]).sum(),x,retain_graph=False)[0]
    assert d[0].abs().max()>1e-8 and d[-1].abs().max()==0
    silent=model(x,silence_boundary=True)
    d_silent=torch.autograd.grad((silent[-1,:,1]-silent[-1,:,0]).sum(),x)[0]
    assert d_silent.abs().max()==0
    results[arm]={"resume_logits_max_abs_error":resume_error,"future_leakage":0,
       "input_first_frame_gradient_max_abs":float(d[0].abs().max()),
       "input_last_frame_gradient_max_abs":float(d[-1].abs().max()),
       "all_silent_input_gradient_max_abs":float(d_silent.abs().max()),
       "sensor_output_variation":float((full[-1]-full[-1,:1]).abs().max().detach()),
       "last_drift":state.physical.drift.detach().tolist(),"trace":trace}
    models[arm]=model
torch.manual_seed(16)
original=BoundaryControlHCSN(models["zero"].config,channel="boundary_only", control_mode="accumulate",boundary_mode="centered").double()
ref=original(x,return_features=True);candidate=models["zero"](x,return_features=True)
for a,b in zip(ref[:2],candidate[:2]): assert torch.equal(a,b)
g_ref=torch.autograd.grad((ref[0][-1,:,1]-ref[0][-1,:,0]).sum(),x)[0]
g_zero=torch.autograd.grad((candidate[0][-1,:,1]-candidate[0][-1,:,0]).sum(),x)[0]
assert torch.equal(g_ref,g_zero)
zero=results["zero"]
for name,field in (("restore","restoring_rms"),("risk","panic_rms")):
    assert max(r[field] for r in results[name]["trace"])>1e-6
    assert (torch.as_tensor(results[name]["last_drift"])-torch.as_tensor(zero["last_drift"])).abs().max()>1e-7
results["zero_equivalence"]={"logits":"bitwise_equal","latent":"bitwise_equal","input_vjp":"bitwise_equal"}
results["source"]="Same seed, CPU FP64, 8 time steps × 4 randomized six-coordinate sequences; population constants as in plan."
(ROOT/"mechanism_tests.json").write_text(json.dumps(results,indent=2,allow_nan=False)+"\n")
print("four force conditions, reference outputs/gradients, split-state continuation, source isolation and phase checks passed")
