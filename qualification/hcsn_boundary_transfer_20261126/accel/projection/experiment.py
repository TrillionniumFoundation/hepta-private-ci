"""Projection-constrained readout edit on the sealed N8 RAVDESS parents."""
import argparse
from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

import numpy as np
import torch

METHODS = ("keep", "direct", "exact", "weak")
SEEDS = (47, 83, 137)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    path.write_text(json.dumps(data, sort_keys=True, indent=2, allow_nan=False) + "\n")


def margin(logits):
    return (logits[:, 1] - logits[:, 0]).double()


def features(net, source):
    xs, base, _, _ = source
    batch, ticks, choices, width = xs.shape
    sequence = xs.permute(1, 0, 2, 3).reshape(ticks, batch * choices, width)
    state = None
    for tick in sequence:
        if state is not None:
            centered = state.message[:, 0] - net.body.fixed_boundary
            state = replace(state, message=torch.cat((centered[:, None], state.message[:, 1:]), dim=1))
        logits, final_features, state = net.body(tick[None], state=state, return_features=True)
    physical_margin = margin(logits[-1]).float().reshape(batch, choices)
    hidden = final_features[-1].reshape(batch, choices, -1)
    return (hidden[:, 1] - hidden[:, 0]).double(), margin(base + physical_margin)


def subspaces(anchor):
    _, s, vh = torch.linalg.svd(anchor, full_matrices=False)
    if anchor.shape[0] < anchor.shape[1]:
        raise ValueError("Full right singular basis required")
    tol = max(anchor.shape) * torch.finfo(anchor.dtype).eps * s.max()
    keep_exact = s <= tol
    keep_weak = s.square() / anchor.shape[0] < .01
    p = torch.eye(anchor.shape[1], dtype=anchor.dtype, device=anchor.device)
    spaces = {"keep": p[:, :0], "direct": p, "exact": vh[keep_exact].T, "weak": vh[keep_weak].T}
    return spaces, {"singular_values": s.tolist(), "exact_tolerance": tol.item(),
                    "machine_eps32_rank": int((s > max(anchor.shape)*torch.finfo(torch.float32).eps*s.max()).sum()),
                    "null_dimensions": {k: v.shape[1] for k, v in spaces.items()}}


def run(stage, base, out):
    sys.path.insert(0, str(base))
    reg = base / "speech_v2"
    module = importlib.util.spec_from_file_location("sealed_profile", reg/"semantic_executor.py")
    profile = importlib.util.module_from_spec(module)
    module.loader.exec_module(profile)
    device = profile.device()
    torch.set_num_threads(1)
    parents = base/"neural_run"
    parent_seal = json.loads((parents/"seal.json").read_text())
    train_raw = profile.raw(reg, "train")
    stats = (train_raw[0].mean(axis=(0, 1, 2)),
             np.maximum(train_raw[0].std(axis=(0, 1, 2)), .001),
             np.float32(max(train_raw[1][:, -1].std(), .001)))
    batch = lambda split: profile.normalized(profile.raw(reg, split), stats)
    result = {"method": "constrained frozen-readout ridge", "device": device, "seeds": {},
              "source": {x: sha(reg/x) for x in ["semantic_executor.py","frontend_receipt.json"]}}
    if stage == "fit":
        out.mkdir(exist_ok=False)
        train, anchor = batch("train"), batch("dev")
        internal = anchor[0].reshape(-1, anchor[0].shape[-1]).double()
        _, result["internal_sender_input_keys"] = subspaces(internal)
        result["internal_sender_input_keys"]["shape"] = list(internal.shape)
        seal = {}
    else:
        seal = json.loads((out/"weights.json").read_text())
        panels = {key: batch(key) for key in ("dev", "test", "retain")}
    with torch.inference_mode():
        for seed in SEEDS:
            key = "centered_" + str(seed)
            path = parents/(key+".pt")
            assert sha(path) == parent_seal[key]
            net = profile.Hybrid("centered").cuda().eval()
            state = torch.load(path, map_location="cuda", weights_only=True)
            net.load_state_dict(state)
            row = {"parent": sha(path)}
            if stage == "fit":
                t = time.perf_counter()
                x, m = features(net, train)
                a, _ = features(net, anchor)
                scale = x.square().mean(0).sqrt().clamp_min(1e-4)
                x, a = x/scale, a/scale
                target = (2*train[2]-1).double()-m
                spaces, row["span"] = subspaces(a)
                row["edit_anchor_shape"] = [list(x.shape), list(a.shape)]
                torch.cuda.synchronize()
                row["feature_projection_seconds"] = time.perf_counter()-t
                for method in METHODS:
                    net.load_state_dict(state)
                    space = spaces[method]
                    torch.cuda.synchronize()
                    start = time.perf_counter()
                    w = torch.zeros_like(scale)
                    if space.shape[1]:
                        design = x @ space
                        eye = torch.eye(space.shape[1], dtype=x.dtype, device=x.device)
                        gram = design.T@design/len(x)+.5*eye
                        w = space@torch.linalg.solve(gram,design.T@target/len(x))
                    d = (w/scale/2).to(net.head.weight)
                    net.head.weight[1].add_(d)
                    net.head.weight[0].sub_(d)
                    torch.cuda.synchronize()
                    elapsed = time.perf_counter()-start
                    file = out/(key+"_"+method+".pt")
                    torch.save(net.state_dict(),file)
                    seal[file.name] = sha(file)
                    row[method] = {"fit_objective": ((x@w-target).square().mean()/2+.25*w.square().sum()).item(),
                                   "weight_change_norm": (d.norm()*2**.5).item(),
                                   "predicted_max_anchor_shift": (a@w).abs().max().item(),
                                   "solve_plus_write_seconds": elapsed}
            else:
                originals = {k: net(*v[:2]).clone() for k,v in panels.items()}
                for method in METHODS:
                    file = out/(key+"_"+method+".pt")
                    assert sha(file) == seal[file.name]
                    net.load_state_dict(torch.load(file, map_location="cuda", weights_only=True))
                    row[method] = {}
                    for k,v in panels.items():
                        scores = net(*v[:2])
                        delta = margin(scores)-margin(originals[k])
                        row[method][k] = {"n": len(delta), "correct": int((scores.argmax(1)==v[2]).sum()),
                                          "brier": profile.scores(scores,v[2])["brier"],
                                          "max_abs_margin_shift": delta.abs().max().item(),
                                          "rms_margin_shift": delta.square().mean().sqrt().item(),
                                          "margins": margin(scores).tolist(), "labels": v[2].tolist(),
                                          "groups": v[3]}
            result["seeds"][str(seed)] = row
    if stage == "fit":
        save(out/"weights.json",seal)
    save(out/(stage+".json"),result)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=["fit","eval"])
    p.add_argument("base", type=Path)
    p.add_argument("out", type=Path)
    a=p.parse_args()
    run(a.stage,a.base.resolve(),a.out.resolve())
