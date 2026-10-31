"""Measured whole-model execution, exact recovery and actual native STOP.

The native test is a declared engineering policy, not a learned utility result.
Neural state updates execute in PyTorch; the unchanged pinned Rust owner selects
KEEP/STOP. CPU seconds, wall time, and persistent state bytes have distinct scopes.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import statistics
import subprocess
import sys
import time

import numpy as np
import torch
from torch.nn import functional as F

from experiments.hcsn_distributional_v2.runtime_eval import numeric_state, read_state
from experiments.hcsn_free_boundary_v1.training import load_weights, save_weights
from .model import build_model


REPOSITORY = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = dict(name="distribution_free_dual", input_dim=64, output_dim=10,
                      width=32, depth=1, seed=730003)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def execution_sources():
    own = Path(__file__).parent
    paths = [own / name for name in ("runtime.py", "native_causal.py", "model.py", "kernel.py")]
    for folder in ("hcsn_distributional_v2", "hcsn_free_boundary_v1",
                   "continuous_spiking_network"):
        paths.extend(sorted((REPOSITORY / "experiments" / folder).glob("*.py")))
    paths.extend(sorted((REPOSITORY / "experiments/hcsn_free_boundary_v1/native_vendor").glob("*.py")))
    return {str(path.relative_to(REPOSITORY)): digest(path) for path in paths}


def measured_child(command, log):
    started = time.monotonic()
    env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
               MKL_NUM_THREADS="1", PYTHONDONTWRITEBYTECODE="1")
    with Path(log).open("xb") as stream:
        child = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT,
                                 env=env, cwd=REPOSITORY)
        _, status, usage = os.wait4(child.pid, 0)
        child.returncode = os.waitstatus_to_exitcode(status)
    return dict(command=command, exit_code=child.returncode,
                complete_child_cpu_seconds=usage.ru_utime + usage.ru_stime,
                wall_seconds=time.monotonic() - started, maxrss_kib=usage.ru_maxrss,
                scope="Exact child wait4, including imports and its waited-for children")


def _model(config, backend, profile, checkpoint):
    model = build_model(**config, backend=backend, profile=profile)
    if checkpoint is not None:
        load_weights(checkpoint, model)
    return model


def _check_manifest(output):
    contract = json.loads((output / "CHECKPOINT.json").read_bytes())
    for path, expected in contract["files"].items():
        if digest(output / path) != expected:
            raise ValueError("Resume input changed: " + path)
    for path, expected in contract["sources"].items():
        if digest(REPOSITORY / path) != expected:
            raise ValueError("Resume source changed: " + path)
    return contract


def _checkpoint(output, model, state, inputs, durations, *, config, backend, profile,
                extra=None, original_checkpoint=None):
    save_weights(output / "weights.npz", model)
    np.savez_compressed(output / "mid_state.npz", **numeric_state(state))
    np.savez_compressed(output / "suffix.npz", x=inputs.numpy(), dt=durations.numpy())
    contract = dict(schema="hcsn-conservative-checkpoint.v1", config=config,
                    backend=backend, profile=profile, sources=execution_sources(),
                    files={p: digest(output / p) for p in
                           ("weights.npz", "mid_state.npz", "suffix.npz")},
                    original_checkpoint_sha256=digest(original_checkpoint)
                    if original_checkpoint else None,
                    trained_weights=original_checkpoint is not None, **(extra or {}))
    write_json(output / "CHECKPOINT.json", contract)
    return contract


def resume_worker(output, native=False):
    contract = _check_manifest(output)
    model = _model(contract["config"], contract["backend"], contract["profile"],
                   output / "weights.npz").eval()
    state = read_state(output / "mid_state.npz", contract["config"]["depth"])
    with np.load(output / "suffix.npz", allow_pickle=False) as archive:
        x, dt = torch.from_numpy(archive["x"].copy()), torch.from_numpy(archive["dt"].copy())
    if native:
        result, state = native_episode(model, state, x, dt,
            binary=contract["binary"], owner_root=output / "native_resumed",
            model_digest=digest(output / "weights.npz"), resume=True,
            start=contract["cut"], stop_after=contract["stop_after"])
        write_json(output / "RESUMED_NATIVE.json", result)
    else:
        logits = []
        with torch.inference_mode():
            for index in range(x.shape[1]):
                value, state, _ = model.step(x[:, index], dt[:, index], state)
                logits.append(value)
        np.savez_compressed(output / "resumed_logits.npz", logits=torch.stack(logits, 1).numpy())
    np.savez_compressed(output / "resumed_state.npz", **numeric_state(state))


def stream_check(output, backend, profile="stable", config=None, checkpoint=None,
                 length=128, cut=37):
    output, config = Path(output), dict(DEFAULT_CONFIG if config is None else config)
    output.mkdir(parents=True, exist_ok=False)
    if not 0 < cut < length:
        raise ValueError("Recovery cut must be inside the sequence")
    model = _model(config, backend, profile, checkpoint).eval()
    rng = torch.Generator().manual_seed(730004)
    x = torch.randn(2, length, config["input_dim"], generator=rng)
    dt = .2 + 4 * torch.rand(2, length, generator=rng)
    state, outputs, sizes, masses, corrections = None, [], [], [], []
    with torch.inference_mode():
        full = model(x, dt, return_sequence=True, return_aux=False)
        for index in range(length):
            value, state, aux = model.step(x[:, index], dt[:, index], state)
            outputs.append(value)
            sizes.append(sum(a.nbytes for a in numeric_state(state).values()))
            masses.append(max(float((p["probability"].sum(-1, dtype=torch.float64)-1).abs().max())
                              for p in state["layers"]))
            corrections.append(max(float(a["normalization_l1_correction"].max())
                                   for a in aux["layers"]))
            if index + 1 == cut:
                _checkpoint(output, model, state, x[:, cut:], dt[:, cut:], config=config,
                            backend=backend, profile=profile, original_checkpoint=checkpoint)
                refractory = [float(s["probability"][..., 8:].sum(-1).max())
                              for s in state["layers"]]
    streaming, expected_state = torch.stack(outputs, 1), numeric_state(state)
    np.savez_compressed(output / "expected_logits.npz", logits=streaming[:, cut:].numpy())
    np.savez_compressed(output / "expected_state.npz", **expected_state)
    command = [sys.executable, "-m", __package__ + ".runtime", "resume", "--output", str(output)]
    cost = measured_child(command, output / "resume.log")
    write_json(output / "RESUME_EXECUTION.json", cost)
    if cost["exit_code"]:
        raise RuntimeError("Fresh-interpreter resume failed; logs retained")
    with np.load(output / "resumed_logits.npz", allow_pickle=False) as archive:
        logits_equal = np.array_equal(streaming[:, cut:].numpy(), archive["logits"])
    with np.load(output / "resumed_state.npz", allow_pickle=False) as archive:
        state_equal = set(archive.files) == set(expected_state) and all(
            np.array_equal(archive[key], expected_state[key]) for key in expected_state)
    error = float((full-streaming).abs().max())
    record = dict(schema="hcsn-conservative-stream.v1", backend=backend, profile=profile,
        config=config, length=length, cut=cut, batch=2,
        batch_stream_max_abs_logit_error=error, batch_stream_atol=1e-4,
        batch_stream_argmax_disagreements=int((full.argmax(-1)!=streaming.argmax(-1)).sum()),
        suffix_logits_bitwise_equal=bool(logits_equal), suffix_state_bitwise_equal=bool(state_equal),
        max_probability_mass_defect=max(masses), max_normalization_l1=max(corrections),
        persistent_state_bytes_min=min(sizes), persistent_state_bytes_max=max(sizes),
        state_bytes_scope="Elapsed, content, probability and boundary only; no weights/history/BPTT",
        midpoint_refractory_mass=refractory, resume_execution=cost,
        trained_weights=checkpoint is not None, original_checkpoint_sha256=digest(checkpoint)
        if checkpoint else None, content_quality_claim=False)
    write_json(output / "RESULT.json", record)
    if not (logits_equal and state_equal and error <= 1e-4 and min(refractory)>0
            and min(sizes)==max(sizes)):
        raise AssertionError("Stream/recovery gate failed; evidence retained")
    return record


class NativeReadLoop:
    """One paid neural observation followed by the actual owner's decision."""

    def __init__(self, model, session, state=None, start=0, stop_after=6):
        self.model, self.session, self.state = model, session, state
        self.start, self.stop_after, self.calls = start, stop_after, 0

    def read(self, inputs, durations):
        from experiments.hcsn_free_boundary_v1.native_bridge import Signals

        if self.session.terminal:
            raise RuntimeError("Native STOP prohibits further neural reads")
        with torch.inference_mode():
            logits, new_state, aux = self.model.step(inputs, durations, self.state)
        self.calls += 1
        read = self.start + self.calls
        budget = 1.0 if read < self.stop_after else -1.0
        # This public engineering schedule guarantees both actions. Internal
        # values contribute, but this is not a learned task Bellman policy.
        value_signal = float(torch.tanh((aux["continuation"]-aux["intervention"]).mean()))
        signals = Signals(continuation=.6*budget + .2*value_signal,
            margin=float(torch.tanh(aux["margin"].mean())),
            risk=float(aux["refractory_mass"].mean()),
            activity=float(-torch.expm1(-aux["activity"].mean())))
        row = self.session.tick(signals, context=dict(read_index=read, public_budget=budget,
                                numerical_backend=self.model.backend, profile=self.model.profile))
        self.state = new_state
        row.update(read_index=read, logits=logits.tolist(),
                   actual_neural_calls=self.calls, public_budget=budget)
        return row


def native_episode(model, state, inputs, durations, *, binary, owner_root,
                   model_digest, resume=False, start=0, stop_after=6):
    from experiments.hcsn_free_boundary_v1.native_bridge import NativeSession

    session = NativeSession(owner_root, binary=binary, policy="continuation_only",
                            model_digest=model_digest, case="acceleration-runtime-v1",
                            seed=730005, resume=resume)
    loop, rows = NativeReadLoop(model, session, state, start, stop_after), []
    try:
        for index in range(inputs.shape[1]):
            if session.terminal:
                break
            rows.append(loop.read(inputs[:, index], durations[:, index]))
        retry = session.verify_retry() if rows else None
        guard = session.verify_terminal() if session.terminal else None
        # Model/read loop terminal guard: no model call is made after STOP.
        calls_before = loop.calls
        rejected = False
        if session.terminal:
            try:
                loop.read(inputs[:, 0], durations[:, 0])
            except RuntimeError as error:
                rejected = str(error) == "Native STOP prohibits further neural reads"
        result = dict(events=rows, actual_neural_calls=loop.calls, actual_paid_reads=loop.calls,
                      terminal=session.terminal, retry=retry, terminal_guard=guard,
                      neural_read_rejected_after_stop=rejected,
                      neural_calls_after_stop_probe=loop.calls-calls_before,
                      native_authority="DENY_ALL", source_model_is_python=True,
                      risk_field_semantics="Current refractory-state probability, not first-hit risk",
                      policy_scope="Fixed engineering budget schedule; no task-utility claim")
    finally:
        native_cost = session.close()
    result["native_execution"] = native_cost
    return result, loop.state


def native_check(output, backend, binary, profile="stable", config=None, checkpoint=None):
    output, config = Path(output), dict(DEFAULT_CONFIG if config is None else config)
    output.mkdir(parents=True, exist_ok=False)
    model = _model(config, backend, profile, checkpoint).eval()
    save_weights(output / "weights.npz", model)
    model_hash = digest(output / "weights.npz")
    generator = torch.Generator().manual_seed(730006)
    inputs = torch.randn(1, 12, config["input_dim"], generator=generator)
    durations = .5 + torch.rand(1, 12, generator=generator)
    full, full_state = native_episode(model, None, inputs, durations, binary=binary,
        owner_root=output / "native_full", model_digest=model_hash)
    prefix, mid_state = native_episode(model, None, inputs[:, :3], durations[:, :3],
        binary=binary, owner_root=output / "native_resumed", model_digest=model_hash)
    _checkpoint(output, model, mid_state, inputs[:, 3:], durations[:, 3:], config=config,
                backend=backend, profile=profile, original_checkpoint=checkpoint,
                extra=dict(binary=str(Path(binary).resolve()), cut=3, stop_after=6))
    if digest(output / "weights.npz") != model_hash:
        raise AssertionError("Numeric checkpoint identity changed during native test")
    command = [sys.executable, "-m", __package__ + ".runtime", "native-resume", "--output", str(output)]
    cost = measured_child(command, output / "native_resume.log")
    write_json(output / "RESUME_EXECUTION.json", cost)
    if cost["exit_code"]:
        raise RuntimeError("Actual native recovery failed; logs retained")
    suffix = json.loads((output / "RESUMED_NATIVE.json").read_bytes())
    combined = prefix["events"] + suffix["events"]
    expected_actions = [r["native"]["effective_action"] for r in full["events"]]
    resumed_actions = [r["native"]["effective_action"] for r in combined]
    state_arrays = numeric_state(full_state)
    with np.load(output / "resumed_state.npz", allow_pickle=False) as archive:
        same_state = set(archive.files)==set(state_arrays) and all(
            np.array_equal(archive[key], state_arrays[key]) for key in state_arrays)
    same_signals = [r["signals"] for r in full["events"]] == [r["signals"] for r in combined]
    same_logits = [r["logits"] for r in full["events"]] == [r["logits"] for r in combined]
    result = dict(schema="hcsn-conservative-native.v1", backend=backend, profile=profile,
        config=config, full=full, prefix=prefix, suffix=suffix, resume_execution=cost,
        action_sequence_equal=expected_actions==resumed_actions, signals_bitwise_equal=same_signals,
        logits_bitwise_equal=same_logits, final_neural_state_bitwise_equal=bool(same_state),
        expected_actions=["keep"]*5+["stop"], actual_actions=expected_actions,
        actual_native_processes=3, python_mock_native=False, production_activation=False,
        trained_weights=checkpoint is not None, original_checkpoint_sha256=digest(checkpoint)
        if checkpoint else None,
        nested_cost_warning="Resume wait4 includes its native child; do not add both scopes")
    write_json(output / "RESULT.json", result)
    if not (expected_actions==resumed_actions==["keep"]*5+["stop"] and same_signals
            and same_logits and same_state and full["terminal_guard"]["passed"]
            and suffix["terminal_guard"]["passed"] and full["neural_calls_after_stop_probe"]==0):
        raise AssertionError("Actual native action/recovery acceptance failed")
    return result


def benchmark_pair(output, config=None, checkpoint=None, repeats=5):
    output, config = Path(output), dict(DEFAULT_CONFIG if config is None else config)
    output.mkdir(parents=True, exist_ok=False)
    start_cpu, source = time.process_time(), execution_sources()
    records = []
    for length in (32, 128):
        generator = torch.Generator().manual_seed(731000 + length)
        x = torch.randn(4, length, config["input_dim"], generator=generator)
        dt = .2 + torch.rand(4, length, generator=generator)
        labels = torch.randint(config["output_dim"], (4, length), generator=generator)
        models = {key: _model(config, key, "stable", checkpoint) for key in ("reference", "accelerated")}
        parameters_equal = all(torch.equal(v, models["accelerated"].state_dict()[k])
                               for k, v in models["reference"].state_dict().items())
        if not parameters_equal:
            raise AssertionError("Benchmark initial parameters differ")
        optimizers = {key: torch.optim.Adam(model.parameters(), lr=.001)
                      for key, model in models.items()}

        def execute(key, training):
            model, optimizer = models[key], optimizers[key]
            model.train(training)
            cpu, wall = time.process_time(), time.monotonic()
            if training:
                optimizer.zero_grad(set_to_none=True)
                logits = model(x, dt, return_sequence=True, return_aux=False)
                loss = F.cross_entropy(logits.flatten(0, 1), labels.flatten())
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 2.)
                optimizer.step()
            else:
                with torch.inference_mode():
                    logits = model(x, dt, return_sequence=True, return_aux=False)
            elapsed = dict(cpu_seconds=time.process_time()-cpu, wall_seconds=time.monotonic()-wall)
            if not bool(torch.isfinite(logits).all()):
                raise FloatingPointError("Nonfinite benchmark result")
            return elapsed

        warmup = {key: dict(forward=execute(key, False), adam_step=execute(key, True)) for key in models}
        measurements = {key: dict(forward=[], adam_step=[]) for key in models}
        for index in range(repeats):
            order = ("reference", "accelerated") if index % 2 == 0 else ("accelerated", "reference")
            for key in order:
                measurements[key]["forward"].append(execute(key, False))
            for key in order:
                measurements[key]["adam_step"].append(execute(key, True))
        medians = {key: {kind: {clock: statistics.median(row[clock] for row in rows)
                    for clock in ("cpu_seconds", "wall_seconds")}
                    for kind, rows in kinds.items()} for key, kinds in measurements.items()}
        records.append(dict(batch=4, length=length, config=config, profile="stable", repeats=repeats,
            initial_state_dict_equal=parameters_equal, warmup=warmup, measurements=measurements,
            medians=medians, counts=models["reference"].counts(),
            cpu_speedup={kind: medians["reference"][kind]["cpu_seconds"] /
                         medians["accelerated"][kind]["cpu_seconds"] for kind in ("forward", "adam_step")}))
    result = dict(schema="hcsn-conservative-runtime.v1", cases=records, sources=source,
        source_changed=[path for path, sha in source.items() if digest(REPOSITORY / path)!=sha],
        self_cpu_seconds=time.process_time()-start_cpu,
        peak_process_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        torch_version=torch.__version__, threads=torch.get_num_threads(),
        complete_step="zero_grad, full model including boundary/value/normalization, CE, backward, clipping, Adam",
        paired_order="alternating backend order each repetition; identical input and initialization",
        scope="Whole-model synthetic CPU timing; no equal-quality, energy, GPU or scaling claim")
    write_json(output / "RESULT.json", result)
    if result["source_changed"]:
        raise AssertionError("Benchmark source changed during measurement")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("stream", "resume", "native", "native-resume",
                                            "native-causal", "benchmark"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--backend", choices=("reference", "accelerated"), default="accelerated")
    parser.add_argument("--profile", choices=("raw", "stable"), default="stable")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--binary", type=Path)
    args = parser.parse_args()
    torch.set_num_threads(1)
    config = json.loads(args.config.read_text()) if args.config else None
    if args.command in ("resume", "native-resume"):
        resume_worker(args.output, native=args.command=="native-resume")
    elif args.command == "stream":
        stream_check(args.output, args.backend, args.profile, config, args.checkpoint)
    elif args.command in ("native", "native-causal"):
        if args.binary is None:
            parser.error("Actual native verification requires --binary")
        if args.command == "native":
            native_check(args.output, args.backend, args.binary, args.profile, config, args.checkpoint)
        else:
            from .native_causal import causal_check

            causal_check(args.output, args.backend, args.binary, args.profile, config, args.checkpoint)
    else:
        benchmark_pair(args.output, config, args.checkpoint)


if __name__ == "__main__":
    main()
