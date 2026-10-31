"""Resident, causally executed policies with every planning and emission cost.

Inputs are public Observations. Targets and observers are absent from this
module. The owner supplies hidden, path-indexed actual innovation streams;
planning has a separate registered namespace and never receives those streams.
"""

from collections import Counter
import time

import torch

from ..v7.model import State
from .control import PLANS
from .media import RawMediaArchive, reopen_archive_records
from .runtime import (PublicFrame, initialize, public_features, public_frame,
                      transition, work_counts)
from .trees import stable_seed


def root_frame(data, indices=None):
    """Reconstruct current public state; never load any child or terminal label."""
    indices = slice(None) if indices is None else indices
    features = data["features"][indices, 0]
    state = State(*(features[:, start:start + 96].detach().clone() for start in (0, 96, 192, 288)),
                  content_control=True, step_count=2)
    return PublicFrame(state, data["root_pixels"][indices].float(),
                       data["root_tokens"][indices].clone(), remaining=2)


@torch.no_grad()
def resident_episode(model, observation, *, policy_name, actual_stream_key,
                     archive_path, feedback=None, route=None, static_plan=None,
                     planning_seed=0):
    """Time input encoding through final file fsync/reopen, with no offline score.

    Models/heads are resident CPU objects; public input tensors already exist.
    This is a complete request cost within that stated contract, not a cold
    model-load, network-upload or general service-latency claim. Metadata writes
    by the caller and offline scoring are separately accounted process costs.
    """
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    work = Counter()
    interventions = {}
    if policy_name == "allocation_only_feedback":
        interventions["content_mode"] = "allocation_only"
    elif policy_name == "shared_state_clamp_semantic_couple":
        interventions["shared_mode"] = "clamped_initial"
    elif policy_name == "encoder_initial_only_fixed":
        interventions["context_mode"] = "initial_only_context_intervention"
    def generator(path):
        return torch.Generator().manual_seed(stable_seed("actual-resident", *actual_stream_key, path))
    run = initialize(model, observation, generator=generator(()), **interventions)
    path = []
    planned = None
    if policy_name in {"fixed", "encoder_initial_only_fixed"}:
        planned = ("refine_image", "refine_text")
    elif policy_name in {"semantic_couple_fixed", "shared_state_clamp_semantic_couple"}:
        planned = ("refine_semantic", "couple")
    elif policy_name == "tuned_static":
        if static_plan is None or tuple(static_plan) not in PLANS:
            raise ValueError("A frozen bounded static plan is required")
        planned = tuple(static_plan)
    elif policy_name == "one_shot_route":
        if route is None:
            raise ValueError("A frozen one-shot route head is required")
        features = public_features(model, public_frame(run), work=work)
        choice = route.choose(features)
        if len(choice) != 1:
            raise ValueError("Resident episodes must have batch size one")
        planned = PLANS[int(choice[0])]
        work.update({"route_calls": 1, "route_examples": 1})
    elif feedback is None:
        raise ValueError("A frozen feedback head is required")
    while not run.done:
        if planned is not None:
            action = planned[len(path)] if len(path) < len(planned) else "stop"
        elif policy_name == "independent_random_stream_MPC":
            from .planning import mpc_actions
            selected = mpc_actions(model, public_frame(run), feedback, planning_seed, work=work)
            action = ("stop", "refine_semantic", "refine_image", "refine_text", "couple")[int(selected[0])]
        else:
            action = feedback.action(model, public_frame(run), work)
        if action != "stop":
            path.append(action)
        run = transition(model, run, action, generator=generator(tuple(path)))
    work.update(work_counts(run))
    with RawMediaArchive(archive_path) as archive:
        pixels, captions, raw = archive.append(run.pixels, run.tokens)
    pixels, captions = reopen_archive_records(archive_path, raw)
    return {"path": tuple(path), "run": run, "pixels": pixels, "captions": captions,
            "raw": raw, "wall_ns": time.perf_counter_ns() - wall,
            "cpu_ns": time.process_time_ns() - cpu, "work": dict(work),
            "planner_counters_are_subsets_not_additional_work": True,
            "resident_model_and_prepared_public_tensor_inputs": True}


@torch.no_grad()
def fixed_intervention(model, observation, *, path, actual_stream_key,
                       shared_mode="adaptive", context_mode="persistent"):
    """Paired finite mechanism experiment, using the materialized-tree streams."""
    def generator(prefix):
        return torch.Generator().manual_seed(stable_seed("generation", *actual_stream_key, prefix))
    run = initialize(model, observation, generator=generator(()), shared_mode=shared_mode,
                     context_mode=context_mode)
    initial = public_frame(run)
    for index, action in enumerate(path):
        run = transition(model, run, action, generator=generator(tuple(path[:index + 1])))
    return run, initial
