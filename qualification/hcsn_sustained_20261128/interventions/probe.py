"""Evaluate explicit boundary communication and price dependence in frozen encoders."""
import argparse
import contextlib
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
import torch
from torch.nn import functional as F

from direct import parameters, make_net
from study import Data, HASHES, digest, write_json

MODES = {
    "intact": ("intact", "intact"),
    "wire_av": ("wire", "intact"),
    "wire_gallery": ("intact", "wire"),
    "wire_both": ("wire", "wire"),
    "equity_both": ("no_E", "no_E"),
    "loss_both": ("no_L", "no_L"),
    "prices_both": ("no_prices", "no_prices"),
}


@contextlib.contextmanager
def intervene(net, mode):
    hooks = []
    previous = [m.kind for m in net.mixer]
    try:
        for layer in net.mixer:
            if mode == "wire" and layer.wire is not None:
                hooks.append(layer.wire.register_forward_hook(
                    lambda module, args, output: torch.zeros_like(output)))
            elif mode in ("no_E", "no_L", "no_prices"):
                layer.kind = mode
        yield
    finally:
        for hook in hooks:
            hook.remove()
        for layer, kind in zip(net.mixer, previous):
            layer.kind = kind


@torch.no_grad()
def components(net, data, mode):
    with intervene(net, mode):
        txt = net.encode(net.text(data.tokens))
        av = [net.encode(net.front(data.v[rows], data.audio[rows]))
              for rows in np.array_split(data.test, (len(data.test) + 31) // 32)]
    return av, txt


def actor_summary(probes, intact, same, labels, actors):
    who = np.unique(actors)
    ix = np.random.default_rng(91363).integers(len(who), size=(4000,len(who)))
    count = np.array([(actors == a).sum() for a in who])
    rows = {}
    for method, model in probes.items():
        rows[method] = {}
        for name in MODES:
            seeds = sorted(model)
            losses = np.stack([model[s][name]["losses"] for s in seeds])
            delta = losses - np.stack([intact[method][s] for s in seeds])
            mean_by_clip = delta.mean(0)
            sums = np.array([mean_by_clip[actors == a].sum() for a in who])
            boot = sums[ix].sum(1) / count[ix].sum(1)
            rows[method][name] = dict(
                nll=float(losses.mean()), nll_change=float(delta.mean()),
                actor_ci95=np.quantile(boot,[.025,.975]).tolist(),
                top1=float(np.mean([model[s][name]["pred"] == labels for s in seeds])),
                changed_top1=float(np.mean([model[s][name]["pred"] != same[method][s] for s in seeds])),
                mean_absolute_logit_change=float(np.mean([model[s][name]["absolute"] for s in seeds])))
    return rows


def run(root, edit, out):
    out.mkdir(exist_ok=True, parents=True)
    for f, h in HASHES.items():
        if digest(root / f) != h:
            raise ValueError(f)
    sys.path.insert(0, str(root / "src"))
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    data = Data(root)
    seal = json.loads((edit / "seal.json").read_text())
    original = json.loads((edit / "terminal.json").read_text())
    if digest(edit / "seal.json") != original["seal_sha256"] or len(seal) != 15:
        raise ValueError("original seal")
    picks = {k:min(rr, key=lambda r:(r["development_nll"],r["steps"])) for k,rr in seal.items()}
    write_json(out / "picks.json", {k:{"file":v["path"],"sha256":v["sha256"]} for k,v in picks.items()})
    labels = data.y[data.test].numpy()
    probes, intact, same, raw, checks = {}, {}, {}, {}, {}
    times = {}
    for group, best in picks.items():
        start = time.perf_counter()
        method, seed = best["method"], best["seed"]
        loc = edit / best["path"]
        if digest(loc) != best["sha256"]:
            raise ValueError("weight mismatch")
        net = make_net(root, data, seed).eval()
        weights = torch.load(loc, map_location="cpu", weights_only=True)
        with torch.no_grad():
            for k, m in parameters(net).items():
                m.copy_(weights[k])
        with np.load(loc.parent / "cold.npz") as a:
            recorded = a["scores"]
            if not np.array_equal(a["labels"], labels) or not np.array_equal(a["ids"], data.names[data.test]):
                raise ValueError("unaligned scores")
        base_av, base_txt = components(net, data, "intact")
        original_z = torch.cat([12 * (z @ base_txt.T) for z in base_av]).numpy()
        if not np.array_equal(original_z, recorded):
            raise ValueError(f"intact replay mismatch for {group}, maximum {abs(original_z - recorded).max()}")
        checks[group] = hashlib.sha256(original_z.tobytes()).hexdigest()
        cache = {"intact":(base_av,base_txt)}
        table = {}
        for name, (av_mode, txt_mode) in MODES.items():
            for needed in {av_mode, txt_mode}:
                if needed not in cache:
                    cache[needed] = components(net, data, needed)
            txt = cache[txt_mode][1]
            scores = torch.cat([12 * (z @ txt.T) for z in cache[av_mode][0]])
            loss = F.cross_entropy(scores.double(), torch.as_tensor(labels), reduction="none").numpy()
            pred = scores.argmax(1).numpy()
            absolute = float(np.abs(scores.numpy().astype(np.float64) - original_z).mean())
            table[name] = dict(losses=loss, pred=pred, absolute=absolute)
            raw[group + "__" + name + "__losses"] = loss
            raw[group + "__" + name + "__top1"] = pred
            raw[group + "__" + name + "__absolute_logit_change"] = np.array(absolute)
        intact.setdefault(method,{})[seed] = table["intact"]["losses"]
        same.setdefault(method,{})[seed] = table["intact"]["pred"]
        probes.setdefault(method,{})[seed] = table
        times[group] = time.perf_counter()-start
        print(group, len(times), round(times[group],2),flush=True)
    actors = data.actors[data.test]
    np.savez_compressed(out / "per_clip.npz", ids=data.names[data.test], labels=labels, **raw)
    write_json(out / "terminal.json", dict(
        methods=actor_summary(probes,intact,same,labels,actors),
        groups=len(picks), interventions=len(MODES)-1, per_clip_sha256=digest(out/"per_clip.npz"),
        original_seal_sha256=digest(edit/"seal.json"), selection_sha256=digest(out/"picks.json"),
        replayed_float32_raw_logits=len(picks)*len(labels)*data.tokens.shape[0],
        original_unmodified_logits_sha256=checks, per_group_seconds=times,
        torch=str(torch.__version__), clips=len(labels), actors=len(np.unique(actors))))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root",type=Path)
    parser.add_argument("edit",type=Path)
    parser.add_argument("out",type=Path)
    args = parser.parse_args()
    run(args.root.resolve(), args.edit.resolve(), args.out.resolve())
