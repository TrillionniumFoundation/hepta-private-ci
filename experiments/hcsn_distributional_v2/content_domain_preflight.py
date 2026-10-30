"""Train-only integration audit of all six duration domains before content002.

The exact train row with the largest duration is always included. The source
timing generator also permits a single duration approaching32, so that regime
is tested explicitly rather than treating the observed train maximum as a law.
No validation, test or OOD arrays are opened by this program.
"""

import argparse
import gc
import hashlib
import json
from pathlib import Path
import resource
import time
import traceback

import torch
from torch.nn import functional as F

from experiments.hcsn_free_boundary_v1.training import load_split, _gradient_summary
from .model import DISTRIBUTION_ARMS, MODEL_NAMES, build_model


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = Path(__file__).resolve().parent
TASKS = ("selective_copy", "mqar", "irregular", "mnist", "fsdd", "multimodal_select")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inspect_probability(aux):
    if "probability" not in aux:
        return {}
    mass_error = float((aux["flow_mass"].detach()-1).abs().max())
    minimum = float(aux["probability"].detach().min())
    assert bool(torch.isfinite(aux["probability"]).all()) and minimum >= 0
    assert mass_error <= 1e-4, "registered probability tolerance"
    return dict(max_mass_error=mass_error, min_probability=minimum,
                total_expected_events=float(aux["total_activity"].detach()))


def update(model, optimizer, x, dt, y):
    before = {key: p.detach().clone() for key, p in model.named_parameters()}
    started = time.process_time()
    optimizer.zero_grad(set_to_none=True)
    logits, aux = model(x, dt, return_sequence=True)
    assert bool(torch.isfinite(logits).all())
    loss = F.cross_entropy(logits.flatten(0, 1), y.flatten(), ignore_index=-100)
    loss.backward()
    gradients = _gradient_summary(model)
    assert all(p.grad is not None and bool(torch.isfinite(p.grad).all())
               for p in model.parameters()), "finite connected task gradients"
    unclipped = float(torch.nn.utils.clip_grad_norm_(model.parameters(), 2))
    optimizer.step()
    cpu = time.process_time()-started
    changes = {group: sum(float((p.detach()-before[name]).square().sum())
                         for name, p in entries)**.5
               for group, entries in model.parameter_groups().items()}
    assert all(value > 0 for value in changes.values()), "actual task-only group learning"
    return dict(training_cpu_seconds=cpu, loss=float(loss.detach()),
                gradients=gradients, preclip_gradient_l2=unclipped,
                actual_parameter_group_change_l2=changes, **inspect_probability(aux))


def run(output):
    output = Path(output)
    if output.exists():
        raise FileExistsError("Preserve all prior preflight evidence")
    output.parent.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    started = time.process_time()
    index_path = ROOT / "experiments/hcsn_free_boundary_v1/data/study001/INDEX.json"
    index = json.loads(index_path.read_bytes())
    report = dict(schema="hcsn-content-domain-preflight.v2", train_only=True, passed=False,
                  access_log=[], tasks=[], stress=[], long_sequence=[],
                  source_sha256={name: digest(PACKAGE / name) for name in
                                 ("model.py", "distribution_kernel.py", "content_domain_preflight.py")},
                  source_timing_contract="32 positive lognormal gaps normalized to total32; observed maxima are not upper bounds",
                  seed=9201, batch_size=32, optimizer="Adam lr=.003 clip2; task cross entropy only")
    try:
        for task in TASKS:
            path = index_path.parent / index[task]["path"]
            access = []
            data = load_split(path, "train", access)
            report["access_log"].append(dict(task=task, events=access))
            assert bool(torch.isfinite(data["dt"]).all()) and bool((data["dt"] >= 0).all())
            ids = torch.argsort(data["dt"].max(1).values, descending=True, stable=True)[:32]
            x, dt, y = (data[key][ids] for key in ("x", "dt", "y"))
            assert float(dt.max()) == float(data["dt"].max())
            row = dict(task=task, data_sha256=digest(path), train_samples=len(data["x"]),
                       min_dt=float(data["dt"].min()), max_dt=float(data["dt"].max()),
                       selected_train_indices=ids.tolist(), models=[])
            for name in MODEL_NAMES:
                model = build_model(name, x.shape[-1], index[task]["output_dim"], seed=9201)
                optimizer = torch.optim.Adam(model.parameters(), lr=.003)
                updates = [update(model, optimizer, x, dt, y) for _ in range(2)]
                row["models"].append(dict(model=name, counts=model.counts(), updates=updates))
                del model, optimizer
                gc.collect()
            report["tasks"].append(row)
            print(json.dumps(dict(task=task, max_train_dt=row["max_dt"], models_passed=len(row["models"]))), flush=True)
            if task == "mnist":
                stress_dt = torch.full((2, 32), .0001)
                stress_dt[:, 0] = 32-31*.0001
                stress_dt[1] = 1
                for name in DISTRIBUTION_ARMS:
                    model = build_model(name, x.shape[-1], index[task]["output_dim"], seed=9201)
                    optimizer = torch.optim.Adam(model.parameters(), lr=.003)
                    record = update(model, optimizer, x[:2], stress_dt, y[:2])
                    report["stress"].append(dict(model=name, max_dt=float(stress_dt.max()),
                                                row_totals=stress_dt.sum(1).tolist(), update=record))
                    del model, optimizer
                    gc.collect()
            if task == "selective_copy":
                long_ids = torch.arange(128)
                long_x = data["x"][long_ids].repeat(1, 2, 1)
                long_dt = data["dt"][long_ids].repeat(1, 2)
                for name in DISTRIBUTION_ARMS:
                    model = build_model(name, x.shape[-1], index[task]["output_dim"], seed=9201)
                    with torch.no_grad():
                        logits, aux = model(long_x, long_dt, return_sequence=True)
                        assert bool(torch.isfinite(logits).all())
                        report["long_sequence"].append(dict(model=name, shape=list(logits.shape),
                                                            **inspect_probability(aux)))
                    del model, logits, aux
                    gc.collect()
            del data
        assert all(digest(PACKAGE / name) == value for name, value in report["source_sha256"].items())
        assert len(report["tasks"]) == 6 and len(report["stress"]) == len(DISTRIBUTION_ARMS)
        report["passed"] = True
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        report["traceback"] = traceback.format_exc()
        raise
    finally:
        report["process_body_cpu_seconds"] = time.process_time()-started
        report["peak_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
        output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False)+"\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    run(parser.parse_args().output)
