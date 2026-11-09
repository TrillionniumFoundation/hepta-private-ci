"""Real-bundle 64-step graph checks and fresh-process independent-episode recovery."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
import traceback

import numpy as np

from .mechanism_contract import ARMS, DT, EXPECTED_PARAMETERS, RUNNER_FILES, STATE_COUNT, file_sha, read_json, utc_now, verify_sources, write_json
from .mechanism_model import DeviceEnergy, make_model
from .mechanism_qualify import numpy_mirror
from .mechanism_worker import configure_torch


CONFIG = dict(namespace="hcsn-mechanism-sequence-probe-only-v1", sequence_length=64, batch_size=2,
              model_seed=60713, private_rng_seed=60729, learning_rate=.001, execution_dtype="float32",
              first_input_nonzero_threshold=1e-8, belief_persists_between_episodes=False)


def pins():
    directory = Path(__file__).parent
    names = tuple(dict.fromkeys((*RUNNER_FILES, "mechanism_qualify.py", "mechanism_sequence_probe.py",
                                "MECHANISM_SEQUENCE_PROTOCOL.md")))
    return {str((directory/name).relative_to(directory.parents[1])): file_sha(directory/name) for name in names}


def semantic(value):
    if hasattr(value, "detach"):
        tensor = value.detach().cpu().contiguous()
        return dict(dtype=str(tensor.dtype), shape=list(tensor.shape), sha256=hashlib.sha256(tensor.numpy().tobytes()).hexdigest())
    if isinstance(value, dict):
        return {str(k): semantic(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [semantic(v) for v in value]
    return value


def digest(value):
    return hashlib.sha256(json.dumps(semantic(value), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def safe_json(value):
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if isinstance(value, dict):
        return {key: safe_json(v) for key, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_json(v) for v in value]
    return value


def load_bundle(path):
    path = Path(path)
    metadata = read_json(path.with_suffix(".json"))
    identity = dict(bundle_sha256=file_sha(path), metadata_sha256=file_sha(path.with_suffix(".json")))
    if metadata["bundle_sha256"] != identity["bundle_sha256"] or metadata["state_count"] != 81 or STATE_COUNT != 81:
        raise ValueError("The actual frozen S81 bundle is required")
    if set(metadata["arms"]) != set(ARMS):
        raise ValueError("The complete ten-arm bundle is required")
    verify_sources(metadata["source_pins"])
    with np.load(path, allow_pickle=False) as archive:
        arrays = {name: archive[name].copy() for name in archive.files}
    if set(arrays) != set(metadata["array_sha256"]):
        raise ValueError("Bundle array roster differs from its metadata")
    for name, value in arrays.items():
        if value.dtype != np.float32 or not np.isfinite(value).all() or hashlib.sha256(value.tobytes()).hexdigest() != metadata["array_sha256"][name]:
            raise ValueError("Unbound or invalid represented operator: "+name)
    return metadata, arrays, identity


def fixture():
    j = np.arange(64, dtype=np.float64)
    indices = np.stack((np.tile([0, 1, 2, 3], 16), np.tile([3, 2, 1, 0], 16))).astype(np.int64)
    observations = np.zeros((2, 64, 3), dtype=np.float32)
    observations[0, :, 0] = .1+.25*np.sin(.17*(j+1))
    observations[1, :, 0] = -.2*np.cos(.11*(j+1))
    observations[:, 0, 1] = 1.
    observations[:, :, 2] = np.asarray(DT, dtype=np.float32)[indices]
    target = np.array([[.2], [-.4]], dtype=np.float32)
    return observations, indices, target


def graph_checks(arrays, metadata, device):
    torch = configure_torch(device)
    observations, indices, target = fixture()
    checks = []
    selected_arms = ("regenerative_dual", "risk_only", "conditional_boundary")
    for arm in ARMS:
        try:
            model = make_model(arrays, arm, metadata["arms"][arm]["channel"], CONFIG["model_seed"], device)
            if sum(parameter.numel() for parameter in model.parameters()) != EXPECTED_PARAMETERS or EXPECTED_PARAMETERS != 2890:
                raise ValueError("Require the selected 2890-parameter S81 graph")
            x = torch.tensor(observations, device=device, requires_grad=arm in selected_arms)
            dt = torch.tensor(indices, device=device)
            with torch.set_grad_enabled(arm in selected_arms):
                value, audit = model(x, dt)
            parameters = {name: parameter.detach().cpu().numpy().astype(np.float64) for name, parameter in model.named_parameters()}
            channel = metadata["arms"][arm]["channel"]
            expected = numpy_mirror(parameters, arrays, arm, channel, observations, indices)
            forward_error = float(np.max(np.abs(value.detach().cpu().numpy()-expected)))
            checks.append(dict(name="64_step_forward_vs_independent_fp64", arm=arm, maximum_absolute_error=forward_error,
                               tolerance=2e-5, passed=math.isfinite(forward_error) and forward_error <= 2e-5,
                               mass_audit=audit, predicted=value.detach().cpu().tolist(), reference=expected.tolist()))
            if arm not in selected_arms:
                continue
            loss = (value-torch.tensor(target, device=device)).square().mean()
            loss.backward()

            def objective(inputs=observations):
                predicted = numpy_mirror(parameters, arrays, arm, channel, inputs, indices)
                return float(np.square(predicted-target.astype(np.float64)).mean())

            for name, parameter in model.named_parameters():
                if name not in ("encoder.0.weight", "encoder.2.weight", "gate.weight", "readout.weight"):
                    continue
                gradient = parameter.grad.detach().cpu().numpy().astype(np.float64)
                for flat in np.argsort(np.abs(gradient).ravel())[-2:]:
                    index = np.unravel_index(int(flat), gradient.shape)
                    original, step = parameters[name][index], 1e-4
                    try:
                        parameters[name][index] = original+step
                        plus = objective()
                        parameters[name][index] = original-step
                        minus = objective()
                    finally:
                        parameters[name][index] = original
                    difference = (plus-minus)/(2*step)
                    automatic = float(gradient[index])
                    error = abs(automatic-difference)
                    limit = 2e-7+.005*abs(difference)
                    checks.append(dict(name="64_step_selected_parameter_gradient", arm=arm, parameter=name,
                                       index=[int(i) for i in index], automatic=automatic, finite_difference=difference,
                                       absolute_error=error, tolerance=limit,
                                       passed=bool(math.isfinite(automatic) and math.isfinite(difference)
                                                   and abs(difference) > 1e-10 and error <= limit)))

            def first_difference(step):
                results = {}
                for k in (-2, -1, 1, 2):
                    changed = observations.astype(np.float64)
                    changed[0, 0, 0] += k*step
                    results[k] = objective(changed)
                return (results[-2]-8*results[-1]+8*results[1]-results[2])/(12*step)

            coarse, fine = first_difference(.002), first_difference(.001)
            automatic = float(x.grad[0, 0, 0].detach().cpu())
            finite = all(math.isfinite(v) for v in (coarse, fine, automatic))
            fd_error = abs(coarse-fine)
            error = abs(automatic-fine)
            relative = error/abs(fine) if fine != 0 else None
            resolved = finite and abs(fine) >= CONFIG["first_input_nonzero_threshold"]
            agreement = (finite and fd_error <= 1e-11+.005*abs(fine) and error <= 2e-7+.005*abs(fine)
                         and (not resolved or relative <= .01))
            checks.append(dict(name="64_step_first_input_fd_agreement", arm=arm, automatic=automatic,
                               finite_difference=fine, coarse_finite_difference=coarse, fd_step_difference=fd_error,
                               absolute_error=error, relative_error=relative, passed=bool(agreement)))
            checks.append(dict(name="64_step_first_input_nonzero_resolved", arm=arm, finite_difference=fine,
                               threshold=CONFIG["first_input_nonzero_threshold"], passed=bool(resolved),
                               sensitivity_status="resolved_nonzero" if resolved else "sensitivity_unresolved_or_vanished"))
        except Exception as error:
            checks.append(dict(name="64_step_arm_completed", arm=arm, passed=False,
                               error=repr(error), traceback=traceback.format_exc()))
    return checks


def global_rng(torch, device):
    return dict(cpu=torch.get_rng_state(), cuda=torch.cuda.get_rng_state() if device == "cuda" else None)


def initialize(arrays, metadata, device):
    torch = configure_torch(device)
    model = make_model(arrays, "regenerative_dual", metadata["arms"]["regenerative_dual"]["channel"], CONFIG["model_seed"], device)
    optimizer = torch.optim.Adam(model.parameters(), lr=CONFIG["learning_rate"])
    rng = torch.Generator(device="cpu").manual_seed(CONFIG["private_rng_seed"])
    return torch, model, optimizer, rng


def update(torch, model, optimizer, rng, episode, device):
    indices = torch.randint(0, 4, (2, 64), generator=rng, dtype=torch.int64)
    x = torch.randn((2, 64, 3), generator=rng, dtype=torch.float32)*.2
    x[:, :, 2] = torch.tensor(DT, dtype=torch.float32)[indices]
    target = torch.tanh(.3*x[:, 0, 0]+.2*x[:, -1, 1]+.1*x[:, :, 0].mean(-1))[:, None]
    data = dict(x=x, indices=indices, target=target)
    optimizer.zero_grad(set_to_none=True)
    value, audit = model(x.to(device), indices.to(device))
    loss = (value-target.to(device)).square().mean()
    loss.backward()
    gradients = {name: parameter.grad.detach().clone() for name, parameter in model.named_parameters()}
    if not all(bool(torch.isfinite(g).all()) for g in gradients.values()):
        raise FloatingPointError("Nonfinite full-episode gradient")
    optimizer.step()
    final = dict(model=model.state_dict(), optimizer=optimizer.state_dict(), private_rng=rng.get_state(),
                 global_rng=global_rng(torch, device), next_episode=episode+1)
    return dict(episode=episode, input_sha256=digest(data), output_sha256=digest(value), loss=float(loss.detach().cpu()),
                gradient_sha256=digest(gradients), model_sha256=digest(model.state_dict()),
                optimizer_sha256=digest(optimizer.state_dict()), final_semantic_sha256=digest(final),
                maximum_gradient_abs=max(float(g.abs().max().cpu()) for g in gradients.values()),
                mass_audit=audit, complete_independent_episode=True, sequence_length=64)


def child(args):
    if file_sha(args.checkpoint) != args.checkpoint_sha256:
        raise ValueError("Checkpoint file differs from the parent's immutable snapshot")
    metadata, arrays, identity = load_bundle(args.bundle)
    source = pins()
    torch, model, optimizer, rng = initialize(arrays, metadata, args.device)
    payload = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    if payload["config"] != CONFIG or payload["sources"] != source or payload["bundle"] != identity or payload["device"] != args.device:
        raise ValueError("Checkpoint source/config/bundle/device mismatch")
    model.load_state_dict(payload["model"])
    optimizer.load_state_dict(payload["optimizer"])
    rng.set_state(payload["private_rng"])
    torch.set_rng_state(payload["global_rng"]["cpu"])
    if args.device == "cuda":
        torch.cuda.set_rng_state(payload["global_rng"]["cuda"])
    result = update(torch, model, optimizer, rng, payload["next_episode"], args.device)
    verify_sources(source)
    write_json(args.output, dict(result=result, child_pid=os.getpid(), source_unchanged=True,
                                 actual_optimizer_updates=1, independent_episode_examples=2,
                                 peak_gpu_allocated_bytes=torch.cuda.max_memory_allocated() if args.device == "cuda" else None,
                                 process_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024))
    return 0


def recovery(args, source, metadata, arrays, identity):
    torch, model, optimizer, rng = initialize(arrays, metadata, args.device)
    first = update(torch, model, optimizer, rng, 0, args.device)
    checkpoint = args.output/"after-one-independent-episode.pt"
    payload = dict(config=CONFIG, sources=source, bundle=identity, device=args.device,
                   model=model.state_dict(), optimizer=optimizer.state_dict(), private_rng=rng.get_state(),
                   global_rng=global_rng(torch, args.device), next_episode=1)
    semantic_hash = digest(payload)
    torch.save(payload, checkpoint)
    checkpoint_hash = file_sha(checkpoint)
    expected = update(torch, model, optimizer, rng, 1, args.device)
    command = [sys.executable, "-m", "qualification.hcsn_regenerative.mechanism_sequence_probe",
               "--bundle", str(args.bundle.resolve()), "--device", args.device,
               "--checkpoint", str(checkpoint.resolve()), "--checkpoint-sha256", checkpoint_hash,
               "--output", str((args.output/"fresh-child.json").resolve())]
    error, code = None, None
    with (args.output/"child.log").open("x") as stream:
        with subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT) as process:
            child_pid = process.pid
            try:
                code = process.wait(timeout=180)
            except subprocess.TimeoutExpired:
                error = "Fresh-process next full episode exceeded 180 seconds; owned child killed and reaped"
                process.kill()
                code = process.wait()
    resumed = None
    if code == 0:
        try:
            resumed = read_json(args.output/"fresh-child.json")
            if (not isinstance(resumed, dict) or not isinstance(resumed.get("result"), dict)
                    or resumed.get("actual_optimizer_updates") != 1 or resumed.get("child_pid") != child_pid):
                raise ValueError("Malformed child receipt")
        except Exception as exception:
            error = "Missing or invalid child receipt: "+repr(exception)
            resumed = None
    passed = bool(resumed and resumed.get("result") == expected and resumed.get("source_unchanged")
                  and resumed.get("child_pid") == child_pid and child_pid != os.getpid())
    return dict(name="fresh_process_next_full_episode_exact", passed=passed,
                status="pass" if passed else "failed", exact_next_block=passed, first_update=first,
                uninterrupted=expected, resumed=resumed, child_exit_code=code, child_error=error, command=command,
                child_pid=child_pid, child_execution_stopped=code is not None,
                checkpoint_sha256=checkpoint_hash, checkpoint_semantic_sha256=semantic_hash,
                actual_optimizer_updates=3 if resumed else None, child_completed_updates=1 if resumed else None,
                known_completed_updates_lower_bound=3 if resumed else 2, child_updates_unknown=resumed is None,
                independent_episode_examples=6 if resumed else None, sequence_steps_per_example=64,
                belief_persists_between_episodes=False, production_owner_recovery_qualified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--checkpoint-sha256")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Retain previous attempts; output already exists")
    if args.checkpoint:
        return child(args)
    args.output.mkdir(parents=True)
    started, cpu = time.monotonic(), time.process_time()
    source = pins()
    metadata, arrays, identity = load_bundle(args.bundle)
    torch = configure_torch(args.device)
    energy = DeviceEnergy(args.device)
    checks = graph_checks(arrays, metadata, args.device)
    graph_peak = torch.cuda.max_memory_allocated() if args.device == "cuda" else None
    try:
        restored = recovery(args, source, metadata, arrays, identity)
    except Exception as error:
        restored = dict(name="fresh_process_next_full_episode_exact", passed=False, status="failed", exact_next_block=False,
                        error=repr(error), traceback=traceback.format_exc(), actual_optimizer_updates=None)
    recovery_peak = torch.cuda.max_memory_allocated() if args.device == "cuda" else None
    checks.append(dict(name=restored["name"], passed=restored["passed"]))
    unchanged = source == pins()
    checks.append(dict(name="source_unchanged", passed=unchanged))
    passed = all(check["passed"] for check in checks)
    sensitivity = []
    for check in checks:
        if check["name"] == "64_step_first_input_nonzero_resolved":
            agreement = next(c["passed"] for c in checks if c["name"] == "64_step_first_input_fd_agreement" and c["arm"] == check["arm"])
            sensitivity.append(dict(check, fd_agreement=agreement, resolved=bool(check["passed"] and agreement)))
    result = dict(schema="hcsn-mechanism-sequence-qualification-v1", status="pass" if passed else "failed",
                  config=CONFIG, sources=source, source_pins=source, source_map_sha256=digest(source), bundle=identity,
                  bundle_sha256=identity["bundle_sha256"], bundle_metadata_sha256=identity["metadata_sha256"],
                  checks=checks, sensitivity_checks=sensitivity, recovery=restored,
                  fixture_sha256=digest([v.tolist() for v in fixture()]),
                  task_dataset_reads=0, task_training_updates=0, original_campaign_completion_credit=0,
                  actual_optimizer_updates=restored.get("actual_optimizer_updates"),
                  wall_seconds=time.monotonic()-started, parent_cpu_seconds=time.process_time()-cpu,
                  children_user_cpu_seconds=resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime,
                  children_system_cpu_seconds=resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime,
                  parent_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                  energy=energy.finish(), full_physical_energy_joules=None,
                  torch=str(torch.__version__), device=args.device,
                  peak_gpu_allocated_bytes=max(graph_peak, recovery_peak) if args.device == "cuda" else None,
                  gpu_memory_scope="Maximum parent allocated bytes across separately reset graph/recovery phases; child reported separately",
                  graph_parent_peak_gpu_allocated_bytes=graph_peak, recovery_parent_peak_gpu_allocated_bytes=recovery_peak,
                  combined_device_memory_peak_qualified=False,
                  numerical_parameter_box_qualified=False, task_gain_qualified=False, finished_utc=utc_now())
    write_json(args.output/"receipt.json", safe_json(result))
    print(json.dumps(dict(status=result["status"], checks=len(checks), passed=sum(c["passed"] for c in checks),
                          actual_optimizer_updates=result["actual_optimizer_updates"])))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
