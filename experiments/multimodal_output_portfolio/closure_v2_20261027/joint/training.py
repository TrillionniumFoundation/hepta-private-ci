"""Score-function training from serialized final outcomes, with matched work."""

from copy import deepcopy
import hashlib
import math
import time

import numpy as np
import torch

from ...v6.data import make_batch
from ...v6.neural import NeuralState, parameter_hash
from ...continuation_20261027.joint.training import actual_utilities
from .actor import (LatentActor, LatentSnapshot, antithetic_gradient,
                    shift_state, state_features, terminal_state)
from .protocol import PROTOCOL as P, checksum, write_json


@torch.inference_mode()
def fit_basis(base, corpus, seed):
    rows = []
    for index, condition in enumerate(P["conditions"]):
        for start in range(0, 128, 32):
            batch = make_batch(corpus, "train", 32, seed * 3109 + index * 128 + start,
                               corruption=condition)
            rng = torch.Generator().manual_seed(seed * 1013 + index * 128 + start)
            state, _ = terminal_state(base, batch.observation,
                                      torch.randn(32, base._base._model.hidden, generator=rng))
            rows.append(torch.cat((state.h, state.image, state.text), dim=1))
    values = torch.cat(rows)
    centered = values - values.mean(0)
    _, singular, right = torch.linalg.svd(centered, full_matrices=False)
    basis = right[:P["dimensions"]] * (singular[:P["dimensions"]] / math.sqrt(len(values) - 1))[:, None]
    return basis.contiguous(), {"training_examples": len(values), "labels_used": False,
        "retained_variance_fraction": float(singular[:P["dimensions"]].square().sum() / singular.square().sum()),
        "state_sha256": hashlib.sha256(values.numpy().tobytes()).hexdigest(),
        "basis_sha256": hashlib.sha256(basis.numpy().tobytes()).hexdigest()}


def costs(utility, arm):
    if arm == "direct_mean":
        return -utility
    if arm == "direct_risk":
        return torch.expm1(-P["gamma"] * utility) / P["gamma"]
    raise ValueError("Unknown direct training objective")


def fit(base, basis, corpus, reward, seed, arm, directory, steps=None):
    steps = P["steps"] if steps is None else steps
    torch.manual_seed(seed * 73 + 19)
    actor = LatentActor(4 * base._base._model.hidden, P["dimensions"], P["hidden"])
    initial_hash = parameter_hash(actor)
    optimizer = torch.optim.Adam(actor.parameters(), lr=P["learning_rate"])
    rng = torch.Generator().manual_seed(seed * 1019 + 271028)
    frozen_hashes = parameter_hash(base._base._model), parameter_hash(base._gate), parameter_hash(reward)
    schedule, delivered = hashlib.sha256(), hashlib.sha256()
    history, checkpoints, trace_costs, trace_gradients = [], [], [], []
    started_wall, started_cpu = time.perf_counter_ns(), time.process_time_ns()
    n, k, d = P["batch_size"], P["directions"], P["dimensions"]
    for step in range(steps):
        condition = P["conditions"][step % 4]
        batch_seed = seed * 1000003 + step * 19 + 271028
        batch = make_batch(corpus, "train", n, batch_seed, corruption=condition)
        noise = torch.randn(n, base._base._model.hidden, generator=rng)
        eps = torch.randn(k, n, d, generator=rng)
        schedule.update(str(batch_seed).encode())
        schedule.update(noise.numpy().tobytes())
        schedule.update(eps.numpy().tobytes())
        with torch.no_grad():
            state, _ = terminal_state(base, batch.observation, noise)
            features = state_features(state)
        mean = actor(features)
        positive = mean.detach()[None] + P["sigma"] * eps
        negative = mean.detach()[None] - P["sigma"] * eps
        coefficients = torch.cat((positive, negative)).flatten(0, 1)
        repeated = NeuralState(*(getattr(state, field).repeat(2 * k, 1)
                                 for field in ("h", "image", "text", "context")))
        target = type(batch.target)(*(getattr(batch.target, field).repeat(2 * k, *([1] * (getattr(batch.target, field).ndim - 1)))
                                     for field in ("pixels", "text_tokens", "labels")))
        with torch.no_grad():
            output = base._base._model.decode(shift_state(repeated, coefficients, basis))
            utility, hashes, captions = actual_utilities(output, target, reward)
            delivered.update("\n".join(hashes + captions).encode())
            actual_cost = costs(utility, arm).reshape(2, k, n)
            gradient = antithetic_gradient(actual_cost[0], actual_cost[1], eps, P["sigma"])
        # This scalar has precisely the likelihood-ratio parameter derivative.
        reward_surrogate = (mean * gradient).sum(-1).mean()
        clean_kl = mean.square().sum(-1).mean() / (2 * P["sigma"] ** 2)
        regularizer = P["clean_kl_coefficient"] * clean_kl if condition == "clean" else 0. * clean_kl
        surrogate = reward_surrogate + regularizer
        optimizer.zero_grad(set_to_none=True)
        surrogate.backward()
        norm = torch.nn.utils.clip_grad_norm_(actor.parameters(), P["gradient_clip"])
        if not torch.isfinite(norm):
            raise FloatingPointError("Nonfinite direct-outcome gradient")
        optimizer.step()
        history.append({"step": step + 1, "condition": condition,
                        "actual_objective": float(actual_cost.mean()),
                        "actual_mean_utility": float(utility.mean()),
                        "clean_kl": float(clean_kl.detach()), "preclip_gradient_norm": float(norm),
                        "mean_shift_rms": float(mean.detach().square().mean().sqrt())})
        trace_costs.append(actual_cost.numpy())
        trace_gradients.append(gradient.numpy())
        if (step + 1) % 50 == 0:
            print(f"direct seed={seed} arm={arm} step={step + 1} U={history[-1]['actual_mean_utility']:.5f}", flush=True)
        if step + 1 in P["checkpoints"] or step + 1 == steps:
            path = directory / f"seed-{seed}-{arm}-step-{step + 1}.pt"
            snapshot = LatentSnapshot(base, deepcopy(actor), basis, P["sigma"],
                                      {"seed": seed, "arm": arm, "step": step + 1})
            snapshot.save(path)
            restored = LatentSnapshot.load(path, base)
            if parameter_hash(restored.actor) != parameter_hash(actor):
                raise RuntimeError("Serialized actor differs")
            checkpoints.append({"step": step + 1, "path": path.name, "sha256": checksum(path)})
    if frozen_hashes != (parameter_hash(base._base._model), parameter_hash(base._gate), parameter_hash(reward)):
        raise RuntimeError("Direct training mutated a frozen reference")
    trace = directory / f"TRACE-{seed}-{arm}.npz"
    np.savez_compressed(trace, actual_costs=np.stack(trace_costs), gradients=np.stack(trace_gradients))
    torch.save({"actor": actor.state_dict(), "optimizer": optimizer.state_dict(), "rng_state": rng.get_state()},
               directory / f"OPTIMIZER-{seed}-{arm}.pt")
    record = {"seed": seed, "arm": arm, "steps": steps, "history": history,
        "checkpoints": checkpoints, "trace_sha256": checksum(trace), "actor_before": initial_hash,
        "actor_after": parameter_hash(actor), "actor_parameters": sum(p.numel() for p in actor.parameters()),
        "schedule_sha256": schedule.hexdigest(), "actual_output_stream_sha256": delivered.hexdigest(),
        "frozen_model_gate_reward_hashes": frozen_hashes,
        "wall_ns": time.perf_counter_ns() - started_wall, "cpu_ns": time.process_time_ns() - started_cpu,
        "training_counts": {"encoder_examples": steps * n, "gate_examples": steps * n,
            "transition_examples": 2 * steps * n, "actor_examples": steps * n,
            "decoder_examples": 2 * k * steps * n, "actual_png_roundtrips": 2 * k * steps * n,
            "observer_digit_examples": 4 * k * steps * n, "optimizer_updates": steps},
        "unbiased_reward_gradient_before_clipping": True, "optimizer_globally_optimal": False,
        "training_media_retention": "actual PNG/UTF8 roundtrips scored, stream hash and paired cost/gradient traces retained; individual training media reproducible from frozen sources/RNG, not all individually archived"}
    write_json(directory / f"TRAINING-{seed}-{arm}.json", record)
    return record
