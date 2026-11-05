"""Small offline controllers; NDU is a discrete BSDE prototype, not Merton.

The action-only martingale basis and 24 observed features are approximate.
Terminal labels enter fit only. A sampled inference policy satisfies a KL
bound against the pooled training exploration distribution, not a risk bound.
"""

import copy
import hashlib
import math
import numbers
from pathlib import Path
import time

import torch
from torch import nn
from torch.nn import functional as F

METHODS = ("learned_router", "mean_only", "risk_actor_critic", "ndu")
ACTION_WEIGHTS = [[0.0] * 4, [0.25] * 4,
                  [1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0],
                  [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]


class _Network(nn.Module):
    def __init__(self, hidden):
        super().__init__()
        self.trunk = nn.Sequential(nn.Linear(24, hidden), nn.Tanh(), nn.Linear(hidden, hidden), nn.Tanh())
        self.actor = nn.Linear(hidden, 6)
        self.q = nn.Linear(hidden, 6)
        self.loss = nn.Linear(hidden, 6)
        self.tail = nn.Linear(hidden, 6)
        self.exceedance = nn.Linear(hidden, 6)
        self.value = nn.Linear(hidden, 1)
        self.y = nn.Linear(hidden, 2)
        self.z = nn.Linear(hidden, 12)

    def forward(self, state):
        hidden = self.trunk(state)
        return {"actor": self.actor(hidden), "q": self.q(hidden), "loss": self.loss(hidden),
                "tail": self.tail(hidden), "exceedance": self.exceedance(hidden),
                "value": self.value(hidden).squeeze(-1), "y": self.y(hidden),
                "z": self.z(hidden).reshape(-1, 2, 6)}


def _batch(trajectories):
    records = []
    for trajectory in trajectories:
        states, actions, probabilities = (trajectory[k] for k in ("states", "actions", "behavior_probs"))
        if trajectory.get("split", "train") != "train":
            raise ValueError("policy fitting accepts train trajectories only")
        if not 1 <= len(actions) <= 8 or len(states) != len(actions) or len(probabilities) != len(actions):
            raise ValueError("one to eight checkpoints with matched states/actions/probabilities required")
        quality, loss = float(trajectory["terminal_quality"]), float(trajectory["terminal_loss"])
        if not all(math.isfinite(v) and 0 <= v <= 1 for v in (quality, loss)):
            raise ValueError("terminal quality/loss must be finite and in [0,1]")
        for index, (state, action, probability) in enumerate(zip(states, actions, probabilities)):
            if len(state) != 24 or not isinstance(action, numbers.Integral) or not 0 <= action < 6 or len(probability) != 6:
                raise ValueError("24 features and one of six actions required")
            action = int(action)
            state = [float(v) for v in state]
            probability = [float(v) for v in probability]
            if (not all(math.isfinite(v) for v in state + probability)
                    or min(probability) <= 0 or abs(sum(probability) - 1) > 1e-5):
                raise ValueError("finite features and full-support behavior probabilities required")
            done = index == len(actions) - 1
            records.append((state, action, probability, quality, loss, done,
                            states[index + 1] if not done else [0.0] * 24,
                            probabilities[index + 1] if not done else probability, 1 / len(actions)))
    if not records:
        raise ValueError("nonempty train trajectories required")
    columns = list(zip(*records))
    names = ("states", "actions", "behavior", "quality", "loss", "done", "next", "next_behavior", "weight")
    batch = {name: torch.tensor(value, dtype=torch.long if name == "actions" else torch.float32)
             for name, value in zip(names, columns)}
    batch["weight"] /= batch["weight"].sum()
    if bool((torch.bincount(batch["actions"], minlength=6) == 0).any()):
        raise ValueError("every action needs at least one observed training transition")
    return batch


def _kl(probability, prior):
    return (probability * (probability.clamp_min(1e-12).log() - prior.log())).sum(-1)


def _conservative_distribution(logits, prior, bound):
    """Project along the prior-to-proposal mixture until KL <= the bound."""
    proposal = logits.softmax(-1)
    if float(_kl(proposal, prior)) <= bound:
        return proposal
    lower, upper = 0.0, 1.0
    for _ in range(40):
        middle = (lower + upper) / 2
        mixed = prior * (1 - middle) + proposal * middle
        if float(_kl(mixed, prior)) <= bound:
            lower = middle
        else:
            upper = middle
    return prior * (1 - lower) + proposal * lower


class Policies:
    def __init__(self, seed=23, hidden=32, tail_threshold=0.5, kl_bound=0.25,
                 temperature=0.25, covariance_strength=0.05):
        if (not all(math.isfinite(value) for value in (tail_threshold, kl_bound, temperature, covariance_strength))
                or not 0 <= tail_threshold < 1 or kl_bound < 0 or temperature <= 0 or covariance_strength < 0):
            raise ValueError("invalid risk or regularization configuration")
        self.config = dict(seed=seed, hidden=hidden, tail_threshold=tail_threshold, kl_bound=kl_bound,
                           temperature=temperature, covariance_strength=covariance_strength)
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed)
            template = _Network(hidden)
            self.models = nn.ModuleDict({method: copy.deepcopy(template) for method in METHODS})
        self.generator = torch.Generator().manual_seed(seed)
        self.mean, self.scale, self.prior = torch.zeros(24), torch.ones(24), torch.full((6,), 1/6)
        self.training_metadata = None

    def _estimates(self, output, method, behavior):
        if method == "ndu":
            centered = output["z"] - (output["z"] * behavior[:, None, :]).sum(-1, keepdim=True)
            quality = output["y"][:, :1] + centered[:, 0]
            loss = output["y"][:, 1:] + centered[:, 1]
        else:
            quality, loss = output["q"], output["loss"]
        risk = loss.clamp(0, 1) + 0.5 * output["tail"].clamp(0, 1) + 0.25 * output["exceedance"].sigmoid()
        return quality, loss, risk

    def fit(self, trajectories, epochs=100, learning_rate=0.003, risk_weight=0.5):
        """Evaluate behavior trajectories, then make finite offline policy improvements."""
        if epochs < 1 or learning_rate <= 0 or not math.isfinite(risk_weight) or risk_weight < 0:
            raise ValueError("positive training schedule and nonnegative risk weight required")
        trajectories = list(trajectories)
        batch = _batch(trajectories)
        self.mean = batch["states"].mean(0)
        self.scale = batch["states"].std(0, unbiased=False).clamp_min(0.1)
        self.prior = (batch["behavior"] * batch["weight"][:, None]).sum(0)
        states, next_states = ((batch[key] - self.mean) / self.scale for key in ("states", "next"))
        rows, actions, weights = torch.arange(len(states)), batch["actions"], batch["weight"]
        boundary = torch.stack((batch["quality"], batch["loss"]), -1)
        threshold = self.config["tail_threshold"]
        tail = (batch["loss"] - threshold).clamp_min(0) / (1 - threshold)
        exceedance = (batch["loss"] > threshold).float()
        delta_m = F.one_hot(actions, 6).float() - batch["behavior"]
        started, histories, diagnostics = time.perf_counter(), {}, {}
        for method, model in self.models.items():
            optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=0.001)
            history = []
            model.train()
            for _ in range(epochs):
                output = model(states)
                quality_q, loss_q, risk_q = self._estimates(output, method, batch["behavior"])
                if method == "learned_router":
                    loss = (weights * (0.01 + batch["quality"]) *
                            F.cross_entropy(output["actor"], actions, reduction="none")).sum()
                else:
                    following = model(next_states)
                    if method == "ndu":
                        next_y = torch.where(batch["done"][:, None].bool(), boundary, following["y"].detach())
                        residual = next_y - output["y"] - (output["z"] * delta_m[:, None, :]).sum(-1)
                        per_step = residual.square().mean(-1) + 0.25 * (output["y"] - boundary).square().mean(-1)
                        centered_z = output["z"] - (output["z"] * batch["behavior"][:, None, :]).sum(-1, keepdim=True)
                        per_step = per_step + 0.005 * centered_z.square().mean((1, 2))
                    else:
                        next_quality = (following["q"] * batch["next_behavior"]).sum(-1).detach()
                        target = torch.where(batch["done"].bool(), batch["quality"], next_quality)
                        per_step = (quality_q[rows, actions] - target).square()
                        per_step += 0.25 * (quality_q[rows, actions] - batch["quality"]).square()
                        per_step += 0.25 * (output["value"] - batch["quality"]).square()
                        if method == "risk_actor_critic":
                            next_loss = (following["loss"] * batch["next_behavior"]).sum(-1).detach()
                            target_loss = torch.where(batch["done"].bool(), batch["loss"], next_loss)
                            per_step += (loss_q[rows, actions] - target_loss).square()
                            per_step += 0.25 * (loss_q[rows, actions] - batch["loss"]).square()
                    if method != "mean_only":
                        per_step += (output["tail"][rows, actions] - tail).square()
                        per_step += F.binary_cross_entropy_with_logits(output["exceedance"][rows, actions],
                                                                      exceedance, reduction="none")
                    applied_risk = 0.0 if method == "mean_only" else risk_weight
                    scores = quality_q.detach().clamp(0, 1) - applied_risk * risk_q.detach()
                    target_policy = (batch["behavior"].log() + scores / self.config["temperature"]).softmax(-1)
                    actor_ce = -(target_policy * output["actor"].log_softmax(-1)).sum(-1)
                    actor_kl = _kl(output["actor"].softmax(-1), batch["behavior"])
                    loss = (weights * (per_step + 0.2 * actor_ce + 0.1 * actor_kl)).sum()
                if not bool(torch.isfinite(loss)):
                    raise ValueError("nonfinite policy training loss")
                optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), 2.0)
                optimizer.step()
                history.append(float(loss.detach()))
            model.eval()
            histories[method] = history
            if method == "ndu":
                with torch.no_grad():
                    output, following = model(states), model(next_states)
                    residual = torch.where(batch["done"][:, None].bool(), boundary, following["y"]) - output["y"]
                    residual -= (output["z"] * delta_m[:, None, :]).sum(-1)
                    diagnostics = {"training_path_residual_mse": float((weights * residual.square().mean(-1)).sum()),
                                   "training_terminal_residual_mse": float(residual[batch["done"].bool()].square().mean())}
        self.training_metadata = {"algorithm": "discrete_bsde_prototype", "continuous_fbsde_solved": False,
            "merton_optimality_proven": False, "policy_improvement": "finite_offline_approximation",
            "martingale_basis": "action_only", "state_representation_complete": False,
            "quality_risk_claim": "requires_independent_heldout_evaluation", "source": "caller_supplied_train_only",
            "trajectories": len(trajectories), "transitions": len(states),
            "action_counts": torch.bincount(actions, minlength=6).tolist(),
            "behavior_prior": self.prior.tolist(), "epochs": epochs, "learning_rate": learning_rate,
            "training_risk_weight": risk_weight, "tail_threshold": threshold,
            "tail_statistic": "normalized_fixed_threshold_hinge_not_CVaR",
            "risk_probabilities_calibrated": False, "coverage_limitation": "finite_random_behavior_support",
            "common_initial_weights": True,
            "seconds": time.perf_counter() - started, "loss_history": histories, **diagnostics,
            "parameters_per_method": {key: sum(p.numel() for p in model.parameters()) for key, model in self.models.items()}}
        return self

    @torch.no_grad()
    def action(self, features, method, risk_weight=0.5, covariance=None, seed=None, deterministic=False):
        if self.training_metadata is None:
            raise ValueError("fit or load policies before inference")
        if method not in METHODS or not math.isfinite(risk_weight) or risk_weight < 0:
            raise ValueError("unknown method or invalid risk weight")
        state = torch.as_tensor(features, dtype=torch.float32).detach().cpu()
        if state.shape != (24,) or not bool(torch.isfinite(state).all()):
            raise ValueError("24 finite inference features required")
        output = self.models[method](((state - self.mean) / self.scale).unsqueeze(0))
        quality, _, risk = self._estimates(output, method, self.prior.unsqueeze(0))
        applied_risk = 0.0 if method in ("mean_only", "learned_router") else risk_weight
        penalty = torch.zeros(6)
        if method == "ndu" and covariance is not None:
            gram = torch.as_tensor(covariance, dtype=torch.float32).detach().cpu()
            if (gram.shape != (4, 4) or not bool(torch.isfinite(gram).all())
                    or not torch.allclose(gram, gram.T, atol=1e-5) or float(torch.linalg.eigvalsh(gram).min()) < -1e-5):
                raise ValueError("local disagreement proxy must be a finite symmetric PSD 4x4 matrix")
            directions = torch.tensor(ACTION_WEIGHTS)
            penalty = ((directions @ gram) * directions).sum(-1).clamp_min(0)
        score = quality[0].clamp(0, 1) - applied_risk * (risk[0] + self.config["covariance_strength"] * penalty)
        logits = output["actor"][0]
        if method != "learned_router":
            logits = 0.25 * logits + score / self.config["temperature"]
        probability = _conservative_distribution(logits, self.prior, self.config["kl_bound"])
        generator = self.generator if seed is None else torch.Generator().manual_seed(int(seed))
        action = int(probability.argmax()) if deterministic else int(torch.multinomial(probability, 1, generator=generator))
        algorithm = "discrete_bsde_prototype" if method == "ndu" else method
        return {"action": action, "weights": list(ACTION_WEIGHTS[action]), "metadata": {
            "method": method, "algorithm": algorithm, "risk_weight": applied_risk,
            "action_probs": probability.tolist(), "behavior_kl": float(_kl(probability, self.prior)),
            "kl_bound": self.config["kl_bound"], "sampled_policy": not deterministic,
            "hard_kl_applies_to_executed_policy": not deterministic, "seed": seed,
            "quality_estimates": quality[0].clamp(0, 1).tolist(), "risk_scores_uncalibrated": risk[0].tolist(),
            "local_disagreement_penalty": penalty.tolist(),
            "covariance_kind": "local_cell_logit_disagreement_proxy" if method == "ndu" and covariance is not None else None,
            "terminal_output_covariance_estimated": False, "continuous_fbsde_solved": False}}

    def save(self, path):
        if self.training_metadata is None:
            raise ValueError("cannot save untrained policies")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save({"format": "hepta.discrete-policies.v1", "config": self.config,
                    "models": self.models.state_dict(), "mean": self.mean, "scale": self.scale,
                    "prior": self.prior, "metadata": self.training_metadata,
                    "generator": self.generator.get_state()}, path)
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @classmethod
    def load(cls, path):
        saved = torch.load(path, map_location="cpu", weights_only=True)
        if saved["format"] != "hepta.discrete-policies.v1":
            raise ValueError("unknown policy checkpoint")
        model = cls(**saved["config"])
        model.models.load_state_dict(saved["models"])
        model.models.eval()
        model.mean, model.scale, model.prior = saved["mean"], saved["scale"], saved["prior"]
        model.training_metadata = saved["metadata"]
        model.generator.set_state(saved["generator"])
        return model
