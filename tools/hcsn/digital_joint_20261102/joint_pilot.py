"""Small isolated CPU/gradient/export profile; never a formal efficacy fit."""
import argparse
import json
from pathlib import Path
import time

import numpy as np
import torch
import torch.nn.functional as F

from . import joint_data
from .joint_law import IndependentLaw
from .joint_model import FAMILIES, NumpyPolicy, Policy


def objective(model, rows, protocol):
    output = model.forward_rows(rows)
    mask = torch.tensor([r["legal"] for r in rows], dtype=torch.float64)
    target = torch.tensor([r["q"] for r in rows], dtype=torch.float64)
    posterior = torch.tensor([r["posterior"] for r in rows], dtype=torch.float64)
    mass = torch.tensor([r["teacher_mass"] for r in rows], dtype=torch.float64)
    bank = torch.tensor([r["teacher_bank"] for r in rows], dtype=torch.float64)
    qloss = (((output["q"]-target).square()*mask).sum(-1)/mask.sum(-1)).mean()
    belief = F.binary_cross_entropy_with_logits(output["logit"], posterior)
    kl = (mass*(torch.log(mass.clamp_min(1e-300))-torch.log(output["mass"].clamp_min(1e-300)))).sum(-1).mean()
    bankloss = (output["bank"]-bank).square().mean()
    return qloss+protocol["belief_loss_weight"]*belief+protocol["mass_kl_weight"]*kl+protocol["bank_mse_weight"]*bankloss


def main():
    p = argparse.ArgumentParser(); p.add_argument("stage", choices=("prepare", "profile"))
    p.add_argument("--out", type=Path, required=True); p.add_argument("--source-commit")
    p.add_argument("--data", type=Path); p.add_argument("--family", choices=FAMILIES)
    args = p.parse_args(); torch.set_num_threads(1)
    protocol = json.loads((Path(__file__).with_name("joint_pilot_protocol.json")).read_text())
    args.out.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter(), time.process_time()
    if args.stage == "prepare":
        joint_data.prepare_fit(args.out, 991, protocol, IndependentLaw(protocol["truth_raw"]), args.source_commit)
        result = dict(stage="pilot_prepare", formal=False)
    else:
        data = json.loads(args.data.read_text()); model = Policy(args.family, 991, data["confusion"])
        optimizer = torch.optim.AdamW(model.parameters(), lr=protocol["learning_rate"], weight_decay=protocol["weight_decay"])
        rng = np.random.default_rng(887001); updates = []
        for step in range(protocol["updates"]):
            rows = [data["train"]["rows"][i] for i in rng.integers(len(data["train"]["rows"]), size=protocol["batch_states"])]
            before = time.process_time(); optimizer.zero_grad(set_to_none=True)
            loss = objective(model, rows, protocol); loss.backward()
            finite = all(v.grad is None or bool(torch.isfinite(v.grad).all()) for v in model.parameters())
            if not finite or not bool(torch.isfinite(loss)):
                raise FloatingPointError("nonfinite pilot gradient")
            norm = float(torch.nn.utils.clip_grad_norm_(model.parameters(), protocol["gradient_clip"]))
            optimizer.step(); model.project()
            updates.append(dict(step=step+1, loss=float(loss.detach()), gradient_norm=norm, cpu_seconds=time.process_time()-before))
        export_start = time.process_time(); artifact = model.export([.25,.5,.75,1.,1.5])
        (args.out/"model.json").write_text(json.dumps(artifact, separators=(",", ":"), allow_nan=False)+"\n")
        exported = NumpyPolicy(artifact); maximum = 0.
        for row in data["validation"]["rows"]:
            with torch.no_grad(): output = model.forward_row(row["public"], row["state"])
            prediction = exported.predict(row["public"], row["state"])
            maximum = max(maximum, max(float(np.max(abs(output[k].numpy()-np.asarray(prediction[k])))) for k in ("q", "mass", "bank")))
        if maximum > 2e-10:
            raise AssertionError(("torch-free export mismatch", maximum))
        result = dict(stage="pilot_profile", formal=False, family=args.family, updates=updates,
                      export_and_validation_cpu_seconds=time.process_time()-export_start, max_export_error=maximum,
                      parameters=artifact["parameter_count"])
    result.update(wall_seconds=time.perf_counter()-wall, cpu_seconds=time.process_time()-cpu)
    (args.out/"RESULT.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
