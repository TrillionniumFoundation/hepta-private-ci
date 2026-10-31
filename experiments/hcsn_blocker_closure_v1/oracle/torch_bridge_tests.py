"""First-order finite-QVI autograd checks and a real joint optimizer update."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import torch

from .torch_bridge import CHANNELS, PARAMETERS, task_values


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    start = time.process_time()
    torch.set_num_threads(1)
    parameters = torch.tensor([[1., .2, .04, .1, .47, .5],
                               [.9, .25, .06, .12, .52, 1.]], dtype=torch.float64, requires_grad=True)
    posterior = torch.tensor([.443, .572], dtype=torch.float64, requires_grad=True)
    checked = torch.autograd.gradcheck(task_values, (parameters, posterior), eps=1e-6,
                                       atol=2e-6, rtol=2e-5)
    broadcast_parameters = parameters.detach()[0].clone().requires_grad_()
    broadcast_posterior = posterior.detach().clone().requires_grad_()
    broadcast_checked = torch.autograd.gradcheck(task_values, (broadcast_parameters, broadcast_posterior),
                                                 eps=1e-6, atol=2e-6, rtol=2e-5)
    optimizer = torch.optim.SGD([parameters, posterior], lr=1e-5)
    before, before_state = parameters.detach().clone(), posterior.detach().clone()
    output_values = task_values(parameters, posterior)
    # A declared local verification objective, not a classification benchmark.
    weights = torch.tensor([.3, -.2, .1, .4], dtype=torch.float64)
    objective = (output_values*weights).mean()
    objective.backward()
    gradient, state_gradient = parameters.grad.detach().clone(), posterior.grad.detach().clone()
    optimizer.step()
    after_objective = float((task_values(parameters, posterior)*weights).mean().detach())
    change = (parameters.detach()-before).abs()
    state_change = (posterior.detach()-before_state).abs()
    checks = dict(gradcheck=checked, broadcast_gradcheck=broadcast_checked,
                  all_six_parameter_columns_nonzero=bool((gradient.abs().sum(0)>0).all()),
                  all_six_parameter_columns_updated=bool((change.sum(0)>0).all()),
                  posterior_gradient_nonzero=bool((state_gradient.abs()>0).all()),
                  posterior_updated=bool((state_change>0).all()),
                  descent=after_objective < float(objective.detach()))
    root = Path(__file__).parent
    sources = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
               for p in root.iterdir() if p.suffix == ".py"}
    result = dict(schema="hcsn-task-oracle-autograd.v1", passed=all(checks.values()), checks=checks,
                  parameters=PARAMETERS, channels=CHANNELS,
                  gradient=gradient.tolist(), state_gradient=state_gradient.tolist(),
                  update=change.tolist(), state_update=state_change.tolist(),
                  objective_before=float(objective.detach()), objective_after=after_objective,
                  source_sha256=sources, torch_version=torch.__version__,
                  cpu_seconds=time.process_time()-start,
                  scope="First derivatives on these stable active sets; CPU solver; no content-quality or architecture benefit claim")
    (output/"RESULTS.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    print(json.dumps(dict(passed=result["passed"], checks=checks, cpu_seconds=result["cpu_seconds"])))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
