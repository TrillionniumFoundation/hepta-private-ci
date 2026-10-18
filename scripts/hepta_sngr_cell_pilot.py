#!/usr/bin/env python3
"""Opt-in, CPU-only *actual neural* shared-stem / Cell-head / NDU graph pilot.

A SMALL randomly initialized and trainable Transformer encoder is shared across
three typed heads: posterior, continuation utility, and conditional Z. All labels
are from a synthetic sequential-evidence simulator with a known Bayes oracle.
Neither a pretrained Laya checkpoint, real Hepta production decision, learned
continuous-time FBSDE, nor a live external task is used. PyTorch is optional.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from functools import lru_cache
import json
import hashlib
import math
import random
import time
from typing import NamedTuple

MAX_PROBES = 5
MAX_GRAPH_CALLS = 63
SENSOR_BOUNDS = (0.6, 0.85)
COST_BOUNDS = (0.02, 0.14)


class PilotError(ValueError):
    """Fail-closed input, numerical or resource error."""


def check_context(reliability: float, cost: float, observations: tuple[int, ...]) -> None:
    if (
        not isinstance(observations, tuple)
        or type(reliability) is bool
        or type(cost) is bool
        or not isinstance(reliability, (int, float))
        or not math.isfinite(reliability)
        or not SENSOR_BOUNDS[0] <= reliability <= SENSOR_BOUNDS[1]
        or not isinstance(cost, (int, float))
        or not math.isfinite(cost)
        or not COST_BOUNDS[0] <= cost <= COST_BOUNDS[1]
        or len(observations) > MAX_PROBES
        or any(type(x) is not int or x not in (-1, 1) for x in observations)
    ):
        raise PilotError("unsupported scope/reliability/cost/observation")


def exact_posterior(reliability: float, observations: tuple[int, ...]) -> float:
    """Analytic teacher; never supplied as an inference input."""
    odds = math.log(reliability / (1.0 - reliability)) * sum(observations)
    return 1.0 / (1.0 + math.exp(-odds))


def probability_of_positive(posterior: float, reliability: float) -> float:
    return reliability * posterior + (1.0 - reliability) * (1.0 - posterior)


def martingale_z(successor_plus: float, successor_minus: float, probability_plus: float) -> tuple[float, float, float]:
    """Centered Z Sigma=B for increment m in {-1,+1}.

    This is a discrete-time two-state martingale regression, NOT Brownian FBSDE.
    Utility at the child must be fixed before computing the regression.
    """
    if not all(math.isfinite(v) for v in (successor_plus, successor_minus, probability_plus)) or not 0 < probability_plus < 1:
        raise PilotError("invalid conditional martingale support")
    variance = 4 * probability_plus * (1 - probability_plus)
    cross = 2 * probability_plus * (1 - probability_plus) * (successor_plus - successor_minus)
    z = cross / variance
    if not all(math.isfinite(v) for v in (z, variance, cross)):
        raise PilotError("nonfinite covariance regression")
    return z, variance, cross


@lru_cache(maxsize=131_072)
def oracle_value(reliability: float, cost: float, count: int, signs_sum: int) -> float:
    """Finite-horizon Bayes-optimal value for a *declared* synthetic task."""
    if not 0 <= count <= MAX_PROBES or abs(signs_sum) > count or (count - signs_sum) % 2:
        raise PilotError("invalid count/sufficient statistic")
    p = 1.0 / (1 + math.exp(-math.log(reliability / (1 - reliability)) * signs_sum))
    stop = max(p, 1 - p)
    if count == MAX_PROBES:
        return stop
    q = probability_of_positive(p, reliability)
    continuation = -cost + q * oracle_value(reliability, cost, count + 1, signs_sum + 1) + (
        1 - q
    ) * oracle_value(reliability, cost, count + 1, signs_sum - 1)
    return max(stop, continuation)


def oracle_targets(reliability: float, cost: float, observations: tuple[int, ...]) -> tuple[float, float, float]:
    check_context(reliability, cost, observations)
    count, total = len(observations), sum(observations)
    p = exact_posterior(reliability, observations)
    value = oracle_value(reliability, cost, count, total)
    if count == MAX_PROBES:
        return p, value, 0.0
    pplus = oracle_value(reliability, cost, count + 1, total + 1)
    pminus = oracle_value(reliability, cost, count + 1, total - 1)
    q = probability_of_positive(p, reliability)
    continuation = -cost + q * pplus + (1 - q) * pminus
    # A stopped policy has no subsequent martingale increment.
    z = martingale_z(pplus, pminus, q)[0] if continuation > max(p, 1 - p) + 1e-12 else 0.0
    return p, value, z


def sample_episode(rng: random.Random, reliability: float) -> tuple[int, tuple[int, ...]]:
    hidden = rng.choice((-1, 1))
    observations = tuple(
        hidden if rng.random() < reliability else -hidden
        for _ in range(MAX_PROBES)
    )
    return hidden, observations


def generate_training_rows(count: int, seed: int) -> tuple[list[tuple[tuple[int, ...], float, float]], list[tuple[float, float, float]]]:
    rng = random.Random(seed)
    states, targets = [], []
    for _ in range(count):
        reliability = rng.uniform(*SENSOR_BOUNDS)
        cost = rng.uniform(*COST_BOUNDS)
        _, all_observations = sample_episode(rng, reliability)
        step = rng.randint(0, MAX_PROBES)
        observations = all_observations[:step]
        states.append((observations, reliability, cost))
        targets.append(oracle_targets(reliability, cost, observations))
    return states, targets


def require_torch():
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("opt-in PyTorch is not available; no neural training occurred") from exc
    return torch


def build_network(torch):
    nn = torch.nn

    class SharedStemCellNetwork(nn.Module):
        """One physical stem, independently addressable light typed heads."""

        def __init__(self):
            super().__init__()
            width = 24
            self.token_embedding = nn.Embedding(4, width)
            self.position_embedding = nn.Embedding(MAX_PROBES + 1, width)
            layer = nn.TransformerEncoderLayer(
                d_model=width, nhead=4, dim_feedforward=48,
                batch_first=True, dropout=0.0, activation="gelu", norm_first=False,
            )
            self.shared_encoder = nn.TransformerEncoder(layer, num_layers=1, enable_nested_tensor=False)
            self.posterior_head = nn.Sequential(nn.Linear(width + 3, 16), nn.Tanh(), nn.Linear(16, 1))
            self.utility_head = nn.Sequential(nn.Linear(width + 3, 16), nn.Tanh(), nn.Linear(16, 1))
            self.z_head = nn.Sequential(nn.Linear(width + 3, 16), nn.Tanh(), nn.Linear(16, 1))

        def forward(self, ids, features, padding_mask):
            positions = torch.arange(ids.shape[1], device=ids.device).unsqueeze(0)
            sequence = self.token_embedding(ids) + self.position_embedding(positions)
            encoded = self.shared_encoder(sequence, src_key_padding_mask=padding_mask)
            hidden = encoded[:, 0, :]
            combined = torch.cat((hidden, features), dim=-1)
            return torch.cat((self.posterior_head(combined), self.utility_head(combined), self.z_head(combined)), dim=-1)

    return SharedStemCellNetwork()


def tensorize(torch, states):
    ids = torch.zeros((len(states), MAX_PROBES + 1), dtype=torch.long)
    ids[:, 0] = 1
    features = torch.zeros((len(states), 3), dtype=torch.float32)
    for row, (observations, reliability, cost) in enumerate(states):
        check_context(reliability, cost, observations)
        for col, signal in enumerate(observations, 1):
            ids[row, col] = 2 if signal == 1 else 3
        features[row] = torch.tensor((reliability, cost, len(observations) / MAX_PROBES))
    return ids, features, ids == 0


def train_network(seed: int = 17, train_samples: int = 4096, steps: int = 450):
    if type(seed) is not int or not 0 <= seed < 2**32 or not 256 <= train_samples <= 8192 or not 1 <= steps <= 1500:
        raise PilotError("training budget not admitted")
    torch = require_torch()
    torch.set_num_threads(1)
    torch.manual_seed(seed)
    network = build_network(torch)
    network.train()
    states, targets = generate_training_rows(train_samples, seed + 100)
    ids, features, mask = tensorize(torch, states)
    labels = torch.tensor(targets, dtype=torch.float32)
    # Training rows and synthetic oracle targets bind this experiment version;
    # no runtime observation, credential or private payload is included.
    data_digest = hashlib.sha256(
        ("hepta.sngr.synthetic-bayes-dataset.v1\n" +
         "".join(repr((row, label)) + "\n" for row, label in zip(states, targets))).encode("utf-8")
    ).hexdigest()
    optimizer = torch.optim.AdamW(network.parameters(), lr=0.003, weight_decay=1e-4)
    generator = torch.Generator(device="cpu").manual_seed(seed + 101)
    start = time.perf_counter()
    for _ in range(steps):
        batch = torch.randint(train_samples, (128,), generator=generator)
        logits, utility, z = network(ids[batch], features[batch], mask[batch]).unbind(dim=1)
        posterior = labels[batch, 0]
        loss = (
            torch.nn.functional.binary_cross_entropy_with_logits(logits, posterior)
            + 3.0 * torch.nn.functional.mse_loss(utility, labels[batch, 1])
            + 0.6 * torch.nn.functional.mse_loss(z, labels[batch, 2])
        )
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(network.parameters(), 1.0)
        optimizer.step()
    seconds = time.perf_counter() - start
    network.eval()
    for parameter in network.parameters():
        parameter.requires_grad_(False)  # selected inference snapshot is not trainable
    return network, {"train_seconds": seconds, "training_examples": train_samples, "optimizer_steps": steps, "seed": seed, "synthetic_training_dataset_sha256": data_digest}


class Prediction(NamedTuple):
    posterior: float
    utility: float
    z: float


@dataclass
class CallMeter:
    max_calls: int = MAX_GRAPH_CALLS
    physical_encoder_calls: int = 0
    head_evaluations: int = 0
    cache_hits: int = 0
    residuals: list[float] | None = None

    def __post_init__(self):
        if type(self.max_calls) is not int or not 1 <= self.max_calls <= MAX_GRAPH_CALLS:
            raise PilotError("invalid inference budget")
        if self.residuals is None:
            self.residuals = []


class CellServing:
    """Typed, scope-local exact-cache serving; never shares mutable episode state."""

    def __init__(self, model, torch, meter: CallMeter):
        if model.training or any(p.requires_grad for p in model.parameters()):
            raise PilotError("selected inference model must be frozen and in eval mode")
        self.model, self.torch, self.meter = model, torch, meter
        self.cache: dict[tuple[tuple[int, ...], float, float], Prediction] = {}

    def predict(self, observations: tuple[int, ...], reliability: float, cost: float) -> Prediction:
        check_context(reliability, cost, observations)
        key = (observations, reliability, cost)
        if key in self.cache:
            self.meter.cache_hits += 1
            return self.cache[key]
        if self.meter.physical_encoder_calls >= self.meter.max_calls:
            raise PilotError("inference budget exhausted")
        ids, features, mask = tensorize(self.torch, [key])
        with self.torch.inference_mode():
            logits, utility, z = self.model(ids, features, mask)[0].tolist()
        result = Prediction(
            posterior=1 / (1 + math.exp(-logits)),
            utility=max(0.0, min(1.0, utility)),
            z=z,
        )
        if not all(math.isfinite(v) for v in result):
            raise PilotError("non-finite neural inference")
        self.cache[key] = result
        self.meter.physical_encoder_calls += 1
        self.meter.head_evaluations += 3
        return result


def plan_choice(serving: CellServing, observations: tuple[int, ...], reliability: float,
                cost: float, depth: int, leaf_mode: str = "learned") -> tuple[str, float]:
    """Bounded forward branch generation, backward value, conditional Z diagnostic.

    leaf_mode='immediate' is a depth-truncated Bellman comparator. 'learned'
    amortizes deeper horizon via a learned continuation utility. Same physical
    model and actor for both; no global stochastic FBSDE claim.
    """
    if leaf_mode not in ("learned", "immediate") or type(depth) is not int or not 0 <= depth <= 3:
        raise PilotError("invalid search operator")
    if len(observations) == MAX_PROBES:
        return "stop", 0.0

    def evaluate(state: tuple[int, ...], remaining: int) -> tuple[float, str]:
        prediction = serving.predict(state, reliability, cost)
        stop = max(prediction.posterior, 1 - prediction.posterior)
        if len(state) == MAX_PROBES or remaining == 0:
            return (prediction.utility if leaf_mode == "learned" and len(state) < MAX_PROBES else stop), "stop"
        pplus = evaluate(state + (1,), remaining - 1)[0]
        pminus = evaluate(state + (-1,), remaining - 1)[0]
        q = probability_of_positive(prediction.posterior, reliability)
        continue_value = -cost + q * pplus + (1 - q) * pminus
        implied_z, variance, cross = martingale_z(pplus, pminus, q)
        if abs(implied_z * variance - cross) > 1e-10:
            raise PilotError("conditional covariance residual exceeds tolerance")
        if continue_value > stop + 1e-8:
            # Z of the chosen continuation; if stopping, Z is zero.
            serving.meter.residuals.append(abs(prediction.z - implied_z))
            return continue_value, "probe"
        return stop, "stop"

    _, action = evaluate(observations, depth)
    return action, max(serving.meter.residuals or [0.0])


def oracle_action(reliability: float, cost: float, observations: tuple[int, ...]) -> str:
    p = exact_posterior(reliability, observations)
    stop = max(p, 1-p)
    if len(observations) == MAX_PROBES:
        return "stop"
    q = probability_of_positive(p, reliability)
    plus = oracle_value(reliability, cost, len(observations) + 1, sum(observations) + 1)
    minus = oracle_value(reliability, cost, len(observations) + 1, sum(observations) - 1)
    return "probe" if -cost + q * plus + (1-q) * minus > stop + 1e-8 else "stop"


def run_episode(model, torch, hidden: int, full_observations: tuple[int, ...],
                reliability: float, cost: float, policy: str, max_calls: int = MAX_GRAPH_CALLS):
    check_context(reliability, cost, ())
    if len(full_observations) != MAX_PROBES or any(type(x) is not int or x not in (-1, 1) for x in full_observations):
        raise PilotError("world evidence stream outside scope")
    if hidden not in (-1, 1) or type(hidden) is not int:
        raise PilotError("invalid synthetic observer target")
    if policy not in ("oracle_policy_neural_answer", "oracle_full", "stop_now", "fixed_3", "bellman_h2", "ndu_h2", "value_bellman_h2", "ndu_adaptive_h2", "value_bellman_adaptive_h2"):
        raise PilotError("unknown policy")
    meter = CallMeter(max_calls=max_calls)
    serving = CellServing(model, torch, meter)
    evidence: tuple[int, ...] = ()
    while len(evidence) < MAX_PROBES:
        if policy in ("oracle_policy_neural_answer", "oracle_full"):
            action = oracle_action(reliability, cost, evidence)
        elif policy == "stop_now":
            action = "stop"
        elif policy == "fixed_3":
            action = "probe" if len(evidence) < 3 else "stop"
        else:
            mode = "learned" if policy in ("ndu_h2", "value_bellman_h2", "ndu_adaptive_h2", "value_bellman_adaptive_h2") else "immediate"
            try:
                if policy in ("ndu_adaptive_h2", "value_bellman_adaptive_h2"):
                    # Spend deeper search only when estimated value of *future
                    # evidence* exceeds stopping by a minimum compute threshold.
                    initial = serving.predict(evidence, reliability, cost)
                    advantage = initial.utility - max(initial.posterior, 1-initial.posterior)
                    if advantage <= 0.009:
                        action = "stop"
                    else:
                        action, _ = plan_choice(serving, evidence, reliability, cost, 2, mode)
                else:
                    action, _ = plan_choice(serving, evidence, reliability, cost, 2, mode)
            except PilotError as exc:
                if str(exc) != "inference budget exhausted":
                    raise
                action = "stop"
        if action == "stop":
            break
        evidence += (full_observations[len(evidence)],)
    if policy == "oracle_full":
        # Strong analytical upper-reference: knows the data-generating law,
        # but NOT the held-out hidden bit. No neural inference is counted.
        prediction = exact_posterior(reliability, evidence)
    else:
        try:
            prediction = serving.predict(evidence, reliability, cost).posterior
        except PilotError as exc:
            if str(exc) != "inference budget exhausted":
                raise
            prediction = 0.5  # explicit budget-fallback guess, not an abstention success
    guess = 1 if prediction >= 0.5 else -1
    correct = int(guess == hidden)
    return {
        "correct": correct,
        "net_reward": correct - cost * len(evidence),
        "net_reward_with_inference_charge": correct - cost * len(evidence) - 0.001 * meter.physical_encoder_calls,
        "probes": len(evidence),
        "encoder_calls": meter.physical_encoder_calls,
        "head_evaluations": meter.head_evaluations,
        "cache_hits": meter.cache_hits,
        "max_z_difference": max(meter.residuals or [0.0]),
    }


def run_pilot(seed: int = 17, train_samples: int = 4096, steps: int = 450,
              heldout_examples: int = 512, episodes: int = 128,
              max_calls: int = MAX_GRAPH_CALLS):
    if type(heldout_examples) is not int or not 128 <= heldout_examples <= 2048 or type(episodes) is not int or not 16 <= episodes <= 1024:
        raise PilotError("evaluation budget exceeded")
    meter = CallMeter(max_calls=max_calls)
    model, training = train_network(seed, train_samples, steps)
    torch = require_torch()
    heldout_states, heldout_targets = generate_training_rows(heldout_examples, seed + 70_001)
    inputs = tensorize(torch, heldout_states)
    with torch.inference_mode():
        predicted = model(*inputs)
        posterior = torch.sigmoid(predicted[:, 0])
        utility = predicted[:, 1].clamp(0, 1)
        z = predicted[:, 2]
        true_labels = torch.tensor(heldout_targets)
        pmae = (posterior - true_labels[:, 0]).abs().mean().item()
        umae = (utility - true_labels[:, 1]).abs().mean().item()
        zmae = (z - true_labels[:, 2]).abs().mean().item()
    policies = ("oracle_full", "oracle_policy_neural_answer", "stop_now", "fixed_3", "bellman_h2", "ndu_h2", "value_bellman_h2", "ndu_adaptive_h2", "value_bellman_adaptive_h2")
    by_policy = {p: [] for p in policies}
    rng = random.Random(seed + 200_001)
    t0 = time.perf_counter()
    wall_by_policy = {p: [] for p in policies}
    for _ in range(episodes):
        reliability, cost = rng.uniform(*SENSOR_BOUNDS), rng.uniform(*COST_BOUNDS)
        hidden, full_obs = sample_episode(rng, reliability)
        for policy in policies:
            start_policy = time.perf_counter()
            result = run_episode(model, torch, hidden, full_obs, reliability, cost, policy, meter.max_calls)
            wall_by_policy[policy].append(time.perf_counter() - start_policy)
            by_policy[policy].append(result)
    eval_wall = time.perf_counter() - t0
    summaries = {}
    for policy, items in by_policy.items():
        samples_sorted = sorted(wall_by_policy[policy])
        summaries[policy] = {
            "p50_episode_wall_ms": 1000 * samples_sorted[episodes // 2],
            "p95_episode_wall_ms": 1000 * samples_sorted[min(episodes - 1, math.ceil(0.95 * episodes) - 1)],
            "accuracy": sum(r["correct"] for r in items) / episodes,
            "mean_net_reward": sum(r["net_reward"] for r in items) / episodes,
            "mean_net_reward_with_inference_charge": sum(r["net_reward_with_inference_charge"] for r in items) / episodes,
            "mean_probes": sum(r["probes"] for r in items) / episodes,
            "mean_encoder_calls": sum(r["encoder_calls"] for r in items) / episodes,
            "max_encoder_calls": max(r["encoder_calls"] for r in items),
            "mean_head_evaluations": sum(r["head_evaluations"] for r in items) / episodes,
            "max_z_difference": max(r["max_z_difference"] for r in items),
        }
    if by_policy["ndu_h2"] != by_policy["value_bellman_h2"] or by_policy["ndu_adaptive_h2"] != by_policy["value_bellman_adaptive_h2"]:
        raise PilotError("additive Bellman/NDU parity failed")
    unique_trainable = sum(p.numel() for p in model.parameters())
    stem_count = sum(p.numel() for name, p in model.named_parameters() if name.startswith(("token_embedding", "position_embedding", "shared_encoder")))
    artifact_bytes = b"hepta.sngr.shared-stem-cell-snapshot.synthetic.v1"
    for name, tensor in sorted(model.state_dict().items()):
        artifact_bytes += len(name).to_bytes(4, "big") + name.encode() + tensor.detach().cpu().contiguous().numpy().tobytes()
    artifact_sha = hashlib.sha256(artifact_bytes).hexdigest()
    def paired_bootstrap(policy_a: str, policy_b: str) -> list[float]:
        """Fixed-seed paired percentile CI, not an independent causal claim."""
        diffs = [a["net_reward_with_inference_charge"] - b["net_reward_with_inference_charge"]
                 for a, b in zip(by_policy[policy_a], by_policy[policy_b])]
        rng_bootstrap = random.Random(seed + 500_001)
        means = sorted(sum(diffs[rng_bootstrap.randrange(episodes)] for _ in range(episodes)) / episodes
                       for _ in range(1000))
        return [means[25], means[974]]
    return {
        "evidence_class": "real_cpu_torch_forward_synthetic_bayes_task",
        "backend": "randomly_initialized_and_supervised_tiny_transformer_not_laya",
        "training": training,
        "heldout_examples": heldout_examples,
        "episodes": episodes,
        "heldout_posterior_mae": pmae,
        "heldout_utility_mae": umae,
        "heldout_z_mae": zmae,
        "model_total_parameters": unique_trainable,
        "model_snapshot_sha256": artifact_sha,
        "paired_reward_delta_bootstrap_ci_95pct": {
            "ndu_minus_fixed3": paired_bootstrap("ndu_h2", "fixed_3"),
            "ndu_minus_bellman_depth2": paired_bootstrap("ndu_h2", "bellman_h2"),
            "ndu_minus_identical_value_bellman": paired_bootstrap("ndu_h2", "value_bellman_h2"),
            "ndu_adaptive_minus_full_think": paired_bootstrap("ndu_adaptive_h2", "ndu_h2"),
        },
        "charge_units_per_encoder_call": 0.001,
        "shared_stem_parameters": stem_count,
        "stem_weights_referenced_once": True,
        "hypothetical_1000_cell_fp32_weights_bytes": {
            "copied_stem_plus_one_head_each": 4 * 1000 * (stem_count + ((unique_trainable - stem_count) // 3)),
            "one_shared_stem_plus_one_head_each": 4 * (stem_count + 1000 * ((unique_trainable - stem_count) // 3)),
            "memory_claim": "weights_only_projection_not_measured_GPU_residency",
        },
        "exclusive_heads_parameters": unique_trainable - stem_count,
        "evaluation_wall_seconds": eval_wall,
        "max_allowed_encoder_calls_per_episode": meter.max_calls,
        "protocol": "typed_observations_scoped_cache_deny_external_effects",
        "results": summaries,
        "real_laya_execution": False,
        "real_world_task_result": None,
        "continuous_time_fbsde_convergence": None,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--steps", type=int, default=450)
    parser.add_argument("--episodes", type=int, default=128)
    parser.add_argument("--max-calls", type=int, default=MAX_GRAPH_CALLS)
    args = parser.parse_args()
    if not args.demo:
        parser.error("opt-in only: supply --demo")
    print(json.dumps(run_pilot(seed=args.seed, steps=args.steps, episodes=args.episodes, max_calls=args.max_calls), indent=2, sort_keys=True, allow_nan=False))
