"""Bounded development functional, causality and independent operator checks."""
import hashlib
import json
from pathlib import Path
import time
import numpy as np
from scipy.linalg import expm
import torch
from tools.hcsn.addressed_decision_r15_20261101.law import Law
from .campaign import tensor_data
from .models import ContentNetwork, KINDS, rollout
from .task import DURATIONS, dataset


def check(output):
    torch.set_num_threads(1)
    started = time.process_time()
    data, identity = dataset(191111, 4, "iid")
    batch, rows = tensor_data(data), []
    for kind in KINDS:
        torch.manual_seed(991)
        model = ContentNetwork(kind, Law())
        optimizer = torch.optim.Adam(model.parameters(), lr=.003)
        loss, _, _, _, _ = rollout(model, batch, "value", 0., True)
        loss.backward()
        grads = {name: float(value.grad.norm()) for name, value in model.named_parameters()
                 if value.grad is not None}
        assert all(np.isfinite(list(grads.values())))
        before = {name: value.detach().clone() for name, value in model.named_parameters()}
        optimizer.step()
        change = sum(float((value.detach() - before[name]).square().sum())
                     for name, value in model.named_parameters())
        assert change > 0
        for threshold in (-1., .05):
            with torch.no_grad():
                _, answer, read, p, _ = rollout(model, batch, "light", threshold)
                altered = {**batch, "tokens": torch.where(read, batch["tokens"],
                            torch.full_like(batch["tokens"], -100)), "targets": (batch["targets"] + 1) % 4}
                _, answer2, read2, p2, _ = rollout(model, altered, "light", threshold)
            assert torch.equal(answer, answer2) and torch.equal(read, read2) and torch.equal(p, p2)
        error = None
        if kind in ("analytic", "hmm"):
            matrices = model.transitions().detach().numpy()
            scale = float(model.log_scale.detach().exp())
            error = max(float(abs(matrices[i] - expm(Law().Q * float(dt) * scale)).max())
                        for i, dt in enumerate(DURATIONS))
            assert error < 2e-12
            assert grads["log_scale"] > 0 and grads["symbol.weight"] > 0
        rows.append(dict(core=kind, objective=float(loss.detach()), gradient_norms=grads,
                         parameters=sum(p.numel() for p in model.parameters()),
                         parameter_update_squared=change, operator_max_error=error,
                         unpurchased_invalid_response_and_target_invariance=True))
    root = Path(__file__).resolve().parent
    result = dict(development_world_identity=identity, rows=rows,
                  sources={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.glob("*.py")},
                  cpu_seconds=time.process_time() - started,
                  scope="Four predeclared development worlds only; formal train/val/test unopened")
    with output.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps(dict(development_passed=True, cores=len(rows), cpu_seconds=result["cpu_seconds"])))


if __name__ == "__main__":
    import sys
    check(Path(sys.argv[1]))
