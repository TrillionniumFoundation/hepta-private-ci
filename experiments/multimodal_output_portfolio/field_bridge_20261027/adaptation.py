"""Empirical field MPC over real optimizer updates, with common exploratory data.

The regressor predicts hard fixed-policy reward from training-only observables.
It is an estimated finite-action controller, not a Riccati/FBSDE implementation.
"""

from dataclasses import replace
import hashlib
import time

import numpy as np
import torch
from torch.nn import functional as F

from ..v6.data import make_batch, render_tokens, SourceCorpus
from ..v6.observer import observe_tensors
from .adapters import make_model, local_parameters, local_state, local_hash, displacement, frozen_base_hash
from .protocol import P
from .task import ACTIONS

FIELD_NAMES = ["adapt_image_bce", "adapt_text_ce", "clean_joint_loss",
               "effective_operator_displacement", "momentum_rms", "learning_time"]
RICH_NAMES = FIELD_NAMES + ["adapt_digit_ce", "clean_image_bce", "clean_text_ce", "clean_digit_ce",
                           "image_intensity", "text_entropy", "image_operator_displacement",
                           "text_operator_displacement"]


def fixed_output(model, batch, action, seed, teacher=False):
    generator = torch.Generator().manual_seed(seed)
    noise = torch.randn(len(batch.observation.pixels), model.hidden, generator=generator)
    state = model.step(model.encode(batch.observation, noise), "couple")
    if action:
        state = model.step(state, ACTIONS[action])
    return model.decode(state, batch.target.text_tokens if teacher else None)


def panels(corpus, seed):
    result = {}
    for name, offset, size, corruption in (
        ("adapt", P["probe_adapt_offset"], P["probe_pairs"], "heavy_noise"),
        ("clean", P["probe_clean_offset"], P["probe_pairs"], "clean"),
        ("value", P["training_value_offset"], P["training_value_pairs"], "missing"),
    ):
        result[name] = make_batch(corpus, "train", size, 271027 + seed,
                                  offset=offset, corruption=corruption)
    return result


def gradient_corpus(corpus):
    source = corpus.splits["train"]
    size = P["gradient_source_count"]
    restricted = replace(source, images=source.images[:size], labels=source.labels[:size],
                         ids=source.ids[:size], pixel_hashes=source.pixel_hashes[:size])
    return SourceCorpus({**corpus.splits, "train": restricted}, corpus.manifest)


@torch.no_grad()
def observe_field(model, optimizer, fixed, action, step):
    out_a = fixed_output(model, fixed["adapt"], action, 771, teacher=True)
    out_c = fixed_output(model, fixed["clean"], action, 883, teacher=True)
    la, lc = model.loss(out_a, fixed["adapt"].target), model.loss(out_c, fixed["clean"].target)
    squares, count = 0., 0
    for state in optimizer.state.values():
        if "momentum_buffer" in state:
            buffer = state["momentum_buffer"]
            squares += float(buffer.square().sum())
            count += buffer.numel()
    delta = displacement(model)
    probability = out_a.text_logits.softmax(-1)
    entropy = -(probability * probability.clamp_min(1e-12).log()).sum(-1).mean()
    vector = [float(la["image_bce"].mean()), float(la["text_ce"].mean()), float(lc["joint"].mean()),
              float(np.sqrt(np.mean(np.square(delta)))), (squares / max(count, 1)) ** .5,
              step / P["steps"], float(la["digit_ce"].mean()), float(lc["image_bce"].mean()),
              float(lc["text_ce"].mean()), float(lc["digit_ce"].mean()),
              float(out_a.image_logits.sigmoid().mean()), float(entropy), delta[0],
              float(np.sqrt(np.mean(np.square(delta[1:]))))]
    if not np.isfinite(vector).all():
        raise FloatingPointError("Nonfinite parameter field")
    return np.array(vector, dtype=np.float64)


@torch.inference_mode()
def hard_value(model, batch, observer, action):
    output = fixed_output(model, batch, action, 991)
    pixels = (output.image_logits.sigmoid() * 255).round() / 255
    captions = [render_tokens(row) for row in output.token_ids]
    scores = observe_tensors(observer, pixels, captions, batch.target.pixels, batch.target.labels)
    return float(np.mean([row["utility"] for row in scores])) - P["refinement_charge"] * (1 + (action != 0))


def update(model, teacher, optimizer, batch, action, multiplier, noise_seed):
    output = fixed_output(model, batch, action, noise_seed, teacher=True)
    with torch.no_grad():
        reference = fixed_output(teacher, batch, action, noise_seed, teacher=True)
    supervised = model.loss(output, batch.target)["joint"].mean()
    anchor = (output.image_logits.sigmoid() - reference.image_logits.sigmoid()).square().mean()
    anchor += .1 * F.kl_div(output.text_logits.log_softmax(-1), reference.text_logits.softmax(-1),
                            reduction="batchmean")
    objective = supervised + P["teacher_anchor"] * anchor
    optimizer.zero_grad(set_to_none=True)
    objective.backward()
    norm = torch.nn.utils.clip_grad_norm_(local_parameters(model), P["gradient_clip"])
    if not torch.isfinite(objective) or not torch.isfinite(norm):
        raise FloatingPointError("Nonfinite local adaptation")
    if multiplier != 0:
        for group in optimizer.param_groups:
            group["lr"] = P["learning_rate"] * multiplier
        optimizer.step()
    return {"proxy_loss": float(objective.detach()), "gradient_norm": float(norm),
            "weights_and_momentum_advanced": multiplier != 0}


def new_optimizer(model):
    return torch.optim.SGD(local_parameters(model), lr=P["learning_rate"], momentum=P["momentum"])


def explore(original, corpus, observer, seed, action, progress):
    fixed, gradient_data = panels(corpus, seed), gradient_corpus(corpus)
    records, endpoints = [], []
    started = time.perf_counter_ns()
    for trajectory in range(P["bank_train_trajectories"] + P["bank_audit_trajectories"]):
        model = make_model(original, seed)
        optimizer = new_optimizer(model)
        base_identity = frozen_base_hash(model)
        rng = np.random.default_rng(seed * 1009 + trajectory)
        current = observe_field(model, optimizer, fixed, action, 0)
        for step in range(P["steps"]):
            choice = trajectory if trajectory < 4 else int(rng.integers(len(P["multipliers"])))
            schedule_id = 0 if trajectory < 4 else trajectory
            batch = make_batch(gradient_data, "train", P["batch_size"],
                               seed * 100003 + schedule_id * 1009 + step,
                               corruption=P["training_conditions"][step % 4])
            info = update(model, original, optimizer, batch, action, P["multipliers"][choice], 107 + step)
            successor = observe_field(model, optimizer, fixed, action, step + 1)
            value = hard_value(model, fixed["value"], observer, action)
            records.append({"trajectory": trajectory, "step": step, "action": choice,
                            "state": current.tolist(), "next_state": successor.tolist(),
                            "hard_value": value, **info})
            current = successor
        if base_identity != frozen_base_hash(model):
            raise RuntimeError("Exploratory adaptation changed its frozen base")
        endpoints.append({"trajectory": trajectory, "final_value": value, "adapter_sha256": local_hash(model)})
        progress(f"seed={seed} common rollout {trajectory + 1}/8 finished")
    return {"records": records, "endpoints": endpoints, "wall_ns": time.perf_counter_ns() - started,
            "gradient_steps": len(records), "examples_per_gradient": P["batch_size"],
            "probe_examples_per_step": 2 * P["probe_pairs"],
            "value_examples_per_step": P["training_value_pairs"],
            "audit_trajectories_used_for_selection": False}


def phi(values):
    values = np.asarray(values)
    return np.concatenate((np.ones((*values.shape[:-1], 1)), values, values * values), axis=-1)


def fit_controller(bank, mode):
    training = [row for row in bank["records"] if row["trajectory"] < P["bank_train_trajectories"]]
    raw = np.array([row["state"] for row in training])
    mean, scale = raw.mean(0), np.maximum(raw.std(0), 1e-5)
    if mode == "field":
        projection = np.eye(len(RICH_NAMES))[:, :len(FIELD_NAMES)]
    elif mode == "generic":
        projection, _ = np.linalg.qr(np.random.default_rng(271027).normal(size=(len(RICH_NAMES), len(FIELD_NAMES))))
    elif mode == "richer":
        projection = np.eye(len(RICH_NAMES))
    else:
        raise ValueError("Unknown observation profile")
    z = ((raw - mean) / scale) @ projection
    following = ((np.array([row["next_state"] for row in training]) - mean) / scale) @ projection
    y = np.column_stack((following - z, [row["hard_value"] for row in training]))
    coefficients = []
    for action in range(len(P["multipliers"])):
        selected = np.array([row["action"] == action for row in training])
        design = phi(z[selected])
        regularizer = P["dynamics_ridge"] * np.eye(design.shape[1])
        regularizer[0, 0] = 0
        coefficients.append(np.linalg.solve(design.T @ design + regularizer, design.T @ y[selected]))
    record = {"mode": mode, "mean": mean.tolist(), "scale": scale.tolist(),
              "projection": projection.tolist(), "coefficients": np.array(coefficients).tolist(),
              "fit_rows": len(training), "fit_trajectories": P["bank_train_trajectories"],
              "dimension": int(z.shape[1]), "feature_names": FIELD_NAMES if mode == "field" else RICH_NAMES,
              "state_clip": 10., "reward_clip": [-1.1, 1.0]}
    errors, state_errors = [], []
    for row in bank["records"]:
        if row["trajectory"] < P["bank_train_trajectories"]:
            continue
        current = project(record, row["state"])
        next_pred, reward_pred = predict(record, current, row["action"])
        errors.append(reward_pred - row["hard_value"])
        state_errors.append(np.mean((next_pred - project(record, row["next_state"])) ** 2))
    record["heldout_trajectory_audit"] = {"rows": len(errors), "reward_mae": float(np.abs(errors).mean()),
        "reward_rmse": float(np.sqrt(np.square(errors).mean())), "next_field_rmse": float(np.sqrt(np.mean(state_errors)))}
    return record


def project(controller, raw):
    return ((np.asarray(raw) - controller["mean"]) / controller["scale"]) @ np.asarray(controller["projection"])


def predict(controller, state, action):
    state = np.clip(state, -controller["state_clip"], controller["state_clip"])
    predicted = phi(state) @ np.asarray(controller["coefficients"])[action]
    return np.clip(state + predicted[:-1], -10., 10.), float(np.clip(predicted[-1], -1.1, 1.0))


def choose_update(controller, raw, remaining):
    state = project(controller, raw)
    scores = []
    for action in range(len(P["multipliers"])):
        following, value = predict(controller, state, action)
        if remaining > 1:
            value = max(predict(controller, following, other)[1] for other in range(len(P["multipliers"])))
        scores.append(value)
    return int(np.argmax(scores)), scores


def adapt(original, corpus, observer, seed, action, mode, bank, progress):
    started = time.perf_counter_ns()
    model, fixed = make_model(original, seed), panels(corpus, seed)
    optimizer, data = new_optimizer(model), gradient_corpus(corpus)
    initial, base_identity = local_state(model), frozen_base_hash(model)
    initial_identity = local_hash(model)
    fixed_choice = int(np.argmax([row["final_value"] for row in bank["endpoints"][:4]]))
    fit_started = time.perf_counter_ns()
    controller = None if mode == "ordinary" else fit_controller(bank, mode)
    controller_fit_wall_ns = time.perf_counter_ns() - fit_started
    history, schedule = [], hashlib.sha256()
    current = observe_field(model, optimizer, fixed, action, 0)
    for step in range(P["steps"]):
        choice, predictions = (fixed_choice, []) if controller is None else choose_update(controller, current, P["steps"] - step)
        batch_seed = seed * 100003 + 90000 + step
        batch = make_batch(data, "train", P["batch_size"], batch_seed,
                           corruption=P["training_conditions"][step % 4])
        schedule.update(str(batch_seed).encode())
        info = update(model, original, optimizer, batch, action, P["multipliers"][choice], 107 + step)
        successor = observe_field(model, optimizer, fixed, action, step + 1)
        value = hard_value(model, fixed["value"], observer, action)
        history.append({"step": step, "action": choice, "state": current.tolist(), "next_state": successor.tolist(),
                        "predicted_two_step_values": predictions, "hard_fixed_value": value, **info})
        current = successor
    if base_identity != frozen_base_hash(model):
        raise RuntimeError("Local adaptation modified frozen base parameters")
    changes = {name: not torch.equal(value, dict(model.named_parameters())[name].detach()) for name, value in initial.items()}
    result = {"mode": mode, "seed": seed, "controller": controller, "history": history,
              "ordinary_fixed_action": fixed_choice, "adapter_parameter_changes": changes,
              "initial_adapter_sha256": initial_identity, "final_adapter_sha256": local_hash(model),
              "frozen_base_sha256": base_identity, "schedule_sha256": schedule.hexdigest(),
              "steps": P["steps"], "trainable_parameters": sum(p.numel() for p in local_parameters(model)),
              "wall_ns": time.perf_counter_ns() - started, "controller_fit_wall_ns": controller_fit_wall_ns,
              "gradient_examples": P["steps"] * P["batch_size"],
              "probe_examples": (P["steps"] + 1) * 2 * P["probe_pairs"],
              "value_examples": P["steps"] * P["training_value_pairs"],
              "direct_gradient_of_deployed_hard_reward": False}
    progress(f"seed={seed} {mode} adaptation complete; choices={np.bincount([h['action'] for h in history], minlength=4).tolist()}")
    return model, optimizer, result
