"""Real trained four-head, two-by-two NDU training x inference *synthetic* pilot.

Never a foundation model or trusted outcome observer. All four raw toy modalities
are generated before an independent, truth-bearing terminal score is computed.
Training methods use identical model/initialization, batches and update counts.
The test target is never passed to inference or controller fitting.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import random
import time

MODES = ("easy", "hard")
TRAININGS = ("supervised", "ndu_risk")
CONTROLS = ("static", "ndu_contextual")
ACTIONS = ("EMIT", "REFINE_TEXT", "REFINE_AUDIO", "REFINE_IMAGE", "REFINE_VIDEO", "QUERY")
ENCODER_WIDTH = 4
EMISSION_COST = 4
COSTS = {a: EMISSION_COST + (3 if a == "QUERY" else 1 if a.startswith("REFINE_") else 0) for a in ACTIONS}

@dataclass(frozen=True)
class World:
    source_id: str
    mode: str
    signals: tuple[int, int, int, int]
    witness: int
    # External observer only. Do not pass to predictor or policy.
    truth: int
    common_flip: bool

    @property
    def public(self) -> PublicObservation:
        # Construct a separate type: the model/policy cannot inspect truth,
        # future witness samples or latent common-cause annotations.
        return PublicObservation(self.source_id, self.mode, self.signals)


@dataclass(frozen=True)
class PublicObservation:
    source_id: str
    mode: str
    signals: tuple[int, int, int, int]


def make_worlds(seed: int, split: str, n: int, common_error: float = .12,
                witness_accuracy: float = .97) -> tuple[World, ...]:
    if (split not in ("train", "dev", "test", "shift") or n < 1
        or type(seed) is not int or not 0 <= common_error <= 1
        or not 0 <= witness_accuracy <= 1):
        raise ValueError("invalid frozen source cohort")
    # Source namespace and streams are disjoint by full (seed, split) pair.
    rng = random.Random(int(hashlib.sha256(
        f"hepta-v5-sources|{seed}|{split}".encode()).hexdigest()[:16], 16))
    rows = []
    for i in range(n):
        mode = MODES[i % 2]
        truth = rng.randrange(2)
        common = rng.random() < common_error
        shared = truth ^ int(common)
        errors = (.02, .08, .16, .22) if mode == "easy" else (.12, .22, .30, .36)
        signals = tuple(shared ^ int(rng.random() < prob) for prob in errors)
        witness = truth ^ int(rng.random() >= witness_accuracy)
        rows.append(World(f"{seed}/{split}/{i:06d}", mode, signals,
                          witness, truth, common))
    return tuple(rows)


def features(world: PublicObservation, channel: int) -> tuple[float, ...]:
    if not 0 <= channel < 4:
        raise ValueError("invalid modality")
    # Frozen shared source features; no truth, witness or common_flip.
    own = 2 * world.signals[channel] - 1
    peers = sum(2 * s - 1 for j, s in enumerate(world.signals) if j != channel) / 3
    return (1.0, float(own), float(peers), float(world.mode == "hard"))


def sigmoid(z: float) -> float:
    if z >= 0:
        return 1 / (1 + math.exp(-z))
    e = math.exp(z)
    return e / (1 + e)


def init_weights(seed: int) -> list[list[float]]:
    rng = random.Random(seed * 1009 + 173)
    return [[rng.uniform(-.08, .08) for _ in range(4)] for _ in range(4)]


def predict(world: PublicObservation, weights: list[list[float]]) -> tuple[float, ...]:
    return tuple(sigmoid(sum(w * f for w, f in zip(weights[k], features(world, k))))
                 for k in range(4))


def train(worlds: tuple[World, ...], seed: int, mode: str,
          *, steps: int = 80, batch_size: int = 64,
          risk_gamma: float = 2.0, learning_rate: float = .18) -> tuple[list[list[float]], dict]:
    if mode not in TRAININGS or steps < 1 or batch_size < 1:
        raise ValueError("invalid training method")
    weights = init_weights(seed)
    rng = random.Random(seed * 101 + 71)
    nonzero_risk_steps = 0
    nonzero_grad_steps = [0] * 4
    initial = tuple(tuple(x) for x in weights)
    train_start = time.perf_counter()
    for _ in range(steps):
        batch = tuple(worlds[rng.randrange(len(worlds))] for _ in range(batch_size))
        grads = []
        losses = []
        for world in batch:
            outs = predict(world.public, weights)
            per_head = []
            gradient = []
            for k, p in enumerate(outs):
                y = world.truth
                safe = max(1e-12, min(1 - 1e-12, p))
                per_head.append(-y * math.log(safe) - (1-y) * math.log(1-safe))
                gradient.append(tuple((p-y) * f / 4 for f in features(world.public, k)))
            losses.append(sum(per_head) / 4)
            grads.append(tuple(gradient))
        if mode == "ndu_risk":
            top = max(losses)
            scaled = [math.exp(risk_gamma * (loss - top)) for loss in losses]
            total = sum(scaled)
            # 70% entropic NDU gradient, 30% same supervised anchor.
            coefficients = [0.7 * x / total + 0.3 / batch_size for x in scaled]
            if max(coefficients) - min(coefficients) > 1e-9:
                nonzero_risk_steps += 1
        else:
            coefficients = [1 / batch_size] * batch_size
        for k in range(4):
            risk_credit = 0.0
            for j in range(4):
                grad = sum(coefficients[b] * grads[b][k][j] for b in range(batch_size))
                if mode == "ndu_risk":
                    ordinary = sum(grads[b][k][j] for b in range(batch_size)) / batch_size
                    risk_credit += (grad - ordinary) ** 2
                weights[k][j] -= learning_rate * (grad + .001 * weights[k][j])
            if risk_credit > 1e-16:
                nonzero_grad_steps[k] += 1
    return weights, {
        "mode": mode, "updates": steps, "examples_per_update": batch_size,
        "initial_weight_digest": _digest(initial),
        "final_weight_digest": _digest(weights),
        "nonzero_utility_weight_steps": nonzero_risk_steps,
        "nonzero_head_risk_gradient_steps": nonzero_grad_steps,
        "training_wall_seconds_observed": time.perf_counter() - train_start,
        "trainable_parameters": 16,
        "head_forward_calls": steps * batch_size * 4,
    }


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def classify(p: float) -> int:
    return int(p >= .5)


def apply_action(probs: tuple[float, ...], action: str, witness: int) -> tuple[float, ...]:
    if action not in ACTIONS or type(witness) is not int or witness not in (0, 1):
        raise ValueError("invalid action or witness")
    if action == "QUERY":
        return (float(witness),) * 4
    if action == "EMIT":
        return probs
    k = ACTIONS.index(action) - 1
    peers = sum(probs[j] for j in range(4) if j != k) / 3
    updated = list(probs)
    updated[k] = .1 * probs[k] + .9 * peers
    return tuple(updated)


def decode_raw(probs: tuple[float, ...]) -> dict:
    if len(probs) != 4 or any(not math.isfinite(p) or not 0 <= p <= 1 for p in probs):
        raise ValueError("invalid multimodal decoder input")
    t, a, i, v = (classify(p) for p in probs)
    return {"text": f"symbol:{t}", "audio": (a, -a, a, -a),
            "image": ((i, i), (i, i)),
            "video": (((v, v), (v, v)), ((v, v), (v, v)))}


def independent_loss(raw: dict, truth: int) -> tuple[int, int, int]:
    if type(truth) is not int or truth not in (0, 1) or set(raw) != {
            "text", "audio", "image", "video"}:
        raise ValueError("unverifiable terminal outcome")
    t = int(raw["text"][-1])
    a = raw["audio"][0]
    i = raw["image"][0][0]
    v = raw["video"][0][0][0]
    if (raw["text"] != f"symbol:{t}" or raw["audio"] != (a, -a, a, -a)
        or raw["image"] != ((i, i), (i, i))
        or raw["video"] != (((v, v), (v, v)), ((v, v), (v, v)))
        or any(type(x) is not int or x not in (0, 1) for x in (t, a, i, v))):
        raise ValueError("malformed output")
    wrong = sum(x != truth for x in (t, a, i, v))
    inconsistency = int(t != a) + int(i != v)
    return int(wrong + 2 * inconsistency), int(wrong), inconsistency


def context(world: PublicObservation, probs: tuple[float, ...]) -> tuple[str, int]:
    # Only public input + already emitted Head probabilities.
    votes = [classify(p) for p in probs]
    disagreements = min(2, min(sum(votes), 4-sum(votes)))
    return world.mode, disagreements


def risk_measure(losses: list[float], gamma: float) -> float:
    if not losses or gamma < 0 or any(not math.isfinite(x) for x in losses):
        raise ValueError("unsupported utility observation")
    if gamma == 0:
        return sum(losses) / len(losses)
    peak = max(losses)
    return peak + math.log(sum(math.exp(gamma*(x-peak)) for x in losses) / len(losses)) / gamma


def train_policies(dev: tuple[World, ...], weights: list[list[float]],
                   *, gamma: float = .12, cost_price: float = .45,
                   budget: int = 7, min_support: int = 16) -> dict:
    if not dev or gamma < 0 or cost_price < 0 or budget < EMISSION_COST:
        raise ValueError("invalid critic budget")
    loss_by_context = {}
    global_losses = {a: [] for a in ACTIONS if COSTS[a] <= budget}
    for world in dev:
        probs = predict(world.public, weights)
        key = context(world.public, probs)
        bucket = loss_by_context.setdefault(key, {a: [] for a in global_losses})
        for action in global_losses:
            loss, _, _ = independent_loss(decode_raw(apply_action(probs, action, world.witness)), world.truth)
            observation = loss + cost_price * COSTS[action]
            bucket[action].append(observation)
            global_losses[action].append(observation)
    static = min(global_losses, key=lambda a: (risk_measure(global_losses[a], gamma), a))
    lookup = {}
    support = {}
    for key, rows in loss_by_context.items():
        count = len(next(iter(rows.values())))
        support[key] = count
        lookup[key] = (min(rows, key=lambda a: (risk_measure(rows[a], gamma), a))
                       if count >= min_support else static)
    return {"static": static, "context_actions": lookup,
            "context_support": support,
            "trained_on_dev_source_digest": _digest([w.source_id for w in dev]),
            "gamma": gamma, "budget": budget, "cost_price": cost_price}


def choose(world: PublicObservation, probs: tuple[float, ...], critic: dict, mode: str) -> str:
    if mode not in CONTROLS:
        raise ValueError("invalid inference policy")
    if mode == "static":
        return critic["static"]
    return critic["context_actions"].get(context(world, probs), critic["static"])


def cvar90(losses: list[int]) -> float:
    if not losses:
        raise ValueError("empty risk cohort")
    sorted_losses = sorted(losses, reverse=True)
    count = max(1, math.ceil(len(losses) / 10))
    # Exact equal-weight fractional 10% tail, not ceil(n/10) averaging.
    mass = len(losses) / 10
    whole = int(mass)
    rest = mass - whole
    return (sum(sorted_losses[:whole]) + rest * sorted_losses[whole]) / mass


def evaluate(test: tuple[World, ...], weights: list[list[float]],
             critic: dict, control: str) -> tuple[dict, list[dict]]:
    start = time.perf_counter()
    rows = []
    for world in test:
        probs = predict(world.public, weights)
        action = choose(world.public, probs, critic, control)
        if action not in ACTIONS or COSTS[action] > critic["budget"]:
            raise AssertionError("inadmissible controller action")
        raw = decode_raw(apply_action(probs, action, world.witness))
        loss, wrong, mismatch = independent_loss(raw, world.truth)
        rows.append({"source": world.source_id, "action": action, "loss": loss,
                     "wrong": wrong, "mismatch": mismatch, "cost_units": COSTS[action],
                     "common_flip": world.common_flip})
    losses = [x["loss"] for x in rows]
    return ({"mean_loss": sum(losses)/len(losses),
             "cvar90_loss": cvar90(losses),
             "mean_wrong_modalities": sum(x["wrong"] for x in rows)/len(rows),
             "mean_inconsistency": sum(x["mismatch"] for x in rows)/len(rows),
             "mean_cost_units": sum(x["cost_units"] for x in rows)/len(rows),
             "query_rate": sum(x["action"] == "QUERY" for x in rows)/len(rows),
             "refine_rate": sum(x["action"].startswith("REFINE_") for x in rows)/len(rows),
             "test_wall_seconds_observed": time.perf_counter()-start,
             "test_sources": len(test),
             "head_forward_calls": len(test) * 4,
             "query_executions": sum(x["action"] == "QUERY" for x in rows)}, rows)


def run(seed: int, ntrain: int = 768, ndev: int = 256, ntest: int = 512,
        steps: int = 80) -> dict:
    splits = {label: make_worlds(seed, label, n) for label, n in
              (("train", ntrain), ("dev", ndev), ("test", ntest))}
    ids = [w.source_id for rows in splits.values() for w in rows]
    if len(ids) != len(set(ids)):
        raise AssertionError("source leakage")
    report = {"schema": "hepta.ndu-v5.factorial-development.v1",
              "status": "DEVELOPMENT_ONLY_NO_CONFIRMATORY_CLAIM",
              "seed": seed, "splits": {k: _digest([w.source_id for w in rows])
                                      for k, rows in splits.items()},
              "arms": {}, "training": {}}
    paired = {}
    for method in TRAININGS:
        weights, receipt = train(splits["train"], seed, method, steps=steps)
        report["training"][method] = receipt
        critic = train_policies(splits["dev"], weights)
        for control in CONTROLS:
            key = f"{method}|{control}"
            metrics, rows = evaluate(splits["test"], weights, critic, control)
            report["arms"][key] = {**metrics,
                                   "static_dev_action": critic["static"],
                                   "critic_dev_digest": critic["trained_on_dev_source_digest"]}
            paired[key] = {r["source"]: r["loss"] for r in rows}
    keys = ("supervised|static", "supervised|ndu_contextual",
            "ndu_risk|static", "ndu_risk|ndu_contextual")
    contrasts = {}
    for label, a, b in (("inference_effect_supervised", keys[1], keys[0]),
                        ("training_effect_static", keys[2], keys[0]),
                        ("training_effect_dynamic", keys[3], keys[1]),
                        ("inference_effect_ndu", keys[3], keys[2])):
        contrasts[label] = sum(paired[a][sid] - paired[b][sid]
                               for sid in paired[a]) / len(paired[a])
    contrasts["training_by_inference_interaction"] = (
        contrasts["inference_effect_ndu"] - contrasts["inference_effect_supervised"])
    report["paired_mean_loss_contrasts"] = contrasts
    return report

if __name__ == "__main__":
    print(json.dumps(run(17), indent=2, sort_keys=True))
