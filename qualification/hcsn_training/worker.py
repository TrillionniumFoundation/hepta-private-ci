"""One bounded task-loss BP request produces an immutable candidate, never adoption.

The forecast horizon labels target_time_micros. It does not replace the learned
financial maturity inside ValueKernelCell. NDU and local eligibility updates are
not accepted as losses, gradients or optimizer inputs by this entry point.
"""

import argparse
import copy
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time

import torch
from .joint_graph import (digest, integer, interval_seconds, load_model, model_bytes, sha256,
                          strict_json, tensor_digest, time_profile_digest)
from .handoff import dataset_digest, encode_handoff, execution_sources, runtime_tuple

MAX_DIAGNOSTIC_BYTES = 1024*1024


def task_gradients(model, inputs, targets, intervals):
    prediction, _ = model(inputs, intervals)
    if targets.shape != prediction[:, -1].shape or not bool(torch.isfinite(targets).all()):
        raise ValueError("finite targets must match final readout exactly")
    loss = (prediction[:, -1]-targets).square().mean()
    parameters = dict(model.named_parameters())
    gradients = torch.autograd.grad(loss, tuple(parameters.values()), allow_unused=True)
    missing = [name for name, grad in zip(parameters, gradients) if grad is None]
    if missing:
        raise ValueError(f"task gradient disconnected: {missing}")
    grads = dict(zip(parameters, gradients))
    tensor_digest(grads)
    if not bool(torch.isfinite(loss)):
        raise ValueError("nonfinite task loss")
    return loss, grads


def propose(model, request):
    started, cpu = time.perf_counter(), time.process_time()
    sources = execution_sources()
    fields = {"schema_version", "mechanism", "binding", "intervals", "inputs", "targets",
              "target_time_micros", "learning_rate", "optimizer_steps", "limits", "base_checkpoint", "time_profile",
              "operation_id"}
    if set(request) != fields or type(request["schema_version"]) is not int or request["schema_version"] != 1:
        raise ValueError("unknown training request schema/fields")
    if request["mechanism"] != "task_mse_bp_v1":
        raise ValueError("only task_mse_bp_v1 is implemented; NDU/plasticity are distinct")
    if not isinstance(request["operation_id"], str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", request["operation_id"]):
        raise ValueError("operation_id must use the Rust StableId V1 grammar")
    binding = request["binding"]
    if set(binding) != {"scope_digest", "generation", "writer_epoch", "clock_epoch", "model_digest", "profile_digest"}:
        raise ValueError("incomplete training binding")
    for key in ("generation", "writer_epoch"):
        integer(binding[key])
    for key in ("model_digest", "profile_digest", "scope_digest", "clock_epoch"):
        sha256(binding[key])
    checkpoint = request["base_checkpoint"]
    if set(checkpoint) != {"path", "sha256"} or binding["model_digest"] != checkpoint["sha256"]:
        raise ValueError("model binding differs from base checkpoint identity")
    original = load_model(checkpoint["path"], checkpoint["sha256"])
    if model.spec != original.spec or tensor_digest(model.state_dict()) != tensor_digest(original.state_dict()):
        raise ValueError("in-memory model differs from exact loaded base checkpoint")
    limits = request["limits"]
    maxima = dict(max_optimizer_steps=64, max_batch=64, max_intervals=256, max_elements=1_048_576)
    if set(limits) != set(maxima):
        raise ValueError("explicit complete resource limits required")
    for key, maximum in maxima.items():
        integer(limits[key], maximum=maximum)
    steps = integer(request["optimizer_steps"], maximum=limits["max_optimizer_steps"])
    rate = request["learning_rate"]
    if type(rate) not in (int, float) or not math.isfinite(rate) or not 0 < rate <= 1:
        raise ValueError("learning rate outside (0,1]")
    if time_profile_digest(request["time_profile"]) != binding["profile_digest"]:
        raise ValueError("admitted profile identity mismatch")
    intervals = interval_seconds(request["intervals"], request["time_profile"])
    last = request["intervals"][-1]
    if integer(request["target_time_micros"]) != last["end_micros"]+last["forecast_horizon_micros"]:
        raise ValueError("target time does not match forecast horizon")
    rows, labels = request["inputs"], request["targets"]
    if (not isinstance(rows, list) or not 1 <= len(rows) <= limits["max_batch"]
            or len(intervals) > limits["max_intervals"] or not isinstance(labels, list) or len(labels) != len(rows)
            or any(not isinstance(row, list) or len(row) != len(intervals) for row in rows)
            or any(not isinstance(x, list) or len(x) != model.spec.input_size for row in rows for x in row)
            or any(not isinstance(y, list) or len(y) != model.spec.output_size for y in labels)
            or len(rows)*(len(intervals)*(model.spec.input_size+4*model.spec.hidden_size*len(model.cells))
                          +model.spec.output_size) > limits["max_elements"]):
        raise ValueError("training tensor budget exceeded")
    inputs = torch.tensor(rows, dtype=next(model.parameters()).dtype)
    targets = torch.tensor(labels, dtype=inputs.dtype)
    if 131_072+64*len(rows)*model.spec.output_size+steps*(512+128*len(model.cells)) > MAX_DIAGNOSTIC_BYTES:
        raise ValueError("diagnostic receipt budget exceeded before training")
    base = tensor_digest(model.state_dict())
    candidate, history = copy.deepcopy(model), []
    for _ in range(steps):
        loss, grads = task_gradients(candidate, inputs, targets, intervals)
        history.append(dict(loss=float(loss.detach()), gradient_digest=tensor_digest(grads),
                            per_cell_gradient_norm={cell: math.sqrt(sum(float(g.square().sum())
                                for name, g in grads.items() if name.startswith(f"cells.{i}.")))
                                for i, cell in enumerate(model.spec.cell_ids)}))
        with torch.no_grad():
            for name, parameter in candidate.named_parameters():
                parameter.add_(grads[name], alpha=-rate)
        tensor_digest(candidate.state_dict())
    with torch.no_grad():
        output, state = candidate(inputs, intervals)
    if tensor_digest(model.state_dict()) != base:
        raise RuntimeError("original model changed during candidate generation")
    if execution_sources() != sources:
        raise RuntimeError("execution source changed; candidate rejected")
    runtime = runtime_tuple(str(next(model.parameters()).dtype))
    receipt = dict(schema_version=1, mechanism=request["mechanism"], binding=copy.deepcopy(binding),
                   request_digest=digest(request), base_checkpoint_sha256=checkpoint["sha256"],
                   execution_sources=sources, execution_source_digest=digest(sources),
                   runtime_tuple=runtime, runtime_tuple_digest=digest(runtime), dataset_digest=dataset_digest(request),
                   graph_digest=digest(asdict(model.spec)), edge_timing="previous_boundary",
                   base_weights_digest=base, candidate_weights_digest=tensor_digest(candidate.state_dict()),
                   inputs_digest=tensor_digest({"inputs": inputs}), targets_digest=tensor_digest({"targets": targets}),
                   schedule_digest=digest(request["intervals"]), target_time_micros=request["target_time_micros"],
                   optimizer=dict(kind="sgd", momentum=0, learning_rate=rate, steps=steps),
                   logical_cells=len(model.cells), trainable_parameters=sum(p.numel() for p in model.parameters()),
                   gradient_cells=len(model.cells), gradient_parameters=sum(g.numel() for g in grads.values()),
                   completed_optimizer_steps=steps, gradient_digest=digest(history),
                   training_examples_seen=steps*inputs.shape[0], training_intervals_seen=steps*inputs.shape[0]*len(intervals),
                   gradients=history, final_prediction=output[:, -1].tolist(),
                   torch_version=str(torch.__version__), physical_energy_joules=None,
                   energy_missing_reason="no physical counter in this CPU development adapter",
                   measurement_scope="proposal validation/base reload/copy/BP/final forward/serialization; excludes caller load and publication",
                   candidate_only=True, evaluation_passed=False)
    payload = model_bytes(candidate, optimizer=receipt["optimizer"], binding=binding,
                          final_state=tuple(tuple(v.detach().cpu() for v in s) for s in state),
                          last_end_micros=last["end_micros"])
    receipt["checkpoint_sha256"] = hashlib.sha256(payload).hexdigest()
    receipt["checkpoint_bytes"] = len(payload)
    receipt.update(wall_seconds=time.perf_counter()-started, cpu_seconds=time.process_time()-cpu,
                   cpu_threads=torch.get_num_threads())
    return payload, receipt


def write_new(path, payload):
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def main():
    started, cpu = time.perf_counter(), time.process_time()
    torch.set_num_threads(1)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.request.stat().st_size > 8*1024*1024:
        raise ValueError("request byte budget exceeded")
    with args.request.open("rb") as stream:
        raw = stream.read(8*1024*1024+1)
    if len(raw) > 8*1024*1024:
        raise ValueError("request byte budget exceeded")
    request = strict_json(raw)
    base = request["base_checkpoint"]
    model = load_model(base["path"], base["sha256"])
    # Exclusive directory is a once-only operation reservation. Interrupted or
    # rejected attempts retain it; the same output cannot silently retrain.
    args.output.mkdir(parents=True, exist_ok=False)
    write_new(args.output/"started.json", json.dumps(dict(request_digest=digest(request),
                                                        base_checkpoint_sha256=base["sha256"])).encode())
    try:
        payload, receipt = propose(model, request)
        write_new(args.output/"candidate.pt", payload)
        receipt["worker_cost_through_checkpoint_fsync"] = dict(wall_seconds=time.perf_counter()-started,
            cpu_seconds=time.process_time()-cpu, excluded="diagnostic and binary-handoff generation/publication")
        diagnostics = json.dumps(receipt, indent=2, allow_nan=False).encode()+b"\n"
        if len(diagnostics) > MAX_DIAGNOSTIC_BYTES:
            raise ValueError("diagnostic receipt byte limit exceeded; no handoff published")
        write_new(args.output/"receipt.json", diagnostics)
        write_new(args.output/"handoff.bin", encode_handoff(request, receipt, diagnostics, payload))
        print(json.dumps(dict(status="candidate", checkpoint_sha256=receipt["checkpoint_sha256"])))
    except BaseException as error:
        (args.output/"failed.json").write_text(json.dumps(dict(error=type(error).__name__, reason=str(error),
                                                            budget="partial_or_unknown; never auto-retry")))
        raise


if __name__ == "__main__":
    main()
