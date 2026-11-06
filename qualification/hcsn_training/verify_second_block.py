"""A fresh worker trains a second block from the owner's recovered full state."""

import copy
from dataclasses import asdict
import sys

import torch
from .handoff import dataset_digest, execution_sources, runtime_tuple
from .joint_graph import digest, interval_seconds, load_training_checkpoint, tensor_digest
from .population_graph import PopulationCellGraph, population_intervals


def verify(parent, native, model, initial, inputs, profile):
    from .verify_bridge import read, run, sha, state_digest, write_new
    root = parent/"second-block"
    root.mkdir()
    base = sha(parent/"readback.pt")
    clock = read(parent/"candidate-clock.json")
    binding = dict(read(parent/"request.json")["binding"], model_digest=base)
    start = clock["last_micros"]
    offsets = [200_000, 300_000]
    if not isinstance(model, PopulationCellGraph):
        # A has one delayed boundary per state transition. Four intervals are
        # needed for every parameter of this two-cell graph to reach final loss.
        inputs = inputs.repeat(1, 2, 1)
        offsets += [500_000, 600_000]
    write_new(root/"clock-input.json", dict(profile=profile, binding=binding, start_micros=start,
        ends=[start+offset for offset in offsets], initial_state_digest=state_digest(initial)))
    run(root, "native-plan", [native, "plan", root])
    if read(root/"training-clock.json") != clock:
        raise AssertionError("second training block did not retain the owner candidate clock")
    plans = read(root/"training-plan.json")["intervals"]
    request = dict(schema_version=2, mechanism="task_mse_bp_v1", operation_id="hcsn:bridge-second-block",
        binding=binding, intervals=plans, time_profile=profile, inputs=inputs.tolist(),
        targets=[[.2] for _ in range(inputs.shape[0])],
        target_time_micros=start+offsets[-1]+profile["forecast_horizon_micros"],
        learning_rate=.01, optimizer_steps=2, initialization=dict(mode="resume", clock_checkpoint=clock),
        limits=dict(max_optimizer_steps=2, max_batch=2, max_intervals=len(offsets), max_elements=1_048_576),
        base_checkpoint=dict(path=str(parent/"readback.pt"), sha256=base))
    admitted = dict(operation_id=request["operation_id"], request_digest=digest(request),
        training_code_digest=digest(execution_sources()), runtime_tuple_digest=digest(runtime_tuple("torch.float64")),
        graph_digest=digest(asdict(model.spec)), time_profile_digest=binding["profile_digest"],
        base_checkpoint_digest=base, dataset_digest=dataset_digest(request), target_generation=binding["generation"],
        optimizer_steps=2, logical_cells=len(model.cells), trainable_parameters=sum(p.numel() for p in model.parameters()))
    write_new(root/"request.json", request)
    write_new(root/"admitted.json", admitted)
    inputs_hash, expected = state_digest(initial), copy.deepcopy(model)
    intervals = (population_intervals(plans, profile, model.spec) if isinstance(model, PopulationCellGraph)
                 else interval_seconds(plans, profile))
    targets = torch.tensor(request["targets"], dtype=inputs.dtype)
    for _ in range(2):
        # Do not call the worker's gradient helper in the independent oracle:
        # a helper regression that dropped `state` must remain detectable.
        output, _ = expected(inputs, intervals, state=initial)
        loss = (output[:, -1]-targets).square().mean()
        parameters = dict(expected.named_parameters())
        gradients = dict(zip(parameters, torch.autograd.grad(loss, tuple(parameters.values()))))
        with torch.no_grad():
            for name, parameter in expected.named_parameters():
                parameter.add_(gradients[name], alpha=-.01)
    with torch.no_grad():
        prediction, final = expected(inputs, intervals, state=initial)
        reset_prediction = expected(inputs, intervals)[0]
    # An explicit comparison makes a silently reset implementation observable.
    reset_difference = float((prediction-reset_prediction).abs().max())
    if reset_difference == 0:
        raise AssertionError("second-block fixture does not distinguish resume from reset")
    child = run(root, "python-worker", [sys.executable, "-m", "qualification.hcsn_training.worker",
        "--request", root/"request.json", "--output", root/"worker"])
    receipt = read(root/"worker/receipt.json")
    candidate = sha(root/"worker/candidate.pt")
    restored, state, metadata = load_training_checkpoint(root/"worker/candidate.pt", candidate)
    if (tensor_digest(expected.state_dict()) != tensor_digest(restored.state_dict())
            or state_digest(final) != state_digest(state)
            or prediction[:, -1].tolist() != receipt["final_prediction"]
            or receipt["initial_state_digest"] != inputs_hash or state_digest(initial) != inputs_hash
            or receipt["initialization_mode"] != "resume" or sha(parent/"readback.pt") != base):
        raise AssertionError("resumed second-block training differs from independent same-state SGD")
    write_new(root/"candidate-state.json", dict(checkpoint_sha256=candidate,
        state_digest=state_digest(state), last_end_micros=metadata["last_end_micros"]))
    run(root, "native-publication", [native, "publish", root])
    run(root, "native-cold-owner", [native, "reopen", root])
    result = dict(status="passed", mode="resume", optimizer_steps=2, intervals=len(offsets), worker_pid=child["pid"],
        initial_state_digest=inputs_hash, initial_time_micros=start, base_checkpoint_digest=base,
        candidate_digest=candidate, complete_state_exact=True, weights_exact=True, prediction_exact=True,
        initial_state_unchanged=True, original_checkpoint_unchanged=True, reset_prediction_max_difference=reset_difference,
        native_publication=read(root/"publication.json"), cold_owner=read(root/"cold-owner.json"),
        branch="independent training branch from the published candidate clock; inference continuation is a separate fixture branch",
        scope="second completed-block training; fixture trust only; not multi-generation quality improvement")
    write_new(root/"result.json", result)
    return result
