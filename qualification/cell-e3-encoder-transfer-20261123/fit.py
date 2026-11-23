"""Fit only on authorized training teacher scores; seal before the confirmation seed."""
import importlib.util
import json
from pathlib import Path
import sys
import time
import zipfile

import numpy as np
import torch
from encoder import Encoder, file_sha, ridge
from panel import digest, panel

work = Path("work")
encoder_dir = Path(sys.argv[1])
torch.set_num_threads(2)
source = Path("../cell-e3-native-answer-transfer-20261123")
old_archive = source / "evidence/completion-run.zip"
assert file_sha(old_archive) == "4e9dc2f83b79db9a1076f107d1c610c9b4ad4e61d24d0ed1aaaa53dea870b508"
spec = importlib.util.spec_from_file_location("previous_panel", source / "panel.py")
orig = importlib.util.module_from_spec(spec)
spec.loader.exec_module(orig)
old_rows = [r for r in orig.panel() if r["split"] == "train"]
old_ids = {r["id"] for r in old_rows}
with zipfile.ZipFile(old_archive) as z:
    past = {n: {r["id"]: r for r in json.loads(z.read(f"teacher-fit-{n}.json"))["rows"]
                if r["id"] in old_ids} for n in ("t5","smol")}
data = panel()
assert not any(r["split"] in ("holdout", "composition") for r in data)
new_rows = [r for r in data if r["split"] == "train"]
discovery = [r for r in data if r["split"] == "discovery"]
rehearsal = [r for r in data if r["split"] == "old-train"]
new = {n: {r["id"]: r for r in json.loads((work / f"teacher-fit-{n}.json").read_bytes())["rows"]}
       for n in past}
assert len(old_rows) == 192 and all(len(d) == 192 for d in past.values())
assert all(len(d) == len(discovery) + len(new_rows) for d in new.values())
declared = {n: sum(new[n][r["id"]]["label"] == r["label"] for r in discovery) for n in new}
best = "smol" if declared["smol"] > declared["t5"] else "t5"
domain_records = {}
fixed = {}
for dom in sorted({r["domain"] for r in discovery}):
    rows = [r for r in discovery if r["domain"] == dom]
    d = {n: sum(new[n][r["id"]]["label"] == r["label"] for r in rows) for n in new}
    domain_records[dom] = d
    fixed[dom] = "smol" if d["smol"] > d["t5"] else "t5"
policy = {"fixed": fixed, "best": best, "discovery_counts": domain_records}
clock, cpu = time.perf_counter(), time.process_time()
E = Encoder(encoder_dir)
train = old_rows + new_rows + rehearsal
x, _, cosine = E.features(train)
_, g, _ = E.features(discovery)
vectors = {}
yold = np.array([2*r["label"]-1 for r in rehearsal])
nold = len(yold)
vectors["parent"] = ridge(x[-nold:], yold - cosine[-nold:])
base = cosine + x @ vectors["parent"]
ys = {}
for n in ("t5", "smol"):
    scores = [past[n][r["id"]] for r in old_rows] + [new[n][r["id"]] for r in new_rows]
    y = np.tanh([float(s["mean_logprobs"][1])-float(s["mean_logprobs"][0]) for s in scores])
    ys[n] = np.concatenate([y, yold])
    vectors[n] = ridge(x, ys[n] - base)
vectors["mix"] = ridge(x, (ys["t5"] + ys["smol"]) / 2 - base)
advantage = np.array([int(new["smol"][r["id"]]["label"] == r["label"]) -
                      int(new["t5"][r["id"]]["label"] == r["label"]) for r in discovery])
vectors["gate"] = ridge(g, advantage)
np.savez_compressed(work / "heads.npz", **vectors)
(work / "policy.json").write_text(json.dumps(policy, sort_keys=True))
freeze = dict(encoder=E.info, heads_sha256=file_sha(work / "heads.npz"),
              policy_sha256=file_sha(work / "policy.json"), fitting_panel=digest(data),
              fit_receipts={n:file_sha(work / f"teacher-fit-{n}.json") for n in new},
              inherited_train_archive_sha256=file_sha(old_archive), old_id_count=len(old_ids),
              train=len(new_rows), discovery=len(discovery), rehearsal=len(rehearsal),
              feature_dim=x.shape[1], head_parameters={k:int(v.size) for k,v in vectors.items()},
              encoder_parameters=E.parameter_count, encoder_inputs=E.presentations,
              batch_forwards=E.batches, input_tokens=E.input_tokens,
              wall_seconds=time.perf_counter()-clock, cpu_seconds=time.process_time()-cpu,
              source={p.name:file_sha(p) for p in sorted(Path(".").glob("*.py"))})
(work / "freeze.json").write_text(json.dumps(freeze, sort_keys=True))
print("E3_FROZEN", file_sha(work/"freeze.json"), freeze["feature_dim"], policy)
