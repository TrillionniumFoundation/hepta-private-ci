"""Replay the original feature pipeline and time two fits of the identical readout."""
import hashlib
import json
import os
from pathlib import Path
import platform
import runpy
import statistics
import sys
import time
import zipfile

import numpy as np
import torch

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
import encoder

torch.set_num_interop_threads(1)
clock = time.perf_counter
model_dir = Path(sys.argv[1]).resolve()
os.chdir(root)
stage = root / "work"
stage.mkdir()
archive = root / "evidence/encoder-run.zip"

def file_sha(p):
    return hashlib.file_digest(p.open("rb"), "sha256").hexdigest()

with zipfile.ZipFile(archive) as z:
    for name in ("teacher-fit-smol.json", "teacher-fit-t5.json", "blind.json", "cold-mix.json"):
        (stage / name).write_bytes(z.read(name))
    freeze = json.loads(z.read("freeze.json"))

# Observe the actual original fit pipeline. Preserve each original value and method.
original_ridge = encoder.ridge
seen = []
def capture(x, y):
    result = original_ridge(x, y)
    seen.append((x.copy(), y.copy(), result.copy()))
    return result
encoder.ridge = capture

measurements = {}
def timed(name, method):
    def invoke(self, *args, **kwargs):
        start = clock()
        result = method(self, *args, **kwargs)
        measurements.setdefault(name, []).append(clock() - start)
        return result
    return invoke

encoder.Encoder.__init__ = timed("load", encoder.Encoder.__init__)
encoder.Encoder.features = timed("features", encoder.Encoder.features)
sys.argv = ["fit.py", str(model_dir)]
ctx = runpy.run_path(str(root / "fit.py"))
assert len(seen) == 5
x, y, old_fit = seen[3]  # parent, FLAN, Smol, mix, gate in the pinned original fit.py
assert np.array_equal(old_fit, ctx["vectors"]["mix"])
shared = {"load": measurements["load"][0], "training_features": measurements["features"][0]}
model = ctx["E"]
blind = json.loads((stage / "blind.json").read_bytes())
xx, _, cc = model.features(blind)
old = json.loads((stage / "cold-mix.json").read_bytes())["rows"]
assert [r["id"] for r in old] == [r["id"] for r in blind]
torch.set_num_threads(1)
X = torch.from_numpy(x)
Y = torch.from_numpy(y)
lam = 0.2

def direct():
    gram = X @ X.T
    gram.diagonal().add_(lam)
    return X.T @ torch.linalg.solve(gram, Y), 0

def backward():
    w = torch.zeros(X.shape[1], dtype=X.dtype, requires_grad=True)
    solver = torch.optim.LBFGS([w], lr=1., max_iter=256, max_eval=320,
                               history_size=50, tolerance_grad=1e-9, tolerance_change=1e-14,
                               line_search_fn="strong_wolfe")
    calls = 0
    def closure():
        nonlocal calls
        calls += 1
        solver.zero_grad()
        residual = X @ w - Y
        loss = (residual.square().sum() + lam*w.square().sum()) / 2
        loss.backward()
        return loss
    solver.step(closure)
    return w.detach(), calls

# Warm both libraries on a separate toy parameter, excluding one-time optimizer imports.
toy = torch.ones(1, dtype=torch.float64, requires_grad=True)
opt = torch.optim.LBFGS([toy], max_iter=1)
def warm():
    opt.zero_grad()
    loss = toy.square().sum()
    loss.backward()
    return loss
opt.step(warm)
torch.linalg.solve(torch.ones((1,1), dtype=torch.float64), torch.ones(1, dtype=torch.float64))
runs = []
weights = {}
for rep in range(7):
    order = (("direct",direct),("bp_lbfgs",backward))
    if rep % 2:
        order = tuple(reversed(order))
    for name, solve in order:
        start = clock()
        w, calls = solve()
        seconds = clock() - start
        resid = X @ w - Y
        gradient = X.T @ resid + lam*w
        runs.append(dict(repeat=rep, method=name, seconds=seconds, backward_calls=calls,
                         objective=float((resid.square().sum()+lam*w.square().sum())/2),
                         relative_stationarity=float(torch.linalg.vector_norm(gradient)/
                                                     torch.linalg.vector_norm(X.T @ Y))))
        if name in weights:
            assert np.array_equal(weights[name], w.numpy())
        weights[name] = w.numpy().copy()

base = cc + xx @ ctx["vectors"]["parent"]
ref = np.array([row["answer"] for row in old])
answer = {name:((base + xx @ w)>0).astype(int) for name,w in weights.items()}
medians = {name:statistics.median(r["seconds"] for r in runs if r["method"]==name) for name in weights}
f = sum(shared.values())
rows = [dict(id=r["id"], published=int(t), direct=int(a), bp=int(b))
        for r,t,a,b in zip(blind,ref,answer["direct"],answer["bp_lbfgs"],strict=True)]
report = dict(frozen_encoder=freeze["encoder"], original_panel_archive_sha256=file_sha(archive),
              measurements=shared, feature_extraction_threads=2, device="cpu", torch_threads=torch.get_num_threads(), torch=torch.__version__,
              cpu_name=next((l.split(":",1)[1].strip() for l in Path("/proc/cpuinfo").read_text().splitlines()
                              if l.startswith("model name")),platform.machine()),
              feature_matrix_shape=list(x.shape), matrix_sha256=hashlib.sha256(x.tobytes()).hexdigest(),
              residual_sha256=hashlib.sha256(y.tobytes()).hexdigest(), runs=runs, fit_median_seconds=medians,
              fit_speed_ratio=medians["bp_lbfgs"]/medians["direct"],
              shared_load_and_features_plus_fit_ratio=(f+medians["bp_lbfgs"])/(f+medians["direct"]),
              holdout_rows=len(ref), same_answers=int((answer["direct"]==answer["bp_lbfgs"]).sum()),
              matches_published={k:int((a==ref).sum()) for k,a in answer.items()},
              max_weight_difference=float(abs(weights["direct"]-weights["bp_lbfgs"]).max()),
              max_direct_difference_from_published=float(abs(weights["direct"]-old_fit).max()),
              real_participants=0, rows=rows)
out=Path(os.environ["RUNNER_TEMP"])/"matched-encoder.json"
out.write_text(json.dumps(report,sort_keys=True,indent=2)+"\n")
print(json.dumps({k:v for k,v in report.items() if k not in ("rows","runs","frozen_encoder")}))
