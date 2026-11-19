"""Verify the next tensor fitting block after a real process checkpoint/restart.

This is a bounded numerical contract probe with synthetic targets, not an
independent task experiment, a trained Hepta core, or a production owner test.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

import torch

from qualification.hcsn_regenerative.run_tensor_audit import source_map
from qualification.hcsn_regenerative.tensor import TensorDiffusion, TensorReset, finite_horizon_value


CONFIG = dict(schema="hcsn.regenerative.recovery.v2", reset_margin=.25,
              refractory=.11, batch_size=4, learning_rate=.001,
              initial_seed=20261107, block_updates=3, dtype="float32")


def serial(value):
    """Canonical semantic content; torch ZIP metadata is not a numerical state."""
    if isinstance(value, torch.Tensor):
        v = value.detach().cpu().contiguous()
        return {"dtype": str(v.dtype), "shape": list(v.shape),
                "sha256": hashlib.sha256(v.numpy().tobytes()).hexdigest()}
    if isinstance(value, dict):
        return {str(k): serial(v) for k, v in sorted(value.items(), key=lambda x: str(x[0]))}
    if isinstance(value, (list, tuple)):
        return [serial(v) for v in value]
    return value


def digest(value):
    return hashlib.sha256(json.dumps(serial(value), sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def initialize(device):
    parameter = torch.nn.Parameter(torch.tensor([-.1, .3, .15], dtype=torch.float32, device=device))
    optimizer = torch.optim.Adam([parameter], lr=CONFIG["learning_rate"])
    generator = torch.Generator(device="cpu").manual_seed(CONFIG["initial_seed"])
    state = dict(completed_updates=0, simulated_horizon_sum_seconds=0.,
                 next_horizon=torch.tensor([.4, .7, 1., 1.4]), last_active_probability=None)
    return parameter, optimizer, generator, state


def block(parameter, optimizer, generator, state, device):
    rows = []
    reset = TensorReset(CONFIG["reset_margin"], CONFIG["refractory"])
    for _ in range(CONFIG["block_updates"]):
        x = (.2+.2*torch.rand(CONFIG["batch_size"], generator=generator)).to(device)
        horizon = state["next_horizon"].to(device)
        process = TensorDiffusion(parameter[0], parameter[1], parameter[2])
        value = finite_horizon_value(process, reset, x, horizon,
                                    active_reward=.4, terminal_reward=.2)
        target = .7+.1*x
        loss = (value.regenerative-target).square().mean()+.01*value.single_cycle.mean()
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        gradient = parameter.grad.detach().clone()
        optimizer.step()
        state["completed_updates"] += 1
        state["simulated_horizon_sum_seconds"] += float(horizon.sum().cpu())
        state["next_horizon"] = torch.roll(state["next_horizon"], 1)
        state["last_active_probability"] = value.active_probability.detach().cpu()
        rows.append(dict(update=state["completed_updates"], loss=float(loss.detach().cpu()),
                         input_sha256=digest({"x": x, "horizon": horizon}),
                         gradient_sha256=digest(gradient), output_sha256=digest(value.regenerative),
                         parameter_sha256=digest(parameter),
                         numerical_state_sha256=digest(state)))
    return rows


def checkpoint(path, parameter, optimizer, generator, state, source):
    if path.exists():
        raise FileExistsError("checkpoint path already exists")
    payload = dict(config=CONFIG, source_files_sha256=source,
                   parameter=parameter.detach().cpu(), optimizer=optimizer.state_dict(),
                   rng=generator.get_state(), numerical_state=state)
    torch.save(payload, path)
    return payload


def child(args):
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    if args.output.exists():
        raise FileExistsError("child output already exists")
    before = source_map()
    parameter, optimizer, generator, state = initialize(args.device)
    payload = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    if payload["config"] != CONFIG or payload["source_files_sha256"] != before:
        raise ValueError("checkpoint config/source identity mismatch")
    with torch.no_grad():
        parameter.copy_(payload["parameter"].to(args.device))
    optimizer.load_state_dict(payload["optimizer"])
    generator.set_state(payload["rng"])
    state = payload["numerical_state"]
    rows = block(parameter, optimizer, generator, state, args.device)
    final = dict(parameter=parameter, optimizer=optimizer.state_dict(), rng=generator.get_state(),
                 numerical_state=state)
    result = dict(rows=rows, final_semantic_sha256=digest(final), source_unchanged=source_map() == before,
                  child_pid=__import__("os").getpid())
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--checkpoint", type=Path)
    args = parser.parse_args()
    if args.checkpoint:
        return child(args)
    if args.output.exists():
        parser.error("retain old attempts; output already exists")
    args.output.mkdir(parents=True)
    before = source_map()
    started, cpu = time.monotonic(), time.process_time()
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    parameter, optimizer, generator, state = initialize(args.device)
    first = block(parameter, optimizer, generator, state, args.device)
    checkpoint_path = args.output / "after-first-block.pt"
    payload = checkpoint(checkpoint_path, parameter, optimizer, generator, state, before)
    checkpoint_semantic = digest(payload)
    uninterrupted_rows = block(parameter, optimizer, generator, state, args.device)
    final = dict(parameter=parameter, optimizer=optimizer.state_dict(), rng=generator.get_state(),
                 numerical_state=state)
    expected_hash = digest(final)
    command = [sys.executable, "-m", "qualification.hcsn_regenerative.run_recovery_probe",
               "--checkpoint", str(checkpoint_path.resolve()), "--output",
               str((args.output / "resumed.json").resolve()), "--device", args.device]
    child_returncode, child_error = None, None
    with (args.output / "child.log").open("x") as stream:
        try:
            result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=120, check=False)
            child_returncode = result.returncode
        except subprocess.TimeoutExpired:
            child_error = "Fresh-process next block exceeded its 120-second deadline"
    resumed = json.loads((args.output / "resumed.json").read_text()) if child_returncode == 0 else None
    passed = bool(resumed and resumed["rows"] == uninterrupted_rows
                  and resumed["final_semantic_sha256"] == expected_hash
                  and resumed["source_unchanged"] and source_map() == before)
    receipt = dict(schema=CONFIG["schema"], status="pass" if passed else "failed", config=CONFIG,
                   source_files_sha256=before, source_unchanged=before == source_map(),
                   device=args.device, torch=torch.__version__, first_block=first,
                   checkpoint_sha256=hashlib.sha256(checkpoint_path.read_bytes()).hexdigest(),
                   checkpoint_semantic_sha256=checkpoint_semantic, uninterrupted_next_block=uninterrupted_rows,
                   expected_final_semantic_sha256=expected_hash, resumed=resumed,
                   child_exit_code=child_returncode, child_error=child_error, command=command,
                   wall_seconds=time.monotonic()-started,
                   parent_process_cpu_seconds=time.process_time()-cpu,
                   child_cpu_seconds=None, physical_energy_joules=None,
                   energy_reason="Full-machine physical energy not supplied",
                   cost_scope="Parent CPU excludes child; wall contains child; never sum overlapping clocks",
                   production_owner_recovery_qualified=False, task_quality_evidence=False,
                   full_survivor_refractory_continuation_qualified=False,
                   recovery_scope="Parameters, optimizer, RNG and consumed input-horizon schedule; stored active probability is diagnostic only",
                   actual_optimizer_updates_including_replay=3*CONFIG["block_updates"] if passed else None,
                   finished_utc=datetime.now(timezone.utc).isoformat())
    with (args.output / "receipt.json").open("x") as stream:
        json.dump(receipt, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"recovery_status": receipt["status"], "wall_seconds": receipt["wall_seconds"]}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
