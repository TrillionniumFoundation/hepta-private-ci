"""Fresh-process next-block recovery that consumes the complete probability state.

This trains an observation likelihood and readout on a bounded synthetic
fixture. Generator matrices are fixed. It is a recovery/state-consumption
gate, not evidence of external-task quality or production fault tolerance.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import numpy as np
import torch

from .distribution import DistributionGrid, DistributionState, condition_on_likelihood
from .distribution_manifest import digest, source_map
from .distribution_operator import DistributionOperator
from .tensor import TensorDiffusion, TensorReset


CONFIG = dict(schema="hcsn.distribution-recovery.v1", candidate="hcsn-regenerative-distribution-fv-v1",
              mu=-.1, sigma=.3, discount=.15, margin=.25, refractory=.11, endpoint=1.6,
              active_cells=16, phase_cells=4, tail_rate=1., durations=(.04, .07, .02, .05),
              quadrature_order=32, batch_size=4, block_steps=3, learning_rate=.003,
              initial_seed=20261109, data_seed=20261110, dtype="float32", truncated_bptt=True)


class ObservationReadout(torch.nn.Module):
    def __init__(self, size):
        super().__init__()
        self.likelihood = torch.nn.Linear(3, size)
        self.readout = torch.nn.Linear(size, 2)


def setup(device):
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    torch.set_float32_matmul_precision("highest")
    torch.backends.cuda.matmul.allow_tf32 = False
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA recovery requested without CUDA")


def operators(device):
    grid = DistributionGrid(tuple(np.linspace(0., CONFIG["endpoint"], CONFIG["active_cells"]+1)),
                            tuple(np.linspace(0., CONFIG["refractory"], CONFIG["phase_cells"]+1)), CONFIG["tail_rate"])
    bank = [DistributionOperator(TensorDiffusion(CONFIG["mu"], CONFIG["sigma"], CONFIG["discount"]),
                                 TensorReset(CONFIG["margin"], CONFIG["refractory"]), grid, dt,
                                 dtype=torch.float32, device=device, quadrature_order=CONFIG["quadrature_order"])
            for dt in CONFIG["durations"]]
    return grid, bank


def initialize(grid, device):
    torch.manual_seed(CONFIG["initial_seed"])
    model = ObservationReadout(grid.size).to(device=device, dtype=torch.float32)
    optimizer = torch.optim.Adam(model.parameters(), lr=CONFIG["learning_rate"], foreach=False, fused=False)
    generator = torch.Generator(device="cpu").manual_seed(CONFIG["data_seed"])
    mass = torch.zeros((CONFIG["batch_size"], grid.size), dtype=torch.float32, device=device)
    mass[:, 3], mass[:, grid.active_size], mass[:, -1] = .6, .15, .25
    state = DistributionState(grid, mass)
    return model, optimizer, generator, state, 0


def global_rng(device):
    return dict(cpu=torch.get_rng_state(), cuda=torch.cuda.get_rng_state() if device == "cuda" else None)


def restore_rng(payload, device):
    torch.set_rng_state(payload["cpu"])
    if device == "cuda":
        torch.cuda.set_rng_state(payload["cuda"])


def block(model, optimizer, generator, state, index, bank):
    """One optimizer update with state carried through all three observations."""
    rows, losses, outputs = [], [], []
    optimizer.zero_grad(set_to_none=True)
    for _ in range(CONFIG["block_steps"]):
        observation = torch.randn((CONFIG["batch_size"], 3), generator=generator).to(state.device)
        target = torch.stack((torch.sigmoid(observation[:, 0]+.3*observation[:, 1]),
                              torch.sigmoid(observation[:, 2]-.2*observation[:, 0])), dim=-1)
        prior_hash = digest(state.state_dict())
        likelihood = torch.exp(.2*model.likelihood(observation))
        conditioned = condition_on_likelihood(state, likelihood, observation_id=f"recovery-observation-{index}")
        flow = bank[index % len(bank)].advance(conditioned.state)
        state = flow.state
        prediction = model.readout(state.mass)
        loss = (prediction-target).square().mean()
        losses.append(loss)
        outputs.append(prediction.detach().cpu().tolist())
        rows.append(dict(step=index, duration=float(bank[index % len(bank)].dt),
                         input_sha256=digest(dict(observation=observation, target=target)),
                         consumed_state_sha256=prior_hash, observation_evidence_sha256=digest(conditioned.evidence),
                         posterior_sha256=digest(conditioned.state.state_dict()),
                         propagated_state_sha256=digest(state.state_dict()), prediction_sha256=digest(prediction),
                         loss=float(loss.detach().cpu()), elapsed=[state.elapsed.numerator, state.elapsed.denominator]))
        index += 1
    loss = torch.stack(losses).mean()
    loss.backward()
    gradients = {name: parameter.grad.detach().clone() for name, parameter in model.named_parameters()}
    if any(not bool(torch.isfinite(value).all()) for value in gradients.values()):
        raise FloatingPointError("training block has nonfinite gradients")
    likelihood_norm = float(sum(value.abs().sum() for name, value in gradients.items() if name.startswith("likelihood")).cpu())
    if likelihood_norm == 0:
        raise FloatingPointError("the observation likelihood did not receive a gradient")
    optimizer.step()
    # Both uninterrupted and resumed branches truncate graphs at block boundaries.
    state = state.detached()
    result = dict(rows=rows, predictions=outputs, block_loss=float(loss.detach().cpu()),
                  gradient_sha256=digest(gradients), likelihood_gradient_l1=likelihood_norm,
                  model_sha256=digest(model.state_dict()), optimizer_sha256=digest(optimizer.state_dict()),
                  final_state_sha256=digest(state.state_dict()),
                  final_semantic_sha256=digest(dict(model=model.state_dict(), optimizer=optimizer.state_dict(),
                                                   data_rng=generator.get_state(), global_rng=global_rng(str(state.device).split(":")[0]),
                                                   state=state.state_dict(), schedule_index=index)))
    return state, index, result


def replace_measure(state, control):
    """Explicit negative controls: change only the checkpoint probability measure."""
    if control == "intact":
        return state
    if state.active_atoms or state.refractory_atoms:
        raise ValueError("this bounded recovery fixture uses a density-only training state")
    mass = state.mass.clone()
    if control == "replace_measure":
        mass.zero_()
        mass[..., 0] = 1.
    elif control == "remove_phase":
        moved = mass[..., state.grid.active_size+1:].sum(-1)
        if not bool((moved > 0).all()):
            raise ValueError("phase negative control has no phase mass to move")
        mass[..., 0] += moved
        mass[..., state.grid.active_size+1:] = 0.
    elif control == "remove_tail":
        if not bool((mass[..., state.grid.active_size] > 0).all()):
            raise ValueError("tail negative control has no tail mass to move")
        mass[..., 0] += mass[..., state.grid.active_size]
        mass[..., state.grid.active_size] = 0.
    else:
        raise ValueError("unknown measure control")
    return DistributionState(state.grid, mass, elapsed=state.elapsed, steps=state.steps,
                             generator_identity=state.generator_identity,
                             projection_active_distance_sum=state.projection_active_distance_sum,
                             projection_phase_time_sum=state.projection_phase_time_sum)


def restore(path, expected_file_hash, source, grid, bank, device, control):
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_file_hash:
        raise ValueError("checkpoint file changed after parent snapshot")
    # Reload separately for every control: Adam tensors must not alias a preceding replay.
    payload = torch.load(path, map_location="cpu", weights_only=True)
    if (payload["config"] != CONFIG or payload["source_files_sha256"] != source
            or payload["operators"] != [operator.checkpoint_identity() for operator in bank]
            or payload["execution_device"] != device):
        raise ValueError("checkpoint source/config/device/operator identity mismatch")
    model, optimizer, generator, _, _ = initialize(grid, device)
    model.load_state_dict(payload["model"])
    optimizer.load_state_dict(payload["optimizer"])
    generator.set_state(payload["data_rng"])
    restore_rng(payload["global_rng"], device)
    state = DistributionState.from_state_dict(grid, payload["state"], device=device)
    state = replace_measure(state, control)
    return model, optimizer, generator, state, payload["schedule_index"]


def child(args):
    setup(args.device)
    source = source_map()
    grid, bank = operators(args.device)
    results = {}
    for control in ("intact", "replace_measure", "remove_phase", "remove_tail"):
        model, optimizer, generator, state, index = restore(args.checkpoint, args.checkpoint_sha256, source,
                                                           grid, bank, args.device, control)
        _, _, results[control] = block(model, optimizer, generator, state, index, bank)
    with args.output.open("x") as stream:
        json.dump(dict(results=results, child_pid=os.getpid(), source_unchanged=source_map() == source,
                       operators=[operator.checkpoint_identity() for operator in bank]), stream, indent=2, allow_nan=False)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--checkpoint-sha256")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("retain previous attempts: output already exists")
    if args.checkpoint:
        return child(args)
    args.output.mkdir(parents=True)
    setup(args.device)
    source = source_map()
    started, cpu = time.monotonic(), time.process_time()
    grid, bank = operators(args.device)
    model, optimizer, generator, state, index = initialize(grid, args.device)
    state, index, first = block(model, optimizer, generator, state, index, bank)
    path = args.output/"after-first-block.pt"
    payload = dict(config=CONFIG, source_files_sha256=source, execution_device=args.device,
                   operators=[operator.checkpoint_identity() for operator in bank], model=model.state_dict(),
                   optimizer=optimizer.state_dict(), data_rng=generator.get_state(), global_rng=global_rng(args.device),
                   state=state.state_dict(), schedule_index=index)
    checkpoint_semantic = digest(payload)
    torch.save(payload, path)
    checkpoint_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    _, _, uninterrupted = block(model, optimizer, generator, state, index, bank)
    command = [sys.executable, "-m", "qualification.hcsn_regenerative.run_distribution_recovery", "--checkpoint",
               str(path.resolve()), "--checkpoint-sha256", checkpoint_hash, "--device", args.device,
               "--output", str((args.output/"resumed.json").resolve())]
    child_error, child_code = None, None
    with (args.output/"child.log").open("x") as stream:
        try:
            child_code = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=180, check=False).returncode
        except subprocess.TimeoutExpired:
            child_error = "Fresh-process replay and negative controls exceeded 180 seconds"
    resumed = json.loads((args.output/"resumed.json").read_text()) if child_code == 0 else None
    checks = [dict(name="fresh_process_replay_completed", pass_=resumed is not None),
              dict(name="source_unchanged", pass_=source == source_map())]
    if resumed:
        checks.extend((dict(name="fresh_child_identity", pass_=resumed["child_pid"] != os.getpid()),
                       dict(name="all_next_block_semantics_exact", pass_=resumed["results"]["intact"] == uninterrupted),
                       dict(name="child_source_unchanged", pass_=resumed["source_unchanged"])))
        expected_data = [row["input_sha256"] for row in uninterrupted["rows"]]
        for name in ("replace_measure", "remove_phase", "remove_tail"):
            control = resumed["results"][name]
            difference = float(np.abs(np.asarray(control["predictions"])-np.asarray(uninterrupted["predictions"])).max())
            checks.append(dict(name=f"{name}:same_data", pass_=[row["input_sha256"] for row in control["rows"]] == expected_data))
            checks.append(dict(name=f"{name}:changes_predictions", pass_=difference >= 1e-7, prediction_linf=difference))
            checks.append(dict(name=f"{name}:changes_parameters", pass_=control["model_sha256"] != uninterrupted["model_sha256"]))
    passed = all(check["pass_"] for check in checks)
    result = dict(schema=CONFIG["schema"], status="pass" if passed else "failed", config=CONFIG,
                  source_files_sha256=source, source_set_sha256=digest(source), checks=checks,
                  device=args.device, torch=str(torch.__version__), cublas_workspace_config=os.environ.get("CUBLAS_WORKSPACE_CONFIG"),
                  first_block=first, checkpoint_sha256=checkpoint_hash, checkpoint_semantic_sha256=checkpoint_semantic,
                  uninterrupted=uninterrupted, resumed=resumed, child_exit_code=child_code, child_error=child_error,
                  command=command, operators=[dict(identity=operator.checkpoint_identity(), diagnostics=operator.diagnostics) for operator in bank],
                  wall_seconds=time.monotonic()-started, parent_cpu_seconds=time.process_time()-cpu,
                  child_cpu_seconds=None, actual_optimizer_updates_including_replays=6 if resumed else None,
                  probability_steps_including_replays=18 if resumed else None, physical_energy_joules=None,
                  energy_reason="No full-machine physical energy measurement supplied",
                  recovery_scope="Full density, tail, phase, physical clock, schedule, model, Adam and RNG; truncated BPTT",
                  production_owner_recovery_qualified=False, task_quality_evidence=False,
                  finished_utc=datetime.now(timezone.utc).isoformat())
    with (args.output/"receipt.json").open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(dict(status=result["status"], checks=len(checks), passed=sum(check["pass_"] for check in checks))))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
