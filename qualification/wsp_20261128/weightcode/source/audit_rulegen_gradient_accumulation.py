"""Post-submission harness audit; does not select or train an experimental arm.

The frozen cloud protocol checks gradient accumulation on 65 already-mastered
rows. Their near-zero loss makes that a weak numerical challenge. This audit
uses fixed rule-generated rows with nonzero base loss, records its later timing,
and checks the same full-token-denominator microbatch accumulation independently.
"""
from __future__ import annotations
import os
for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[key] = "1"
import hashlib, json, sys, time
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/"WeightCode"))
import numpy as np
import torch
import torch.nn.functional as F
from weightcode.baselines.instance_io import load_instance
from weightcode.baselines.fit import seqgrad as SG, scanrefs as R
from weightcode.data import scan as S
from weightcode.common.identity import params_sha256
torch.set_num_threads(1)
torch.set_num_interop_threads(1)
torch.use_deterministic_algorithms(True)
start=time.monotonic()
inst=load_instance(HERE/"WeightCode/reproduction_scan/downloads/hf/weights/instances/ncc5c260f")
generated=R.rulegen_fit_set("addprim_jump","mixed")
# No outcome-based sample search. First 33 and last 32 rows in the pinned generator.
indices=np.r_[np.arange(33),np.arange(len(generated["x"])-32,len(generated["x"]))]
x=torch.from_numpy(generated["x"][indices])
y=torch.from_numpy(generated["y"][indices])
model=SG.rebuild(inst.params)
dense=SG.token_loss(model,x,y)
dense.backward()
reference={k:p.grad.detach().clone() for k,p in model.named_parameters()}
model.zero_grad(set_to_none=True)
denom=int((y!=S.IGNORE).sum())
accum=0.
for first in range(0,len(x),17):
    out=model(x[first:first+17])
    loss=F.cross_entropy(out.reshape(-1,out.shape[-1]),y[first:first+17].reshape(-1),
                         ignore_index=S.IGNORE,reduction="sum")/denom
    loss.backward()
    accum+=float(loss.detach())
per_tensor=[]
for k,p in model.named_parameters():
    diff=(p.grad-reference[k]).abs()
    nontrivial=reference[k].abs()>1e-3
    per_tensor.append({"key":k,"gradient_absmax":float(reference[k].abs().max()),
                       "absolute_error":float(diff.max()),
                       "relative_error_nontrivial":float((diff[nontrivial]/reference[k].abs()[nontrivial]).max()) if nontrivial.any() else 0.,
                       "nontrivial_entries":int(nontrivial.sum())})
absolute=max(r["absolute_error"] for r in per_tensor)
relative=max(r["relative_error_nontrivial"] for r in per_tensor)
passed=absolute<=1e-4 and relative<=1e-3 and abs(accum-float(dense.detach()))<=1e-4
result={"scope":"Post-submission independent nonzero-loss CPU harness audit, not a pre-fit cloud gate and not model-quality evidence",
        "unix_time":time.time(),"script_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "base_params_sha256":inst.params_sha256,"fit_commands_sha256":generated["record"]["commands_sha256"],
        "selected_indices":indices.tolist(),"selected_xy_sha256":params_sha256({"x":x.numpy(),"y":y.numpy()}),
        "torch":torch.__version__,"numpy":np.__version__,"device":"cpu","threads":1,
        "dense_loss":float(dense.detach()),"accumulated_loss":accum,"gradient_absmax_error":absolute,
        "gradient_relative_error_nontrivial":relative,"per_tensor":per_tensor,
        "gradient_forward_rows":130,"optimizer_steps":0,"passed":passed,"wall_seconds":time.monotonic()-start}
target=HERE/"rulegen_gradient_accumulation_audit.json"
if target.exists(): raise RuntimeError("Refuse to overwrite audit evidence")
target.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
print(json.dumps({k:v for k,v in result.items() if k not in ("per_tensor","selected_indices")}))
assert passed
