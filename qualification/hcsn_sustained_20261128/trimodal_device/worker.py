"""Private full-data single-seed CUDA replication of the shared decoder."""
import ctypes
import ctypes.util
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time

import numpy as np
import torch


def discover():
    driver = {"ctypes_library": ctypes.util.find_library("cuda")}
    try:
        cuda = ctypes.CDLL(driver["ctypes_library"] or "libcuda.so.1")
        driver["cuInit"] = cuda.cuInit(0)
        count = ctypes.c_int()
        driver["cuDeviceGetCount"] = cuda.cuDeviceGetCount(ctypes.byref(count))
        driver["device_count"] = count.value
    except OSError:
        driver["libcuda_load"] = False
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            run = subprocess.run([smi, "--query-gpu=name,memory.total,driver_version",
                                  "--format=csv,noheader"], capture_output=True, text=True, timeout=10)
            driver["nvidia_smi"] = run.stdout.splitlines() if run.returncode == 0 else {"returncode": run.returncode}
        except subprocess.TimeoutExpired:
            driver["nvidia_smi"] = "timeout"
    return dict(torch=str(torch.__version__), compiled_cuda=torch.version.cuda,
                device_count=torch.cuda.device_count(), cuda_available=torch.cuda.is_available(),
                nvidia_smi_present=bool(smi), driver=driver)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fit(folder, seed, arm, x, y, tr, dev, held, modes, vocab):
    from data import START
    from network import architecture
    from train import BATCH, evaluate
    from torch.nn.functional import cross_entropy
    program = time.perf_counter()
    model, width, err = architecture(vocab, arm, seed)
    model = model.to("cuda")
    opt = torch.optim.AdamW(model.parameters(), lr=.002, weight_decay=.01)
    rng = torch.Generator().manual_seed(seed)
    steps = seen = ntoken = 0
    active = 0.
    rows = []
    while len(set().union(*(set(r["labels"]) for r in rows))) < 2:
        order = torch.as_tensor(tr)[torch.randperm(len(tr), generator=rng)]
        for b_cpu in order.split(BATCH):
            batch = b_cpu.to("cuda")
            torch.cuda.synchronize()
            start = time.perf_counter()
            z = model(x[batch])[:, START:]
            t = y[batch]
            loss = cross_entropy(z.reshape(-1, vocab), t.flatten(), ignore_index=-100)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.)
            opt.step()
            torch.cuda.synchronize()
            active += time.perf_counter()-start
            steps += 1
            seen += len(batch)
            ntoken += int((t != -100).sum())
            reached = set().union(*(set(r["labels"]) for r in rows))
            labels = []
            if seen == len(tr) and "epoch1" not in reached:
                labels.append("epoch1")
            if active >= 60 and "time60" not in reached:
                labels.append("time60")
            if labels:
                cp = folder / (arm+"-"+"-".join(labels)+".npz")
                np.savez_compressed(cp, **{k:v.detach().cpu().numpy() for k,v in model.state_dict().items()})
                model.eval()
                nll, prob, pred = evaluate(model, x, y, dev, modes)
                model.train()
                score_file = folder/(cp.stem+"-dev.npz")
                np.savez_compressed(score_file, logp=prob, pred=pred)
                rows.append(dict(labels=labels, steps=steps, examples=seen, targets=ntoken,
                                 update_s=active, elapsed_s=time.perf_counter()-program, dev_nll=nll,
                                 weights=cp.name, weights_sha256=digest(cp), dev_scores=score_file.name,
                                 dev_scores_sha256=digest(score_file)))
            if len(set().union(*(set(r["labels"]) for r in rows))) == 2:
                break
    chosen = min(rows, key=lambda r: np.mean(r["dev_nll"]))
    with np.load(folder/chosen["weights"]) as ck:
        model.load_state_dict({k:torch.from_numpy(v).to("cuda") for k,v in ck.items()})
    model.eval()
    held_nll, prob, pred = evaluate(model, x, y, held, modes)
    score_file = folder/(arm+"-selected-test.npz")
    np.savez_compressed(score_file, logp=prob, pred=pred)
    return dict(arm=arm,seed=seed,width=width,parameters=sum(a.numel() for a in model.parameters()),
                example_device=str(x.device), model_device=str(next(model.parameters()).device),
                physical_interpolation_error=err,rows=rows,selected_weights=chosen["weights"],
                selected_test_nll=held_nll,test_scores=score_file.name,test_sha256=digest(score_file))


def run(src_root, out):
    folder = out/"tri_private_scores"
    folder.mkdir(exist_ok=True)
    report = dict(schema=1,device=discover(),seed=137,arms=["financial","sdpa_matched"],rows=[])
    def publish():
        with tarfile.open(out/"raw.tar.gz", "w:gz") as archive:
            for f in sorted(folder.iterdir()):
                if f.is_file(): archive.add(f,arcname=f.name)
        (out/"result.json").write_text(json.dumps(report,indent=2)+"\n")
    if not (torch.cuda.is_available() and torch.version.cuda):
        report["endpoint"]="requested_cuda_unavailable"
        report["train_updates"]=0
        publish()
        return
    trial=torch.arange(8,device="cuda",dtype=torch.float32)
    result=float(torch.dot(trial,trial)); torch.cuda.synchronize()
    assert result==140.
    report["device"].update(name=torch.cuda.get_device_name(0), actual_dot=result)
    sys.path.insert(0,str(src_root/"hcsn_recurrent_boundary_20261128"/"trimodal_decoder"))
    from data import streams,SHA
    x,y,(tr,dev,held),actors,modes,vocab,_=streams()
    x=x.to("cuda");y=y.to("cuda")
    report["input_sha256"]=SHA
    report["conditional_counts"]=[len(tr),len(dev),len(held)]
    report["recordings"]=len(x)//3
    assert len(x)//3==7442 and len(tr)==14952
    torch.set_num_threads(1)
    for arm in report["arms"]:
        report["rows"].append(fit(folder,137,arm,x,y,tr,dev,held,modes,vocab))
        report["endpoint"]="partial"
        publish()
    report["endpoint"]="cuda_full_epoch_and_sixty_seconds"
    publish()
