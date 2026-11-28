"""Recompute every reported contrast from saved clip-level values with NumPy alone."""
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
summary = json.loads((ROOT / "terminal.json").read_text())
with (ROOT / "per_clip.npz").open("rb") as file:
    assert hashlib.file_digest(file,"sha256").hexdigest() == summary["per_clip_sha256"]
with np.load(ROOT / "per_clip.npz") as data:
    y, ids = data["labels"], data["ids"]
    actor = np.array([v.split("_")[0] for v in ids])
    who = np.unique(actor)
    choose = np.random.default_rng(91363).integers(len(who),size=(4000,len(who)))
    n = np.array([np.sum(actor==k) for k in who])
    assert (len(ids),len(who))==(1311,16)
    for method, rows in summary["methods"].items():
        for mode, reported in rows.items():
            def vals(variant, key):
                return np.stack([data[f"{method}-{seed}__{variant}__{key}"] for seed in (137,311,557)])
            loss = vals(mode,"losses")
            pred = vals(mode,"top1")
            delta = (loss-vals("intact","losses")).mean(0)
            sums = np.array([delta[actor==k].sum() for k in who])
            ci = np.quantile(sums[choose].sum(1)/n[choose].sum(1),[.025,.975])
            np.testing.assert_allclose(
                [loss.mean(), (pred==y).mean(), delta.mean(), (pred!=vals("intact","top1")).mean(),
                 vals(mode,"absolute_logit_change").mean(), *ci],
                [reported["nll"],reported["top1"],reported["nll_change"],reported["changed_top1"],
                 reported["mean_absolute_logit_change"],*reported["actor_ci95"]],rtol=1e-12,atol=1e-14)
print("Verified all 35 method/intervention summaries, 105 model-condition pairs, and 1,311 aligned held-out clips.")
