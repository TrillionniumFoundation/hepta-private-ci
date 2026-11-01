"""Retained development-only addressing convergence trial; never confirmation."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch
from torch.nn import functional as F

from experiments.hcsn_four_stage_flow_20261031.synthetic_data import batch
from .addressed_models import AddressedModel


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    seed, steps = 17, 400
    shared = ("encode.", "address_a", "address_b", "log_temperature", "roles.", "value.", "read.")
    source = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in (Path(__file__).resolve(), Path(__file__).with_name("addressed_models.py").resolve())}
    protocol = dict(scope="Development, all outcomes retained; no confirmation", seed=seed,
                    tasks=["mqar", "selective", "binding"], cores=["flow", "diagonal"], steps=steps,
                    batch=24, lr=.003, optimizer="AdamW", weight_decay=.0001, clip_norm=1.,
                    shared_initialization=list(shared), source=source)
    (out / "PROTOCOL.json").write_text(json.dumps(protocol, indent=2) + "\n")
    campaign_wall, campaign_cpu = time.perf_counter(), time.process_time()
    rows = []
    for task in protocol["tasks"]:
        torch.manual_seed(seed)
        template = AddressedModel("diagonal").state_dict()
        for core in protocol["cores"]:
            torch.manual_seed(seed)
            model = AddressedModel(core)
            state = model.state_dict()
            for name in state:
                if name.startswith(shared):
                    state[name] = template[name].clone()
            model.load_state_dict(state)
            optimizer = torch.optim.AdamW(model.parameters(), lr=protocol["lr"], weight_decay=protocol["weight_decay"])
            wall, cpu = time.perf_counter(), time.process_time()
            curve = []
            for step in range(steps):
                data = batch(task, 24, 100000 + seed * 10000 + step, split="train")
                x, dt, observed, y = [torch.from_numpy(data[key]) for key in ("x", "dt", "observed", "y")]
                optimizer.zero_grad(set_to_none=True)
                logits = model(x, dt, observed)
                loss = F.cross_entropy(logits.flatten(0, 1), y.flatten(), ignore_index=-100)
                loss.backward()
                gradient_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), 1., error_if_nonfinite=True)
                optimizer.step()
                if step % 50 == 0 or step == steps - 1:
                    curve.append(dict(step=step + 1, loss=float(loss.detach()), gradient_norm=float(gradient_norm)))
            train_cost = dict(wall_seconds=time.perf_counter() - wall, cpu_seconds=time.process_time() - cpu)
            wall, cpu = time.perf_counter(), time.process_time()
            model.eval()
            data = batch(task, 512, 0, split="dev")
            predictions, losses = [], []
            with torch.no_grad():
                for offset in range(0, 512, 32):
                    x, dt, observed, y = [torch.from_numpy(data[key][offset:offset + 32])
                                          for key in ("x", "dt", "observed", "y")]
                    logits = model(x, dt, observed)
                    predictions.append(logits.argmax(-1).numpy())
                    losses.append(float(F.cross_entropy(logits.flatten(0, 1), y.flatten(), ignore_index=-100)))
            predicted = np.concatenate(predictions)
            mask = data["y"] != -100
            correct = predicted == data["y"]
            result = dict(task=task, core=core, seed=seed, accuracy=float(correct[mask].mean()),
                          all_four=float((correct | ~mask).all(-1).mean()), loss=float(np.mean(losses)),
                          role_gates=model.roles(torch.eye(4)).sigmoid().detach().tolist(),
                          train_cost=train_cost,
                          eval_cost=dict(wall_seconds=time.perf_counter() - wall, cpu_seconds=time.process_time() - cpu),
                          curve=curve, diagnostics=model.last_diagnostics,
                          resources=model.resource_shape(data["x"].shape[1]))
            torch.save(model.state_dict(), out / f"{task}_{core}.pt")
            np.savez_compressed(out / f"{task}_{core}_dev.npz", prediction=predicted, target=data["y"])
            rows.append(result)
            (out / "RESULTS.json").write_text(json.dumps(rows, indent=2, allow_nan=False) + "\n")
            print(json.dumps(result), flush=True)
    summary = dict(fits=len(rows), wall_seconds=time.perf_counter() - campaign_wall,
                   cpu_seconds=time.process_time() - campaign_cpu,
                   source_unchanged=all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
                                        for path, digest in source.items()))
    (out / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
