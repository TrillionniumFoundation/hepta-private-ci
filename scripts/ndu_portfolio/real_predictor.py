"""Deployable predictive controllers over public, actually encoded observations.

This is a model-based implementation, not the toy environment's oracle. Its
finite ensemble is a learned prediction law, not an independently calibrated
truth distribution. Fitting uses registered train transitions and external
training labels. No evaluation target or counterfactual executor is available
to choose(). Joint fitting here updates the controller's content state and
predictive heads; it does not claim joint-return training of frozen generators.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import time
import uuid

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from experiments.multimodal_output_portfolio.joint_hepta_20261029 import hepta_core


ACTIONS = ("perceive", "text", "draft", "revise", "refine", "verify", "stop")
CORE_SHA256 = "54c2e9724f6cb924582451bea907d671fe510963879117dd5f00cf4e95f1e978"


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def parameter_digest(model):
    value = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        value.update(name.encode())
        value.update(str((str(tensor.dtype), tuple(tensor.shape))).encode())
        value.update(tensor.detach().cpu().contiguous().numpy().tobytes())
    return value.hexdigest()


def _number(value, name, positive=False):
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or value < 0
        or (positive and value == 0)
    ):
        raise ValueError("invalid " + name)
    return float(value)


@dataclass(frozen=True)
class Observation:
    encoding: tuple
    has_text: bool
    has_image: bool
    remaining_cost: float
    remaining_seconds: float
    remaining_steps: int

    def __post_init__(self):
        values = np.asarray(self.encoding)
        if (
            values.ndim != 1
            or not 1 <= len(values) <= 4096
            or values.dtype.kind not in "fi"
            or not np.isfinite(values).all()
        ):
            raise ValueError("finite public encoding of bounded width required")
        object.__setattr__(self, "encoding", tuple(float(x) for x in values))
        if type(self.has_text) is not bool or type(self.has_image) is not bool:
            raise ValueError("availability must be observable booleans")
        _number(self.remaining_cost, "remaining cost")
        _number(self.remaining_seconds, "remaining seconds")
        if type(self.remaining_steps) is not int or not 0 <= self.remaining_steps <= 32:
            raise ValueError("bounded decision horizon required")

    @classmethod
    def parse(cls, value):
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise ValueError(
                "public observation fields differ; labels and identities are forbidden"
            )
        return cls(**value)

    def features(self):
        return (
            *self.encoding,
            float(self.has_text),
            float(self.has_image),
            math.log1p(self.remaining_cost),
            math.log1p(self.remaining_seconds),
            self.remaining_steps / 32,
        )

    def legal(self):
        if min(self.remaining_steps, self.remaining_cost, self.remaining_seconds) <= 0:
            return ("stop",)
        return tuple(
            a
            for a in ACTIONS
            if a != "refine" or self.has_image
            if a != "verify" or (self.has_text and self.has_image)
        )


@dataclass(frozen=True)
class Opportunity:
    """A common opportunity ceiling; actual use is reported, never padded."""

    max_parameters: int
    training_rows: int
    updates: int
    search_trials: int
    fit_wall_seconds: float
    planner_nodes: int

    def __post_init__(self):
        for name in (
            "max_parameters",
            "training_rows",
            "updates",
            "search_trials",
            "planner_nodes",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError("positive integer opportunity required: " + name)
        _number(self.fit_wall_seconds, "fit wall", positive=True)
        if (
            self.planner_nodes > 100000
            or self.updates > 100000
            or self.training_rows > 1000000
        ):
            raise ValueError("opportunity exceeds this bounded implementation")


class PredictiveModel(nn.Module):
    def __init__(
        self, encoding_width, width=16, members=2, core="ordinary", encoding_digest=None
    ):
        super().__init__()
        if (
            hashlib.sha256(Path(hepta_core.__file__).read_bytes()).hexdigest()
            != CORE_SHA256
        ):
            raise ValueError("Hepta implementation differs from the reviewed source")
        if (
            core not in ("ordinary", "hepta")
            or type(members) is not int
            or not 1 <= members <= 8
            or type(encoding_width) is not int
            or not 1 <= encoding_width <= 4096
        ):
            raise ValueError("invalid predictive model profile")
        if encoding_digest is not None and (
            not isinstance(encoding_digest, str)
            or len(encoding_digest) != 64
            or any(c not in "0123456789abcdef" for c in encoding_digest)
        ):
            raise ValueError("invalid encoder contract digest")
        self.config = dict(
            encoding_width=encoding_width,
            width=width,
            members=members,
            core=core,
            encoding_digest=encoding_digest,
        )
        self.fit_receipt = None
        self.encoder = nn.Linear(encoding_width + 5, width)
        self.core = hepta_core.HeptaCore(
            width, mode="dual" if core == "hepta" else "ordinary"
        )
        self.transitions = nn.ModuleList(
            nn.Linear(width + len(ACTIONS), encoding_width + 2) for _ in range(members)
        )
        self.values = nn.ModuleList(nn.Linear(width, 1) for _ in range(members))

    def hidden(self, features):
        value = self.encoder(features).tanh()
        state = self.core.initial_state(len(value), content=value)
        return self.core.step(value, state, 0.5)[0].tanh()

    def forward(self, features, actions):
        hidden = self.hidden(features)
        joined = torch.cat(
            (hidden, F.one_hot(actions, len(ACTIONS)).to(hidden.dtype)), -1
        )
        return [
            (head(joined), value(hidden).sigmoid().squeeze(-1))
            for head, value in zip(self.transitions, self.values, strict=True)
        ]

    def set_regime(self, regime):
        if regime not in ("frozen", "joint"):
            raise ValueError("unknown fitting regime")
        self.requires_grad_(True)
        if regime == "frozen":
            self.encoder.requires_grad_(False)
            self.core.requires_grad_(False)

    @torch.no_grad()
    def terminal(self, observation):
        anchor = next(self.parameters())
        hidden = self.hidden(
            torch.tensor(
                [observation.features()], device=anchor.device, dtype=anchor.dtype
            )
        )
        return [float(value(hidden).sigmoid().item()) for value in self.values]

    @torch.no_grad()
    def forecast(self, observation, action):
        anchor = next(self.parameters())
        features = torch.tensor(
            [observation.features()], device=anchor.device, dtype=anchor.dtype
        )
        index = torch.tensor([ACTIONS.index(action)], device=anchor.device)
        branches = []
        for prediction, _ in self(features, index):
            row = prediction[0]
            cost, seconds = F.softplus(row[-2:]).tolist()
            if (
                cost > observation.remaining_cost
                or seconds > observation.remaining_seconds
            ):
                branches.append((None, cost, seconds))
                continue
            text, image = observation.has_text, observation.has_image
            if action in ("perceive", "revise"):
                text = image = False
            elif action == "text":
                text = True
            elif action in ("draft", "refine"):
                image = True
            successor = Observation(
                tuple(row[:-2].tolist()),
                text,
                image,
                observation.remaining_cost - cost,
                observation.remaining_seconds - seconds,
                observation.remaining_steps - 1,
            )
            branches.append((successor, cost, seconds))
        return branches


def fit_predictive(model, rows, opportunity, *, allowed_sources, regime, seed, output):
    """Fit actual transition/score labels. Hash declarations do not certify origin.

    Every call is an independent physical fit attempt with its own directory.
    CPU/wall and failures remain in its receipt; finite-budget overruns do not
    produce an admissible checkpoint. No confirmation/development rows fit it.
    """
    path = Path(output)
    path.mkdir(parents=True, exist_ok=False)
    model.fit_receipt = None
    start = time.process_time(), time.perf_counter()
    report = {
        "attempt_id": uuid.uuid4().hex,
        "status": "started",
        "seed": seed,
        "regime": regime,
        "opportunity": asdict(opportunity),
        "updates": 0,
        "input_digest": None,
        "initial_model_digest": parameter_digest(model),
        "source_provenance": "EXTERNAL_RECEIPTS_NOT_NATIVE_AUTHENTICATED",
    }
    try:
        report["input_digest"] = digest(rows)
        if type(seed) is not int or not rows or len(rows) > opportunity.training_rows:
            raise ValueError("invalid fit seed or row opportunity exceeded")
        if sum(p.numel() for p in model.parameters()) > opportunity.max_parameters:
            raise ValueError("model exceeds common parameter opportunity")
        fields = {
            "split",
            "source_group",
            "episode_group",
            "observation",
            "next_observation",
            "action",
            "utility",
            "next_utility",
            "cost",
            "seconds",
            "execution_receipt",
            "evaluator_receipt",
            "encoding_digest",
        }
        source_groups, episodes, executions = set(), {}, set()
        observations, successors, actions, targets = [], [], [], []
        for row in rows:
            if (
                set(row) != fields
                or row["split"] != "train"
                or row["source_group"] not in allowed_sources
            ):
                raise ValueError(
                    "only registered training transitions may fit the model"
                )
            for key in ("execution_receipt", "evaluator_receipt"):
                if len(row[key]) != 64 or any(
                    c not in "0123456789abcdef" for c in row[key]
                ):
                    raise ValueError(
                        "missing external training execution/scoring receipt"
                    )
            if row["execution_receipt"] == row["evaluator_receipt"]:
                raise ValueError("training outcome needs a separate evaluator receipt")
            if row["execution_receipt"] in executions:
                raise ValueError("duplicate physical training transition receipt")
            executions.add(row["execution_receipt"])
            encoding_digest = row["encoding_digest"]
            if (
                not isinstance(encoding_digest, str)
                or len(encoding_digest) != 64
                or any(c not in "0123456789abcdef" for c in encoding_digest)
            ):
                raise ValueError(
                    "training features need a frozen encoder contract digest"
                )
            if model.config["encoding_digest"] is None:
                model.config["encoding_digest"] = encoding_digest
            if model.config["encoding_digest"] != encoding_digest:
                raise ValueError("training encoder identity changed")
            old = episodes.setdefault(row["episode_group"], row["source_group"])
            if old != row["source_group"]:
                raise ValueError("episode group cannot change upstream source")
            before, after = (
                Observation.parse(row["observation"]),
                Observation.parse(row["next_observation"]),
            )
            if row["action"] == "stop" or row["action"] not in before.legal():
                raise ValueError(
                    "training transition is not an actual legal nonterminal action"
                )
            if len(before.encoding) != model.config["encoding_width"] or len(
                after.encoding
            ) != len(before.encoding):
                raise ValueError("training encoder width differs from model")
            utility = [
                _number(row[k], k)
                for k in ("utility", "next_utility", "cost", "seconds")
            ]
            if max(utility[:2]) > 1:
                raise ValueError("registered utility must lie in [0,1]")
            source_groups.add(row["source_group"])
            observations.append(before.features())
            successors.append(after.features())
            actions.append(ACTIONS.index(row["action"]))
            targets.append(utility)
        model.set_regime(regime)
        anchor = next(model.parameters())
        tensor = lambda x: torch.tensor(x, dtype=anchor.dtype, device=anchor.device)
        x, nxt, y = tensor(observations), tensor(successors), tensor(targets)
        a = torch.tensor(actions, device=anchor.device)
        rng = np.random.default_rng(seed)
        optimizer = torch.optim.Adam(
            [p for p in model.parameters() if p.requires_grad], lr=0.001
        )
        for update in range(opportunity.updates):
            if time.perf_counter() - start[1] > opportunity.fit_wall_seconds:
                raise TimeoutError("fit opportunity exhausted")
            optimizer.zero_grad(set_to_none=True)
            loss = 0
            for member in range(model.config["members"]):
                sample = torch.tensor(
                    rng.integers(0, len(rows), len(rows)), device=anchor.device
                )
                prediction, value = model(x[sample], a[sample])[member]
                next_hidden = model.hidden(nxt[sample])
                next_value = model.values[member](next_hidden).sigmoid().squeeze(-1)
                loss = loss + F.mse_loss(
                    prediction[:, :-2], nxt[sample, : model.config["encoding_width"]]
                )
                loss = loss + F.mse_loss(F.softplus(prediction[:, -2:]), y[sample, 2:])
                loss = (
                    loss
                    + F.mse_loss(value, y[sample, 0])
                    + F.mse_loss(next_value, y[sample, 1])
                )
            if not torch.isfinite(loss):
                raise ValueError("nonfinite predictive fitting objective")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            report["updates"] = update + 1
        if time.perf_counter() - start[1] > opportunity.fit_wall_seconds:
            raise TimeoutError("fit opportunity exhausted after update")
        report.update(
            status="completed",
            model_digest=parameter_digest(model),
            source_groups=sorted(source_groups),
            training_rows=len(rows),
            parameters=sum(p.numel() for p in model.parameters()),
            trainable_parameters=sum(
                p.numel() for p in model.parameters() if p.requires_grad
            ),
        )
        torch.save(
            {"config": model.config, "state_dict": model.state_dict(), "fit": report},
            path / "model.pt",
        )
        if time.perf_counter() - start[1] > opportunity.fit_wall_seconds:
            raise TimeoutError("fit opportunity exhausted while saving checkpoint")
    except BaseException as error:
        report.update(
            status="failed", error_type=type(error).__name__, error=str(error)
        )
        raise
    finally:
        report.update(
            cpu_seconds=time.process_time() - start[0],
            wall_seconds=time.perf_counter() - start[1],
            claim_status="HOLD",
            fitting_objective="supervised_predictive_not_joint_generator_return",
            unknown_costs=["energy", "external_data_collection", "final_receipt_write"],
        )
        (path / "fit.json").write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n"
        )
    model.fit_receipt = dict(report)
    return report
