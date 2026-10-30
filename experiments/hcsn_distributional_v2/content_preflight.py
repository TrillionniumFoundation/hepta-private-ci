"""Train-split-only engineering probe; no validation or heldout selection."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import torch
from torch.nn import functional as F

from experiments.hcsn_free_boundary_v1.training import load_split, _gradient_summary
from .model import MODEL_NAMES, build_model


def run(output):
    output = Path(output)
    if output.exists():
        raise FileExistsError("Preserve prior preflight evidence")
    output.parent.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(1)
    root = Path(__file__).resolve().parents[2]
    path = root / "experiments/hcsn_free_boundary_v1/data/study001/selective_copy.npz"
    access = []
    train = load_split(path, "train", access)
    records = []
    started = time.process_time()
    for name in MODEL_NAMES:
        model = build_model(name, 64, 8, seed=9201)
        optimizer = torch.optim.Adam(model.parameters(), lr=0.003)
        initial = {key: value.detach().clone() for key, value in model.named_parameters()}
        generator = torch.Generator().manual_seed(9201+200003)
        rows = []
        for index in range(3):
            begin = time.process_time()
            ids = torch.randint(train["x"].shape[0], (32,), generator=generator)
            x, dt, y = (train[key][ids] for key in ("x", "dt", "y"))
            optimizer.zero_grad(set_to_none=True)
            logits, aux = model(x, dt, return_sequence=True)
            loss = F.cross_entropy(logits.flatten(0, 1), y.flatten(), ignore_index=-100)
            loss.backward()
            groups = _gradient_summary(model)
            unclipped = float(torch.nn.utils.clip_grad_norm_(model.parameters(), 2))
            optimizer.step()
            row = dict(update=index+1, cpu_seconds=time.process_time()-begin,
                       loss=float(loss.detach()), gradients=groups,
                       preclip_gradient_l2=unclipped)
            if "flow_mass" in aux:
                row.update(max_mass_error=float((aux["flow_mass"].detach()-1).abs().max()),
                           min_probability=float(aux["probability"].detach().min()),
                           total_events=float(aux["total_activity"].detach()))
            rows.append(row)
        changes = {group: sum(float((p.detach()-initial[key]).square().sum())
                             for key, p in entries)**0.5
                   for group, entries in model.parameter_groups().items()}
        result = dict(model=name, counts=model.counts(), updates=rows,
                      group_actual_change_l2=changes)
        records.append(result)
        print(json.dumps(dict(model=name, median_step_cpu_seconds=sorted(r["cpu_seconds"] for r in rows)[1],
                              groups_updated=all(x > 0 for x in changes.values()))), flush=True)
    report = dict(schema="hcsn-distribution-content-preflight.v2", access_log=access,
                  data_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                  source_hashes={name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                 for name in ("model.py", "distribution_kernel.py", "content_preflight.py")},
                  train_only=True, records=records, process_cpu_seconds=time.process_time()-started,
                  optimizer="Adam lr=.003 clip2", seed=9201, batch_size=32)
    output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False)+"\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    run(parser.parse_args().output)
