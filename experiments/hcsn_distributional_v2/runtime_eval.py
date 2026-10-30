"""Measured CPU work and new-interpreter recovery for the distributional cell.

Synthetic timing is separate from content accuracy. Complete optimizer updates
are measured; persistent inference state excludes parameters, outputs and BPTT.
Every worker is isolated and its complete wait4 CPU is recorded by its parent.
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

from experiments.hcsn_free_boundary_v1.training import load_weights, save_weights
from .model import MODEL_NAMES, build_model


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True,
                                    allow_nan=False) + "\n")


def verify_sources(mapping):
    for filename, expected in mapping.items():
        if digest(filename) != expected:
            raise ValueError("Source identity changed: " + filename)


def verified_training_run(directory):
    """Bind a completed selected MNIST model, not an interchangeable NPZ shape."""
    directory = Path(directory).resolve()
    repository = Path(__file__).resolve().parents[2]
    study = directory.parents[1]
    names = ("summary.json", "selection.json", "IDENTITY.json", "EXECUTION.json")
    summary, selection, identity, execution = (
        json.loads((directory / name).read_bytes()) for name in names)
    if summary["status"] != "completed" or identity["status"] != "completed" or execution["returncode"]:
        raise ValueError("Training run is not successfully completed")
    job = identity["job"]
    if job["task"] != "mnist" or job["model"] != "distribution_free_dual" or execution["job"] != job:
        raise ValueError("Expected the registered MNIST distribution_free_dual run")
    model_config = summary["selected_model_config"]
    constructor = {key: model_config[key] for key in ("name", "input_dim", "output_dim", "width", "depth", "seed")}
    if constructor["input_dim"] != 64 or constructor["output_dim"] != 10:
        raise ValueError("Unexpected MNIST input/output dimensions")
    if constructor["name"] != job["model"] or constructor["seed"] != job["seed"]:
        raise ValueError("Training identity differs from selected configuration")
    request = summary["request"]
    if any(request[key] != constructor[key] for key in ("width", "depth", "seed")) or request["model"] != constructor["name"]:
        raise ValueError("Training request/configuration mismatch")
    if summary["selection"] != selection or selection["completed_lr_candidates"] != len(summary["candidates"]):
        raise ValueError("Selection record is inconsistent")
    if selection["completed_lr_candidates"] != len(request["learning_rates"]):
        raise ValueError("Not all learning-rate candidates completed")
    checkpoint = directory / "selected.npz"
    if digest(checkpoint) != selection["selected_checkpoint_sha256"]:
        raise ValueError("Selected model weights changed")
    if selection["dataset_sha256"] != identity["dataset_sha256"]:
        raise ValueError("Training dataset identity differs")
    registration = json.loads((study / "REGISTRATION.json").read_bytes())
    if identity["protocol_sha256"] != registration["protocol_sha256"] or execution["protocol_sha256"] != registration["protocol_sha256"]:
        raise ValueError("Training protocol binding differs")
    protocols = [path for path in (study / "source").glob("CONTENT*PROTOCOL.json")
                 if digest(path) == registration["protocol_sha256"]]
    if len(protocols) != 1:
        raise ValueError("Missing unique registered protocol snapshot")
    protocol = json.loads(protocols[0].read_bytes())
    if job not in protocol["jobs"] or protocol["source_files_sha256"] != identity["source_files_sha256"]:
        raise ValueError("Unregistered training job/dependencies")
    for relative, expected in identity["source_files_sha256"].items():
        if digest(repository / relative) != expected:
            raise ValueError("Registered training dependency changed: " + relative)
    data = protocol["data"]["mnist"]
    if data["sha256"] != identity["dataset_sha256"] or digest(repository / data["path"]) != data["sha256"]:
        raise ValueError("Registered MNIST dataset changed")
    binding = dict(run=str(directory), files={name: digest(directory / name) for name in names},
                   selected_checkpoint_sha256=digest(checkpoint), protocol_sha256=registration["protocol_sha256"],
                   full_model_config=model_config, job=job, successful_completed_worker=True)
    return checkpoint, constructor, binding


def measured_child(arguments, log_path):
    command = [sys.executable, "-m", __package__ + ".runtime_eval", *arguments]
    start = time.monotonic()
    with Path(log_path).open("xb") as log:
        child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        _, status, usage = os.wait4(child.pid, 0)
        code = os.waitstatus_to_exitcode(status)
        child.returncode = code
    return dict(command=command, exit_code=code,
                child_cpu_seconds=usage.ru_utime + usage.ru_stime,
                wall_seconds=time.monotonic() - start, maxrss_kib=usage.ru_maxrss)


def numeric_state(state):
    result = {"elapsed": state["elapsed"].detach().cpu().numpy().copy()}
    for index, layer in enumerate(state["layers"]):
        for key, value in layer.items():
            if not isinstance(value, torch.Tensor):
                raise ValueError("Checkpoint must follow at least one observation")
            result[f"layer_{index}.{key}"] = value.detach().cpu().numpy().copy()
    return result


def read_state(path, config, batch, array_schema):
    with np.load(path, allow_pickle=False) as stored:
        raw = {key: np.array(stored[key], copy=True) for key in stored.files}
    expected = {"elapsed": [batch]}
    for index in range(config["depth"]):
        expected.update({f"layer_{index}.content": [batch, config["width"]],
                         f"layer_{index}.probability": [batch, config["physical_channels"],
                                                       config["grid_cells"] + config["refractory_stages"]],
                         f"layer_{index}.boundary": [batch, config["physical_channels"]]})
    if set(raw) != set(expected) or set(array_schema) != set(expected):
        raise ValueError("Incomplete or unknown checkpoint fields")
    for key, value in raw.items():
        if list(value.shape) != expected[key] or value.dtype != np.dtype("float32") or not np.isfinite(value).all():
            raise ValueError("Invalid checkpoint shape/dtype/numerics: " + key)
        if array_schema[key] != dict(shape=list(value.shape), dtype=str(value.dtype)):
            raise ValueError("Checkpoint array metadata mismatch")
        if key.endswith("probability") and (value.min() < -1e-7 or np.max(np.abs(value.sum(-1) - 1)) > 1e-4):
            raise ValueError("Checkpoint probability is not a valid numerical distribution")
        if key.endswith("boundary") and value.min() <= config["lower"]:
            raise ValueError("Checkpoint boundary is outside the physical domain")
    if raw["elapsed"].min() < 0:
        raise ValueError("Negative elapsed time")
    arrays = {key: torch.from_numpy(value) for key, value in raw.items()}
    state = dict(elapsed=arrays.pop("elapsed"), layers=[])
    for index in range(config["depth"]):
        prefix = f"layer_{index}."
        layer = {key[len(prefix):]: arrays.pop(key) for key in list(arrays)
                 if key.startswith(prefix)}
        if set(layer) != {"content", "probability", "boundary"}:
            raise ValueError("Incomplete or unknown distributional layer state")
        state["layers"].append(layer)
    if arrays:
        raise ValueError("Unknown checkpoint fields")
    return state


def measure_case(output, name, batch, length, repeats=3):
    generator = torch.Generator().manual_seed(730001 + batch + 7 * length)
    inputs = torch.randn(batch, length, 64, generator=generator)
    durations = 0.2 + torch.rand(batch, length, generator=generator)
    labels = torch.randint(10, (batch, length), generator=generator)
    model = build_model(name, 64, 10, width=32, depth=1, seed=730002)
    optimizer = torch.optim.Adam(model.parameters(), lr=.001)

    def execute(training):
        model.train(training)
        cpu, wall = time.process_time(), time.monotonic()
        if training:
            optimizer.zero_grad(set_to_none=True)
            logits = model(inputs, durations, return_sequence=True, return_aux=False)
            loss = F.cross_entropy(logits.flatten(0, 1), labels.flatten())
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 2.0)
            optimizer.step()
        else:
            with torch.inference_mode():
                logits = model(inputs, durations, return_sequence=True, return_aux=False)
        if not bool(torch.isfinite(logits).all()):
            raise FloatingPointError("Nonfinite timing output")
        return dict(cpu_seconds=time.process_time() - cpu,
                    wall_seconds=time.monotonic() - wall)

    warmup = dict(forward=execute(False), optimizer_step=execute(True))
    forward = [execute(False) for _ in range(repeats)]
    training = [execute(True) for _ in range(repeats)]
    record = dict(schema="hcsn-v2-runtime-case.v1", model=name,
                  input_features=64, classes=10, batch=batch, length=length,
                  width=32, depth=1, counts=model.counts(), warmup=warmup,
                  forward=forward, optimizer_step=training,
                  forward_cpu_median=statistics.median(x["cpu_seconds"] for x in forward),
                  optimizer_cpu_median=statistics.median(x["cpu_seconds"] for x in training),
                  peak_process_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  scope="Synthetic full-sequence CPU; not equal-quality throughput, energy or cache comparison")
    write_json(output / "RESULT.json", record)


def resume_worker(output):
    contract = json.loads((output / "CHECKPOINT.json").read_bytes())
    if contract["schema"] != "hcsn-v2-stream-checkpoint.v2":
        raise ValueError("Unknown stream checkpoint schema")
    if contract["writer_pid"] == os.getpid():
        raise ValueError("Resume did not use a distinct Python process")
    for filename, expected in contract["files"].items():
        if digest(output / filename) != expected:
            raise ValueError("Resume input identity changed: " + filename)
    verify_sources(contract["source"])
    cpu = time.process_time()
    model = build_model(**contract["model"])
    if model.config != contract["full_model_config"]:
        raise ValueError("Full physical model configuration changed")
    load_weights(output / "weights.npz", model)
    model.eval()
    state = read_state(output / "mid_state.npz", model.config, contract["batch"], contract["state_array_schema"])
    with np.load(output / "suffix.npz", allow_pickle=False) as archive:
        inputs = torch.from_numpy(archive["x"].copy())
        durations = torch.from_numpy(archive["dt"].copy())
    restored_cpu = time.process_time() - cpu
    outputs = []
    with torch.inference_mode():
        for index in range(inputs.shape[1]):
            logits, state, _ = model.step(inputs[:, index], durations[:, index], state)
            outputs.append(logits)
    np.savez_compressed(output / "resumed_logits.npz", logits=torch.stack(outputs, 1).numpy())
    np.savez_compressed(output / "resumed_state.npz", **numeric_state(state))
    write_json(output / "RESUME_COST.json", dict(load_model_and_state_cpu_seconds=restored_cpu,
               self_cpu_after_input_validation=time.process_time() - cpu,
               pid=os.getpid(), writer_pid=contract["writer_pid"],
               new_python_interpreter=os.getpid() != contract["writer_pid"],
               scope="Worker complete CPU, including imports and hash checks, is measured by parent wait4"))


def recovery_case(output, checkpoint_run=None):
    config = dict(name="distribution_free_dual", input_dim=64, output_dim=10,
                  width=32, depth=2, seed=730003)
    checkpoint, training_binding = None, None
    if checkpoint_run:
        checkpoint, config, training_binding = verified_training_run(checkpoint_run)
    model = build_model(**config)
    if training_binding and model.config != training_binding["full_model_config"]:
        raise ValueError("Selected full physical configuration is incompatible with current code")
    if checkpoint:
        load_weights(checkpoint, model)
    model.eval()
    save_weights(output / "weights.npz", model)
    generator = torch.Generator().manual_seed(730004)
    batch, length, cut = 2, 256, 113
    inputs = torch.randn(batch, length, 64, generator=generator)
    durations = .2 + torch.rand(batch, length, generator=generator)
    np.savez_compressed(output / "suffix.npz", x=inputs[:, cut:].numpy(), dt=durations[:, cut:].numpy())
    with torch.inference_mode():
        full = model(inputs, durations, return_sequence=True, return_aux=False)
        state, outputs, state_sizes, mass_errors = None, [], [], []
        for index in range(length):
            logits, state, _ = model.step(inputs[:, index], durations[:, index], state)
            outputs.append(logits)
            arrays = numeric_state(state)
            state_sizes.append(sum(value.nbytes for value in arrays.values()))
            mass_errors.append(max(float((layer["probability"].sum(-1)-1).abs().max())
                                   for layer in state["layers"]))
            if index + 1 == cut:
                np.savez_compressed(output / "mid_state.npz", **arrays)
                state_array_schema = {key: dict(shape=list(value.shape), dtype=str(value.dtype))
                                      for key, value in arrays.items()}
                refractory_mass = [float(layer["probability"][..., 8:].sum(-1).max())
                                   for layer in state["layers"]]
        streaming = torch.stack(outputs, 1)
    expected_logits = streaming[:, cut:].numpy()
    expected_state = numeric_state(state)
    np.savez_compressed(output / "uninterrupted_logits.npz", logits=expected_logits)
    np.savez_compressed(output / "uninterrupted_state.npz", **expected_state)
    source_paths = execution_sources()
    contract = dict(schema="hcsn-v2-stream-checkpoint.v2", model=config,
                    full_model_config=model.config, writer_pid=os.getpid(),
                    state_array_schema=state_array_schema, training_binding=training_binding,
                    inputs="deterministic synthetic, not content-quality evaluation",
                    trained_weights=checkpoint is not None,
                    input_checkpoint_sha256=digest(checkpoint) if checkpoint else None,
                    batch=batch, total_steps=length, completed_steps=cut,
                    files={name: digest(output / name) for name in
                           ("weights.npz", "mid_state.npz", "suffix.npz")},
                    source={str(path): digest(path) for path in source_paths})
    write_json(output / "CHECKPOINT.json", contract)
    cost = measured_child(["resume", "--output", str(output)], output / "resume.log")
    write_json(output / "RESUME_EXECUTION.json", cost)
    if cost["exit_code"]:
        raise RuntimeError("Fresh-interpreter resume failed; evidence retained")
    with np.load(output / "resumed_logits.npz", allow_pickle=False) as archive:
        restored_logits = archive["logits"].copy()
    with np.load(output / "resumed_state.npz", allow_pickle=False) as archive:
        restored_state = {key: archive[key].copy() for key in archive.files}
    same_state = set(restored_state) == set(expected_state) and all(
        np.array_equal(restored_state[key], expected_state[key]) for key in expected_state)
    sequence_error = float((full-streaming).abs().max())
    record = dict(schema="hcsn-v2-recovery-result.v1", model=config,
                  trained_weights=checkpoint is not None, batch=batch, steps=length,
                  training_binding=training_binding,
                  split_at=cut, suffix_steps=length-cut,
                  full_vs_stream_max_absolute_logit_error=sequence_error,
                  full_vs_stream_tolerance=1e-4,
                  full_vs_stream_argmax_disagreements=int((full.argmax(-1) != streaming.argmax(-1)).sum()),
                  resumed_logits_bitwise_equal=bool(np.array_equal(expected_logits, restored_logits)),
                  resumed_state_bitwise_equal=same_state,
                  mid_refractory_mass_max_by_layer=refractory_mass,
                  persistent_state_bytes_min=min(state_sizes), persistent_state_bytes_max=max(state_sizes),
                  persistent_state_bytes_by_step=state_sizes,
                  max_probability_mass_error=max(mass_errors),
                  resume_complete_child=cost,
                  state_scope="Only elapsed/content/probability/boundary; excludes parameters, outputs, BPTT and baseline caches")
    write_json(output / "RESULT.json", record)
    if (not record["resumed_logits_bitwise_equal"] or not same_state
            or sequence_error > 1e-4 or min(refractory_mass) <= 0
            or min(state_sizes) != max(state_sizes)):
        raise AssertionError("Recovery/streaming acceptance failed; evidence retained")


def execution_sources():
    local = Path(__file__).parent
    return ([local / name for name in ("runtime_eval.py", "model.py", "distribution_kernel.py")]
            + sorted(Path("experiments/hcsn_free_boundary_v1").glob("*.py"))
            + sorted(Path("experiments/continuous_spiking_network").glob("*.py")))


def run_suite(output, checkpoint_run=None):
    output.mkdir(parents=True, exist_ok=False)
    source = {str(path): digest(path) for path in execution_sources()}
    checkpoint, training_binding = None, None
    if checkpoint_run:
        checkpoint, _, training_binding = verified_training_run(checkpoint_run)
    write_json(output / "REGISTRATION.json", dict(schema="hcsn-v2-runtime-registration.v1",
               models=list(MODEL_NAMES), configurations=[[4, 32], [4, 128]], repeats=3,
               source=source, checkpoint_sha256=digest(checkpoint) if checkpoint else None,
               training_binding=training_binding,
               content_quality_claim=False, gpu_energy_claim=False))
    records = []
    for batch, length in ((4, 32), (4, 128)):
        for name in MODEL_NAMES:
            directory = output / f"{name}_b{batch}_t{length}"
            directory.mkdir()
            arguments = ["bench", "--output", str(directory), "--model", name,
                         "--batch", str(batch), "--length", str(length),
                         "--registration", str(output / "REGISTRATION.json")]
            execution = measured_child(arguments, directory / "process.log")
            write_json(directory / "EXECUTION.json", execution)
            records.append(dict(path=str(directory), execution=execution))
            write_json(output / "PROGRESS.json", dict(records=records))
    directory = output / "recovery"
    directory.mkdir()
    arguments = ["recovery", "--output", str(directory),
                 "--registration", str(output / "REGISTRATION.json")]
    if checkpoint_run:
        arguments += ["--checkpoint-run", str(checkpoint_run)]
    execution = measured_child(arguments, directory / "process.log")
    write_json(directory / "EXECUTION.json", execution)
    records.append(dict(path=str(directory), execution=execution))
    changed = [path for path, expected in source.items() if digest(path) != expected]
    complete = dict(schema="hcsn-v2-runtime-complete.v1", records=records,
                    source_changed_during_run=changed,
                    complete_workers_cpu_seconds=sum(x["execution"]["child_cpu_seconds"] for x in records),
                    coordinator_complete_self_cpu_through_cutoff=time.process_time(),
                    note="Nested resume CPU is already inside its recovery worker scope; do not add twice")
    write_json(output / "COMPLETE.json", complete)
    if changed or any(row["execution"]["exit_code"] for row in records):
        raise RuntimeError("Runtime suite has failed or changed-source records")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("run", "bench", "recovery", "resume"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", choices=MODEL_NAMES, default="distribution_free_dual")
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--length", type=int, default=32)
    parser.add_argument("--checkpoint-run", type=Path)
    parser.add_argument("--registration", type=Path)
    args = parser.parse_args()
    torch.set_num_threads(1)
    if args.registration:
        verify_sources(json.loads(args.registration.read_bytes())["source"])
    if args.mode == "run":
        run_suite(args.output, args.checkpoint_run)
    elif args.mode == "bench":
        measure_case(args.output, args.model, args.batch, args.length)
    elif args.mode == "recovery":
        recovery_case(args.output, args.checkpoint_run)
    else:
        resume_worker(args.output)


if __name__ == "__main__":
    main()
