"""Reference-free generation, budget accounting, and rendered output artifacts."""

import hashlib
import io
import os
from pathlib import Path
import tempfile
import time

import numpy as np
from PIL import Image, ImageDraw
import torch

from backend import MODEL_REVISION, explanation
from cells import apply_constraints, state_features


PORTFOLIOS = [[0.0] * 4, [0.25] * 4, [1., 0., 0., 0.],
              [0., 1., 0., 0.], [0., 0., 1., 0.], [0., 0., 0., 1.]]
COMPONENTS = ("encoder", "backbone", "cell", "controller", "critic", "verifier", "render", "communication")


class Controller:
    def __init__(self, backend, cells, policies, method, seed, risk_weight=0.5):
        self.backend, self.cells, self.policies = backend, cells, policies
        self.method, self.seed, self.risk_weight = method, seed, risk_weight
        self.action, self.weights = 1, PORTFOLIOS[1]
        self.states, self.actions, self.probabilities = [], [], []
        self.cell_seconds = self.critic_seconds = 0.0
        self.rng = np.random.default_rng(seed)

    def __call__(self, state):
        started = time.perf_counter()
        corrections = self.cells.corrections(state["hidden"])
        cell_seconds = time.perf_counter() - started
        self.cell_seconds += cell_seconds
        features, covariance = state_features(state, corrections, self.cells.vocabulary,
                                               self.backend.location_token_ids, self.backend.eos_token_id)
        metadata, critic_seconds = {}, 0.0
        if state["checkpoint_changed"]:
            if self.method == "explore":
                self.action = int(self.rng.integers(len(PORTFOLIOS)))
                self.weights, probabilities = PORTFOLIOS[self.action], [1 / 6] * 6
            elif self.method in ("static_cells", "ablate_fixed_weights"):
                self.action, self.weights, probabilities = 1, PORTFOLIOS[1], [0., 1., 0., 0., 0., 0.]
            else:
                policy_method = "ndu" if self.method.startswith("ablate_") else self.method
                before_policy = time.perf_counter()
                decision = self.policies.action(
                    features, policy_method, risk_weight=self.risk_weight,
                    covariance=None if self.method == "ablate_covariance" else covariance.numpy(),
                    seed=self.seed * 31 + state["checkpoint"],
                )
                critic_seconds = time.perf_counter() - before_policy
                self.critic_seconds += critic_seconds
                self.action, self.weights = decision["action"], decision["weights"]
                metadata = decision["metadata"]
                probabilities = metadata.get("action_probs", [float(i == self.action) for i in range(6)])
            self.states.append(features.tolist())
            self.actions.append(self.action)
            self.probabilities.append(probabilities)
        delta = state["hidden"].new_zeros(len(state["logits"]))
        delta[self.cells.vocabulary] = torch.tensor(self.weights) @ corrections
        logits = state["logits"] + delta
        if self.method != "ablate_crossmodal":
            logits = apply_constraints(logits, state["token_ids"], self.backend.location_token_ids,
                                       self.backend.eos_token_id)
        elapsed = time.perf_counter() - started
        extra = {"cell_seconds": cell_seconds, "critic_seconds": critic_seconds,
                 "controller_seconds": max(0.0, elapsed - cell_seconds - critic_seconds),
                 "constraint_scope": "prefix_geometry_only", "policy": metadata}
        if state["checkpoint_changed"]:
            extra["observed_features"] = features.tolist()
        return {"logits": logits, "weights": self.weights, "action": self.action, "extra": extra}


def render(observation, boxes, artifact_root):
    """Render predictions on the source image, retaining original dimensions."""
    started = time.perf_counter()
    with Image.open(observation["image_path"]) as source:
        image = source.convert("RGB")
    draw = ImageDraw.Draw(image)
    width, height = image.size
    for index, box in enumerate(boxes):
        if len(box) != 4 or not all(np.isfinite(box)) or box[0] >= box[2] or box[1] >= box[3]:
            continue  # The unchanged invalid prediction is rejected by the independent scorer.
        coordinates = (box[0] * width, box[1] * height, box[2] * width, box[3] * height)
        draw.rectangle(coordinates, outline=(255, 30, 30), width=3)
        draw.text((coordinates[0] + 3, coordinates[1] + 3),
                  f"{index + 1}: {observation['target_category']}", fill=(255, 255, 0), stroke_width=1, stroke_fill=(0, 0, 0))
    # Palette PNG bounds storage; quantization affects display pixels, never input or boxes.
    image = image.quantize(colors=256, method=Image.Quantize.FASTOCTREE)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    payload = buffer.getvalue()
    digest = hashlib.sha256(payload).hexdigest()
    path = Path(artifact_root) / (digest + ".png")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".png.tmp", delete=False) as temporary:
            temporary.write(payload)
            temporary_path = temporary.name
        os.replace(temporary_path, path)
    return str(path.resolve()), digest, time.perf_counter() - started


def altered_observation(observation, method, artifact_root, partner=None):
    observed = dict(observation)
    if method == "ablate_shuffled_pair":
        if partner is None or partner["task_id"] == observation["task_id"]:
            raise ValueError("a different same-split image is required for shuffled-pair ablation")
        observed.update(image_path=partner["image_path"], image_sha256=partner["image_sha256"])
    elif method == "ablate_missing_modality":
        with Image.open(observation["image_path"]) as source:
            size = source.size
        black = Path(artifact_root) / f"missing-vision-{size[0]}x{size[1]}.png"
        black.parent.mkdir(parents=True, exist_ok=True)
        if not black.exists():
            with tempfile.NamedTemporaryFile(dir=black.parent, suffix=".png.tmp", delete=False) as temporary:
                Image.new("RGB", size, (0, 0, 0)).save(temporary, format="PNG")
                temporary_path = temporary.name
            os.replace(temporary_path, black)
        observed.update(image_path=str(black.resolve()), image_sha256=hashlib.sha256(black.read_bytes()).hexdigest())
    return observed


def run_episode(backend, cells, policies, verifier, observation, method, artifact_root,
                seed=23, budget_cap=10.0, risk_weight=0.5, partner=None):
    """No reference argument exists: all terminal scoring belongs to the caller."""
    started = time.perf_counter()
    cpu_started = time.process_time()
    execution_seed = (seed + int(hashlib.sha256(observation["task_id"].encode()).hexdigest()[:8], 16)) % (2**31 - 1)
    observed = altered_observation(observation, method, artifact_root, partner)
    costs = {name: {"component": name, "calls": 0, "wall_seconds": 0.0} for name in COMPONENTS}
    overhead = time.perf_counter() - started
    costs["controller"]["wall_seconds"] += overhead
    candidates, controllers, failures, encoded_cache = [], [], [], None
    for candidate_index in range(2 if method == "best_of_n" else 1):
        if budget_cap - (time.perf_counter() - started) < 0.25:
            break
        encoded, controller, result = None, None, None
        attempt_started = time.perf_counter()
        recorded_before = sum(row["wall_seconds"] for row in costs.values())
        try:
            encoder_reused = encoded_cache is not None
            if encoded_cache is None:
                encoded_cache = backend.encode(observed)
                costs["encoder"]["calls"] += 1
                costs["encoder"]["wall_seconds"] += encoded_cache.costs["encoder_seconds"]
            encoded = encoded_cache
            if method not in ("base", "best_of_n"):
                controller = Controller(backend, cells, policies, method, execution_seed, risk_weight)
                controllers.append(controller)
            remaining = budget_cap - (time.perf_counter() - started) + encoded.costs["encoder_seconds"] - 0.15
            result = backend.generate(encoded, modifier=controller, max_wall_seconds=max(0.001, remaining),
                                      do_sample=method == "best_of_n" and candidate_index > 0,
                                      temperature=0.7, seed=execution_seed + candidate_index)
            raw = result["costs"]
            result["encoder_reused"] = encoder_reused
            cell = controller.cell_seconds if controller else 0.0
            critic = controller.critic_seconds if controller else 0.0
            amounts = {"backbone": raw["decoder_seconds"] + raw["parsing_seconds"] + raw["loop_overhead_seconds"],
                       "cell": cell, "critic": critic,
                       "controller": max(0.0, raw["modifier_seconds"] - cell - critic)}
            for name, seconds in amounts.items():
                costs[name]["wall_seconds"] += seconds
                costs[name]["calls"] += (1 if name == "backbone" else int(seconds > 0))
            if verifier is not None:
                prediction = verifier.predict(result)
                costs["verifier"]["calls"] += 1
                costs["verifier"]["wall_seconds"] += prediction["wall_seconds"]
            else:
                prediction = {"quality": 0.0, "severe_probability": None, "wall_seconds": 0.0}
            result["verification"] = prediction
            candidates.append(result)
        except Exception as exc:
            # Preserve the failed attempt and its measured elapsed work, including partial decoding.
            measured = time.perf_counter() - attempt_started
            recorded = sum(row["wall_seconds"] for row in costs.values()) - recorded_before
            unallocated = costs.setdefault("unallocated_failure", {"component": "unallocated_failure", "calls": 0, "wall_seconds": 0.0})
            unallocated["calls"] += 1
            unallocated["wall_seconds"] += max(0.0, measured - recorded)
            failures.append(f"candidate {candidate_index}: {type(exc).__name__}: {str(exc)[:300]}")
            if result is not None:
                result["verification"] = {"quality": 0.0, "severe_probability": None, "verification_failed": True}
                candidates.append(result)
            break
    completed = [candidate for candidate in candidates if candidate["termination"] == "eos"]
    eligible = completed or candidates
    chosen = max(eligible, key=lambda row: row["verification"]["quality"]) if eligible else {
        "boxes": [], "controls": [], "tokens": [], "raw_text": "", "termination": "error",
        "verification": {"quality": 0.0, "severe_probability": None},
    }
    path, digest, seconds = render(observation, chosen["boxes"], artifact_root)
    costs["render"].update(calls=1, wall_seconds=seconds)
    accounted = sum(row["wall_seconds"] for row in costs.values())
    elapsed = time.perf_counter() - started
    costs["controller"]["wall_seconds"] += max(0.0, elapsed - accounted)
    termination = "completed" if chosen["termination"] == "eos" else "incomplete"
    if failures and not candidates:
        termination = "error"
    return {"task_id": observation["task_id"], "method": method, "seed": seed,
            "budget_cap": budget_cap, "budget_unit": "wall_seconds", "termination": termination,
            "text": explanation(observation["target_category"], chosen["boxes"]),
            "boxes": chosen["boxes"], "label": observation["target_category"],
            "artifact_path": path, "artifact_sha256": digest, "controls": chosen["controls"],
            "costs": list(costs.values()), "model_revision": MODEL_REVISION,
            "policy_version": f"hepta-grounded-v1/{method}", "risk_weight": risk_weight,
            "actual_input_image_sha256": observed["image_sha256"], "source_image_sha256": observation["image_sha256"],
            "failures": failures, "verification": chosen["verification"], "raw_text": chosen["raw_text"],
            "actual_wall_seconds": elapsed, "execution_seed": execution_seed,
            "actual_cpu_seconds": time.process_time() - cpu_started,
            "ledger_minus_wall_seconds": sum(row["wall_seconds"] for row in costs.values()) - elapsed,
            "generated_tokens": sum(len(c["tokens"]) - 1 for c in candidates),
            "token_measurement_complete": not failures,
            "failed_work_detail": "failed attempt time retained; token/internal-call counts may be unavailable" if failures else None,
            "candidates": [{"raw_text": c["raw_text"], "boxes": c["boxes"], "verification": c["verification"],
                            "termination": c["termination"], "encoder_reused": c.get("encoder_reused", False),
                            "costs": c["costs"]} for c in candidates],
            "trajectory": {"states": controllers[0].states, "actions": controllers[0].actions,
                           "behavior_probs": controllers[0].probabilities} if controllers else None,
            "generated_for_verifier": {k: chosen.get(k) for k in ("boxes", "tokens", "controls", "termination")},
            "accounting": "exclusive measured worker wall time; one real encoder per episode, reused within best-of-two; resident initialization separate"}
