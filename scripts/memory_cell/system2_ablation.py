"""Bounded research policies on the existing shared Features interface.

No encoder copy, reader replacement, runtime writer or private outcome authority.
Source-support supervision is not proof that an evidence set is sufficient.
The eight arms have identical resource CEILINGS, not fictional identical costs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import itertools
import math
import json
from pathlib import Path
import sys
import time

import torch
from torch import nn

NDU_RESEARCH = Path(__file__).resolve().parents[2] / "codex-rs/hepta-ndu/research"
sys.path.insert(0, str(NDU_RESEARCH))
from finite_tree_bsde import Profile, solve_path  # noqa: E402

ARMS = (
    "rag",
    "linear",
    "gated",
    "recurrent",
    "tree_critic",
    "ndu_deterministic",
    "fbsde_stochastic",
    "wrong_stitch_control",
)


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def model_digest(model: nn.Module) -> str:
    h = hashlib.sha256()
    for name, value in sorted(model.state_dict().items()):
        x = value.detach().cpu().contiguous()
        h.update(name.encode())
        h.update(str((x.dtype, tuple(x.shape))).encode())
        h.update(x.numpy().tobytes())
    return h.hexdigest()


class BudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class Limits:
    operations: int = 100000
    seconds: float = 30.0
    evidence: int = 3
    candidates: int = 4

    def validate(self):
        if (
            type(self.operations) is not int
            or not 1 <= self.operations <= 1000000
            or not math.isfinite(self.seconds)
            or not 0 < self.seconds <= 300
            or type(self.evidence) is not int
            or not 1 <= self.evidence <= 4
            or type(self.candidates) is not int
            or not 1 <= self.candidates <= 8
        ):
            raise ValueError("invalid research budget")


class Meter:
    def __init__(self, limits: Limits):
        limits.validate()
        self.limits, self.started, self.used = limits, time.perf_counter(), {}

    def charge(self, kind: str, count: int = 1):
        if type(count) is not int or count < 0:
            raise ValueError("invalid work increment")
        # Counts are attempted work. An over-budget attempt is never erased.
        self.used[kind] = self.used.get(kind, 0) + count
        if sum(self.used.values()) > self.limits.operations:
            raise BudgetExceeded("operation ceiling")
        if time.perf_counter() - self.started > self.limits.seconds:
            raise BudgetExceeded("wall-time ceiling at operation boundary")

    def receipt(self):
        return dict(
            attempted_operations=dict(self.used),
            elapsed_seconds=time.perf_counter() - self.started,
            limits=asdict(self.limits),
            preemptive_kernel_timeout=False,
        )


class Continuation(nn.Module):
    """Small shared latent transition and terminal critic; no per-node encoder."""

    def __init__(self, dimension: int, hidden: int = 16, seed: int = 719):
        super().__init__()
        if not 1 <= dimension <= 1024 or not 2 <= hidden <= 64:
            raise ValueError("bounded continuation architecture")
        self.dimension, self.hidden = dimension, hidden
        self.encoder_identity, self.roots, self.quarantined = None, frozenset(), False
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed)
            self.project = nn.Linear(dimension, hidden)
            self.cell = nn.GRUCell(hidden, hidden)
            self.critic = nn.Linear(hidden, 1)

    def action_vectors(self, paired):
        return torch.tanh(self.project(paired))

    def transition(self, h, a):
        return self.cell(a.unsqueeze(0), h.unsqueeze(0)).squeeze(0)

    def value(self, h):
        return torch.sigmoid(self.critic(h)).squeeze(-1)

    def forward(self, paired):
        h = paired.new_zeros(self.hidden)
        for a in self.action_vectors(paired):
            h = h + 0.1 * (self.transition(h, a) - h)
        return self.value(h)


def train_continuation(model, rows, cut, *, steps=96, pair_ceiling=100000, seed=719):
    """Labels only from the admitted train cut; SGD/no hidden momentum state.

    Target is any native source-support hit, NOT joint semantic sufficiency.
    All admission checks complete before the first mutation.
    """
    if (
        type(steps) is not int
        or not 1 <= steps <= 2048
        or not 1 <= len(rows) <= 256
        or not cut.admission_digest
        or model.quarantined
        or torch.is_inference_mode_enabled()
        or model.roots.intersection(cut.forbidden_roots)
    ):
        raise ValueError("invalid admitted training session")
    seen, identities, roots = set(), set(), set()
    for r in rows:
        f = r.features
        f.validate(model.dimension)
        if (
            f.question_id in seen
            or f.question_id not in cut.question_ids
            or f.family not in cut.families
            or not f.roots.issubset(cut.allowed_roots)
            or f.roots.intersection(cut.forbidden_roots)
            or len(set(r.positive_indices)) != len(r.positive_indices)
            or any(
                type(i) is not int or not 0 <= i < len(f.candidate_ids)
                for i in r.positive_indices
            )
        ):
            raise ValueError("training leakage/duplicate/unadmitted source")
        seen.add(f.question_id)
        identities.add(f.encoder_identity)
        roots.update(f.roots)
    if len(identities) != 1 or (
        model.encoder_identity is not None and model.encoder_identity not in identities
    ):
        raise ValueError("continuation encoder lineage mismatch")
    before, meter = (
        model_digest(model),
        Meter(Limits(operations=pair_ceiling, seconds=300)),
    )
    optimizer = torch.optim.SGD(model.parameters(), lr=0.03)
    random = torch.Generator().manual_seed(seed)
    loss_values = []
    try:
        for step in range(steps):
            r = rows[step % len(rows)]
            n = len(r.features.candidate_ids)
            count = min(step % 4, n)
            indices = torch.randperm(n, generator=random)[:count].tolist()
            meter.charge("training_examples", 1)
            meter.charge("training_pairs", count)
            predicted = model(r.features.paired[indices])
            target = predicted.new_tensor(
                float(bool(set(indices).intersection(r.positive_indices)))
            )
            loss = torch.nn.functional.binary_cross_entropy(predicted, target)
            optimizer.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0, error_if_nonfinite=True)
            optimizer.step()
            loss_values.append(float(loss.detach()))
        if not loss_values or not all(
            torch.isfinite(p).all() for p in model.parameters()
        ):
            raise ValueError("no finite continuation training")
    except Exception:
        model.quarantined = True
        raise
    model.encoder_identity = next(iter(identities))
    model.roots = model.roots.union(roots)
    return dict(
        before=before,
        after=model_digest(model),
        updates=len(loss_values),
        objective="any-native-support-not-joint-sufficiency",
        costs=meter.receipt(),
        initial_loss=loss_values[0],
        final_loss=loss_values[-1],
    )


def _rank(scores, ids):
    return sorted(range(len(ids)), key=lambda i: (-float(scores[i]), ids[i]))


@torch.no_grad()
def choose_set(
    arm,
    feature,
    heads,
    continuation,
    meter: Meter,
    *,
    revoked=frozenset(),
    profile=None,
):
    if arm not in ARMS:
        raise ValueError("unregistered ablation arm")
    feature.validate(continuation.dimension)
    if feature.roots.intersection(revoked):
        raise ValueError("withdrawn inference source")
    if arm not in ("rag", "linear", "gated") and (
        continuation.roots.intersection(revoked)
        or continuation.quarantined
        or continuation.encoder_identity != feature.encoder_identity
    ):
        raise ValueError("withdrawn/unbound continuation")
    count = len(feature.candidate_ids)
    meter.charge("candidate_validation", count)
    if not count:
        return (), dict(reason="empty-pool", solvers=[])
    scores, null_score = feature.frozen_scores, 0.0
    ranked = _rank(scores, feature.candidate_ids)
    if arm in ("linear", "gated"):
        head = heads[arm]
        if head.roots.intersection(revoked):
            raise ValueError("withdrawn trained head")
        meter.charge("head_pairs", count)
        logits = head(feature)
        scores, null_score = logits[:-1], float(logits[-1])
        ranked = _rank(scores, feature.candidate_ids)
    if arm in ("rag", "linear", "gated"):
        selected = (
            ()
            if null_score >= float(scores[ranked[0]])
            else tuple(ranked[: meter.limits.evidence])
        )
        return selected, dict(solvers=[], null_score=null_score)
    proposal = ranked[: meter.limits.candidates]
    meter.charge("projection", count)
    vectors = continuation.action_vectors(feature.paired)
    initial = vectors.new_zeros(continuation.hidden)
    paths = [
        tuple(p)
        for d in range(1, min(len(proposal), meter.limits.evidence) + 1)
        for p in itertools.combinations(proposal, d)
    ]
    if arm == "recurrent":
        # Fixed greedy expansion, not tree search or backward propagation.
        paths = [
            tuple(proposal[:d])
            for d in range(1, min(len(proposal), meter.limits.evidence) + 1)
        ]
    meter.charge("critic", 1)
    results = [(float(continuation.value(initial)), (), None)]
    # Primary ablation fixes the state integrator; feedback coupling is a
    # separately configurable solver stress profile, not an unreported factor.
    base_profile = profile or Profile(coupling=0.0)
    for path in paths:
        p = Profile(
            **(
                asdict(base_profile)
                | {"horizon": base_profile.horizon * len(path) / meter.limits.evidence}
            )
        )
        if arm in ("tree_critic", "recurrent"):
            h = initial
            for i in path:
                meter.charge("transition", 1)
                next_h = continuation.transition(h, vectors[i])
                h = h + (p.horizon / len(path)) * (next_h - h)
            meter.charge("critic", 1)
            value, solver = float(continuation.value(h)), None
        else:
            if arm == "ndu_deterministic":
                p = Profile(**(asdict(p) | {"sigma": 0.0}))
            solver = solve_path(
                vectors[list(path)],
                initial,
                continuation.transition,
                continuation.value,
                p,
                meter.charge,
                wrong_boundary=arm == "wrong_stitch_control",
            )
            if not solver.converged and arm != "wrong_stitch_control":
                raise ValueError("finite-tree FBSDE residual did not converge")
            value = solver.value
        results.append((value, path, None if solver is None else asdict(solver)))
    # All paths represent admissible actions; chance nodes were integrated, not selected.
    best = min(
        results,
        key=lambda row: (-row[0], tuple(feature.candidate_ids[i] for i in row[1])),
    )
    return best[1], dict(
        value=best[0],
        paths=len(paths),
        solvers=[x[2] for x in results if x[2]],
        selected_solver=best[2],
        action_search="bounded-subset-enumeration",
    )


def execute_matrix(
    feature, heads, continuation, reader, *, limits=Limits(), revoked=frozenset()
):
    """One shared feature extraction is supplied by the existing cache owner.

    reader(selected_indices) must validate source lineage, use one frozen
    FrozenBundleReader, and return (raw_answer, receipt). Labels cannot enter it.
    Each arm gets exactly one attempted reader call after a successful policy.
    All failures remain in the result; there is no successful-row denominator.
    """
    stamps = {
        name: model_digest(model)
        for name, model in {**heads, "continuation": continuation}.items()
    }
    records = []
    feature_stamp = feature.seal()
    offset = int(digest(feature.question_id)[:8], 16) % len(ARMS)
    execution_order = ARMS[offset:] + ARMS[:offset]
    for arm in execution_order:
        meter, record = (
            Meter(limits),
            dict(
                arm=arm,
                question_id=feature.question_id,
                family=feature.family,
                feature_digest=feature.seal(),
            ),
        )
        try:
            selected, policy = choose_set(
                arm, feature, heads, continuation, meter, revoked=revoked
            )
            record.update(selected=list(selected), policy=policy)
            meter.charge("reader_calls", 1)
            answer, receipt = reader(selected)
            if not isinstance(answer, str) or not answer.strip():
                raise ValueError("empty or invalid reader answer")
            record.update(answer=answer, reader=receipt)
            # Preserve an observed answer even if the latency ceiling was exceeded.
            meter.charge("post_reader_check", 0)
            record.update(status="succeeded")
        except Exception as exc:
            record.update(
                status="failed", error_type=type(exc).__name__, error=str(exc)[:512]
            )
        after = {
            name: model_digest(model)
            for name, model in {**heads, "continuation": continuation}.items()
        }
        if feature.seal() != feature_stamp:
            raise ValueError("evaluation mutated shared features")
        if after != stamps:
            raise ValueError("evaluation mutated shared parameters")
        record["cost"] = meter.receipt()
        records.append(record)
    return records


def census(records, question_ids):
    expected = {(q, a) for q in question_ids for a in ARMS}
    actual = [(r["question_id"], r["arm"]) for r in records]
    if len(question_ids) != len(set(question_ids)) or any(
        r.get("status") not in ("succeeded", "failed") for r in records
    ):
        raise ValueError("invalid census identity/status")
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("missing/duplicated/extra planned attempt")
    return dict(
        planned=len(expected),
        recorded=len(actual),
        complete=True,
        succeeded=sum(r["status"] == "succeeded" for r in records),
        failed=sum(r["status"] == "failed" for r in records),
        equal_resource_ceilings=True,
        equal_observed_cost=False,
        native_reasoning_superiority=False,
        production_accepted=False,
    )
