"""Real admitted CPU work for process-cancellation acceptance, never quality evidence.

B uses an explicitly identified 8-bin discretization so a longer real trace fits
the unchanged one-million-element admission ceiling. General fixtures keep their
historical 32-bin grid and canonical checkpoint identity.
"""

import copy
import json
from pathlib import Path

import torch
from .joint_graph import digest, graph_spec_dict, interval_seconds
from .population_graph import population_intervals
from .population_age_graph import population_age_intervals
from .test_joint_graph import fixture as value_fixture
from .test_population_graph import fixture as grid_fixture
from .test_population_age_graph import fixture as age_fixture
from .test_training_state import bind_initialization
from .verify_bridge import write_new
from .worker import propose

MAX_ELEMENTS = 1_048_576
OPTIMIZER_STEPS = 64
MAX_HOST_WIRE = 24 * 1024


def prepare_cancellation_fixture(directory, backend):
    if backend == "value_kernel":
        model, request, old_inputs, targets, _ = value_fixture(directory)
        elapsed = [request["intervals"][i % 4]["elapsed_micros"] for i in range(32)]
    elif backend == "population_grid":
        model, request, old_inputs, targets, _ = grid_fixture(directory, spatial_bins=8)
        elapsed = [800_000] * 12
    elif backend == "population_age":
        model, request, old_inputs, targets, _ = age_fixture(directory, spatial_bins=8)
        elapsed = [200_000] * 14
    else:
        raise ValueError("unknown cancellation backend")
    original = request["intervals"]
    start, plans = original[0]["start_micros"], []
    for index, dt in enumerate(elapsed):
        plan = dict(original[index % len(original)], start_micros=start, end_micros=start+dt,
                    elapsed_micros=dt)
        if backend == "value_kernel":
            plan.update(substep_micros=dt, substeps=1)
        elif backend == "population_grid":
            plan["substeps"] = dt // model.spec.step_micros
        plans.append(plan)
        start += dt
    indices = torch.arange(len(plans)) % old_inputs.shape[1]
    inputs = old_inputs[:, indices].clone()
    request.update(intervals=plans, inputs=inputs.tolist(), targets=targets.tolist(),
        target_time_micros=start+request["time_profile"]["forecast_horizon_micros"],
        optimizer_steps=OPTIMIZER_STEPS,
        limits=dict(max_optimizer_steps=OPTIMIZER_STEPS, max_batch=inputs.shape[0],
                    max_intervals=len(plans), max_elements=MAX_ELEMENTS))
    request["operation_id"] += ":cancel-workload-v1"
    initial = model.initial_state(inputs)
    bind_initialization(request, initial, "fresh")
    if backend == "population_age":
        intervals = population_age_intervals(plans, request["time_profile"], model.spec)
        event_steps = sum(map(len, model.event_schedule(intervals, initial)))
        working = model.working_elements(inputs.shape[0], intervals, initial)
    elif backend == "population_grid":
        intervals = population_intervals(plans, request["time_profile"], model.spec)
        event_steps = sum(intervals)
        working = model.working_elements(inputs.shape[0], intervals)
    else:
        intervals = interval_seconds(plans, request["time_profile"])
        event_steps = len(intervals)
        working = inputs.shape[0]*(len(intervals)*(model.spec.input_size
            + 4*model.spec.hidden_size*len(model.cells))+model.spec.output_size)
    if working > MAX_ELEMENTS:
        raise ValueError("cancellation trace exceeds the existing worker tensor-work bound")
    wire_bytes = len(json.dumps(request, indent=2, allow_nan=False).encode()) + 1
    if wire_bytes > MAX_HOST_WIRE:
        raise ValueError("cancellation request exceeds the Agentd public wire bound")
    workload = dict(schema_version=1, backend=backend, logical_cells=len(model.cells),
        spatial_bins=getattr(model.spec, "spatial_bins", None), graph_digest=digest(graph_spec_dict(model.spec)),
        temporal_profile_digest=request["binding"]["profile_digest"], batch=inputs.shape[0],
        coarse_intervals=len(intervals), event_steps_per_sample=event_steps,
        working_elements=working, maximum_elements=MAX_ELEMENTS, maximum_optimizer_steps=OPTIMIZER_STEPS,
        request_bytes=wire_bytes, maximum_host_wire_bytes=MAX_HOST_WIRE,
        scope="real bounded process-cancellation workload; not the 32-bin numerical-quality fixture")
    return model, request, inputs, targets, intervals, workload


def preflight_cancellation_fixture(directory, model, request):
    """Retain one uncancelled proposal through the actual worker admission path."""
    root = Path(directory)/"cancellation-preflight"
    root.mkdir(mode=0o700)
    one = copy.deepcopy(request)
    one["optimizer_steps"] = 1
    one["operation_id"] += ":preflight"
    write_new(root/"request.json", one)
    payload, receipt = propose(model, one)
    if receipt["completed_optimizer_steps"] != 1 or receipt["logical_cells"] != 2:
        raise ValueError("real cancellation preflight did not complete one joint optimizer step")
    write_new(root/"candidate.pt", payload)
    write_new(root/"receipt.json", receipt)
    result = dict(schema_version=1, status="passed", admitted_optimizer_steps=1,
        cancellation_optimizer_steps=request["optimizer_steps"],
        original_request_digest=digest(request), preflight_request_digest=digest(one),
        graph_digest=receipt["graph_digest"], initial_state_digest=receipt["initial_state_digest"],
        wall_seconds=receipt["wall_seconds"], cpu_seconds=receipt["cpu_seconds"],
        checkpoint_sha256=receipt["checkpoint_sha256"],
        measurement_scope=receipt["measurement_scope"], uncancelled_64_step_duration_measured=False,
        optimizer_entry_in_cancelled_process_proven=False, production=False)
    write_new(root/"result.json", result)
    return result
