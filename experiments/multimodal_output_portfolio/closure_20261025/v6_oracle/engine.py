"""Public-only inference; independent truth enters only after media readback."""

from itertools import product
from pathlib import Path
import time

import torch

from ...v6.data import Observation, render_tokens
from ...v6.neural import ACTIONS
from ...v6.observer import observe_tensors, read_bundle, write_bundle
from ...v6.plan_training import ALLOCATION_PLAN, PLANS
from ...v6.run import rollout


def paths(mode, horizon=3):
    actions = ACTIONS if mode == "full" else ALLOCATION_PLAN
    return [p for length in range(horizon + 1) for p in product(actions, repeat=length)]


@torch.inference_mode()
def enumerate_public(snapshot, observation, noise_seed, mode):
    """All permitted deterministic continuation endpoints from one shared root."""
    if type(observation) is not Observation or mode not in ("full", "allocation"):
        raise TypeError("Only registered public observations and modes are supported")
    root = snapshot.encode(observation, noise_seed, content_control=mode == "full")
    states = {(): root}
    initial = ALLOCATION_PLAN if root.plan_index == -1 else PLANS[root.plan_index]
    for path in paths(mode):
        if path:
            states[path] = snapshot.step(states[path[:-1]], path[-1])
        state = states[path]
        output = snapshot.decode(state)
        yield path, output.image_logits.sigmoid(), render_tokens(output.token_ids[0]), {
            "state_sha256": snapshot.state_key(state), "initial_content_plan": list(initial),
            "initial_plan_index": root.plan_index,
        }
    snapshot.verify_integrity()


@torch.inference_mode()
def fixed_public(snapshot, observation, noise_seed, mode, path):
    if type(observation) is not Observation or tuple(path) not in paths(mode):
        raise ValueError("Invalid public fixed request")
    state = snapshot.encode(observation, noise_seed, content_control=mode == "full")
    initial = ALLOCATION_PLAN if state.plan_index == -1 else PLANS[state.plan_index]
    for action in path:
        state = snapshot.step(state, action)
    output = snapshot.decode(state)
    snapshot.verify_integrity()
    return output.image_logits.sigmoid(), render_tokens(output.token_ids[0]), {
        "actions": list(path), "initial_content_plan": list(initial),
        "final_state_sha256": snapshot.state_key(state), "mode": mode,
    }


def materialize(directory, pixels, caption, observer, target):
    """Score only the actual durable PNG and UTF-8 text; never decoder logits."""
    emitted = write_bundle(directory, caption, pixels)
    restored_pixels, restored_caption, hashes = read_bundle(emitted)
    scores = observe_tensors(observer, restored_pixels, [restored_caption], target.pixels, target.labels)[0]
    return {"output_paths": {k: str(Path(v).name) for k, v in emitted.items()},
            "output_hashes": hashes, "metrics": scores}


def policy_request(snapshot, forecast, observation, noise_seed, policy, selected, directory, observer, target, control):
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    if policy in selected:
        choice = selected[policy]
        pixels, caption, trace = fixed_public(snapshot, observation, noise_seed, choice["mode"], choice["path"])
    else:
        pixels, caption, trace = rollout(snapshot, forecast, observation, policy, 64,
            {"inference_horizon": 3, "control": control}, "v6-oracle-public-request", noise_seed)
        trace["mode"] = "allocation" if policy == "allocation_only" else "full"
    # All generation and policy decisions finish before target/observer use.
    generation_wall = time.perf_counter_ns() - wall
    actual = materialize(directory, pixels, caption, observer, target)
    return {**trace, **actual, "policy": policy, "generation_wall_ns": generation_wall,
            "whole_request_wall_ns": time.perf_counter_ns() - wall,
            "whole_request_cpu_ns": time.process_time_ns() - cpu}
