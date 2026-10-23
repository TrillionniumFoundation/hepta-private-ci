"""Prospective, factorial Cell-credit qualification (SHADOW ONLY).

A complete sealed *symbolic* coalition ledger establishes bookkeeping under
stated counterfactual consistency assumptions, NOT real causal identification.
The verifier supplied by the caller is not an independently deployed trust root.
No effect, promotion, selection, or model execution authority is granted.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from hashlib import sha256
from itertools import combinations
from math import factorial, fsum, isfinite, log, sqrt
import json
from collections.abc import Callable, Sequence

Verifier = Callable[[str, str, str], bool]


class CreditRejected(ValueError):
    """No partial or guessed factorial evidence is accepted."""


def _digest(value: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        c in "0123456789abcdef" for c in value
    )


def _number(value: object, *, positive: bool = False) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (float, int))
        and isfinite(value)
        and (value > 0 if positive else True)
    )


def _seal(record: object, domain: bytes, excluded: set[str]) -> str:
    data = {field.name: getattr(record, field.name)
            for field in fields(record) if field.name not in excluded}
    try:
        raw = json.dumps(data, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CreditRejected("unserializable or nonfinite sealed evidence") from exc
    return sha256(domain + b"\x00" + raw).hexdigest()


@dataclass(frozen=True)
class ProspectiveCreditTrial:
    trial_id: str
    actor_id: str
    registrar_id: str
    objective_digest: str
    snapshot_digest: str
    encoder_digest: str
    decoder_digest: str
    critic_digest: str
    generation: int
    registered_at: int
    future_from: int
    # Frozen BEFORE observing outcomes: (episode_id, cluster_id, input_digest).
    episodes: tuple[tuple[str, str, str], ...]
    cells: tuple[str, ...]
    resource_price: float
    risk_price: float
    max_compute_units: float
    abs_ndu_bound: float
    max_pair_interaction_fraction: float
    alpha: float
    registrar_signature: str

    def digest(self) -> str:
        return _seal(self, b"hepta.ndu-dmgp.credit-protocol.v1",
                     {"registrar_signature"})

    def check(self) -> None:
        if (not self.trial_id or not self.actor_id or not self.registrar_id
                or self.actor_id == self.registrar_id
                or type(self.generation) is not int or self.generation <= 0
                or type(self.registered_at) is not int
                or type(self.future_from) is not int
                or not 0 < self.registered_at < self.future_from):
            raise CreditRejected("invalid or retroactive prospective trial")
        if not all(_digest(v) for v in (
                self.objective_digest, self.snapshot_digest,
                self.encoder_digest, self.decoder_digest, self.critic_digest)):
            raise CreditRejected("missing frozen model or objective digest")
        if (not 1 <= len(self.cells) <= 6
                or self.cells != tuple(sorted(set(self.cells)))
                or any(not c for c in self.cells)):
            raise CreditRejected("illegal, duplicate or noncanonical Cell roster")
        if (not 32 <= len(self.episodes) <= 4096
                or len({row[0] for row in self.episodes}) != len(self.episodes)
                or len({row[1] for row in self.episodes}) != len(self.episodes)
                or any(len(row) != 3 or not row[0] or not row[1]
                       or not _digest(row[2]) for row in self.episodes)):
            raise CreditRejected("incomplete or dependent preregistered episodes")
        if (not all(_number(v) for v in (
                self.resource_price, self.risk_price,
                self.max_pair_interaction_fraction, self.alpha))
                or self.resource_price < 0 or self.risk_price < 0
                or not _number(self.max_compute_units, positive=True)
                or not _number(self.abs_ndu_bound, positive=True)
                or not 0 <= self.max_pair_interaction_fraction <= 1
                or not 0 < self.alpha < 1):
            raise CreditRejected("invalid frozen risk, resource or statistical profile")


@dataclass(frozen=True)
class CoalitionOutcome:
    trial_id: str
    episode_id: str
    cluster_id: str
    input_digest: str
    objective_digest: str
    snapshot_digest: str
    critic_digest: str
    generation: int
    active_cells: tuple[str, ...]
    split: str
    observed_at: int
    actor_id: str
    observer_id: str
    meter_id: str
    quality: float
    compute_units: float
    risk: float
    output_digest: str
    meter_digest: str
    evidence_kind: str
    observer_signature: str
    meter_signature: str

    def digest(self) -> str:
        return _seal(self, b"hepta.ndu-dmgp.coalition-observation.v1",
                     {"observer_signature", "meter_signature"})


@dataclass(frozen=True)
class CreditVerdict:
    episodes: int
    cells: tuple[str, ...]
    mean_shapley: tuple[float, ...]
    simultaneous_credit_lcb: tuple[float, ...]
    mean_global_delta: float
    max_pair_interaction_fraction: float
    low_interaction_supported: bool
    positive_local_credit_supported: bool
    exact_factorial_complete: bool = True
    causal_effect_identified: bool = False
    production_blockers_closed: bool = False
    production_authority: bool = False


def _shapley(values: dict[frozenset[str], float],
             cells: tuple[str, ...]) -> tuple[float, ...]:
    k = len(cells)
    total = factorial(k)
    credits = []
    for cell in cells:
        other = tuple(c for c in cells if c != cell)
        parts = []
        for size in range(k):
            weight = factorial(size) * factorial(k - size - 1) / total
            for subset in combinations(other, size):
                s = frozenset(subset)
                parts.append(weight * (values[s | {cell}] - values[s]))
        credits.append(fsum(parts))
    return tuple(credits)


def _pair_interaction(values: dict[frozenset[str], float],
                      cells: tuple[str, ...]) -> float:
    """Strongest context-conditioned 2nd difference, not a causal interaction."""
    result = 0.0
    for i, j in combinations(cells, 2):
        others = tuple(c for c in cells if c not in (i, j))
        for size in range(len(others) + 1):
            for subset in combinations(others, size):
                s = frozenset(subset)
                interaction = (values[s | {i, j}] - values[s | {i}]
                               - values[s | {j}] + values[s])
                result = max(result, abs(interaction))
    return result


def verify_factorial_credit(
    trial: ProspectiveCreditTrial,
    observations: Sequence[CoalitionOutcome],
    verifier: Verifier | None,
) -> CreditVerdict:
    """Requires a preregistered complete 2^k panel on every held-out episode.

    Observation/model seals are structurally checked. Signer provenance and
    randomized counterfactual consistency require OUTSIDE verification.
    """
    trial.check()
    if verifier is None or not trial.registrar_signature:
        raise CreditRejected("prospective independent verifier unavailable")
    if not verifier(trial.registrar_id, trial.digest(), trial.registrar_signature):
        raise CreditRejected("prospective registration signature rejected")
    roster = {episode: (cluster, inp) for episode, cluster, inp in trial.episodes}
    expected = {frozenset(s) for size in range(len(trial.cells) + 1)
                for s in combinations(trial.cells, size)}
    if len(observations) != len(roster) * len(expected):
        raise CreditRejected("incomplete, repeated or selectively omitted factorial panel")
    cells_set = set(trial.cells)
    panel: dict[str, dict[frozenset[str], float]] = {}
    for obs in observations:
        if (obs.episode_id not in roster
                or (obs.cluster_id, obs.input_digest) != roster[obs.episode_id]
                or obs.trial_id != trial.trial_id
                or obs.objective_digest != trial.objective_digest
                or obs.snapshot_digest != trial.snapshot_digest
                or obs.critic_digest != trial.critic_digest
                or type(obs.generation) is not int or obs.generation != trial.generation
                or obs.split != "future" or type(obs.observed_at) is not int
                or obs.observed_at < trial.future_from
                or obs.actor_id != trial.actor_id
                or len({obs.actor_id, trial.registrar_id,
                        obs.observer_id, obs.meter_id}) != 4
                or not obs.observer_id or not obs.meter_id
                or obs.evidence_kind != "independent_observation"):
            raise CreditRejected("outcome identity, provenance, split or chronology mismatch")
        if (obs.active_cells != tuple(sorted(set(obs.active_cells)))
                or not set(obs.active_cells).issubset(cells_set)
                or not _digest(obs.output_digest)
                or not _digest(obs.meter_digest)):
            raise CreditRejected("incomplete or invalid coalition/decoder/meter identity")
        if (not _number(obs.quality) or not 0 <= obs.quality <= 1
                or not _number(obs.risk) or not 0 <= obs.risk <= 1
                or not _number(obs.compute_units, positive=True)
                or obs.compute_units > trial.max_compute_units):
            raise CreditRejected("unmetered or infeasible physical observations")
        if not obs.observer_signature or not obs.meter_signature:
            raise CreditRejected("unsigned observer or meter")
        digest = obs.digest()
        if (not verifier(obs.observer_id, digest, obs.observer_signature)
                or not verifier(obs.meter_id, digest, obs.meter_signature)):
            raise CreditRejected("invalid independent outcome or meter signature")
        cell_set = frozenset(obs.active_cells)
        group = panel.setdefault(obs.episode_id, {})
        if cell_set in group:
            raise CreditRejected("duplicate coalition or selective panel substitution")
        net_ndu = (obs.quality - trial.resource_price * obs.compute_units
                   - trial.risk_price * obs.risk)
        if not isfinite(net_ndu) or abs(net_ndu) > trial.abs_ndu_bound:
            raise CreditRejected("net NDU beyond preregistered support")
        group[cell_set] = net_ndu
    credit_rows: list[tuple[float, ...]] = []
    deltas: list[float] = []
    maximum_fraction = 0.0
    for episode in sorted(roster):
        values = panel.get(episode, {})
        if set(values) != expected:
            raise CreditRejected("missing preregistered counterfactual coalition")
        delta = values[frozenset(trial.cells)] - values[frozenset()]
        phi = _shapley(values, trial.cells)
        if abs(fsum(phi) - delta) > 1e-9:
            raise CreditRejected("global utility / local Shapley conservation failed")
        credit_rows.append(phi)
        deltas.append(delta)
        pair = _pair_interaction(values, trial.cells)
        maximum_fraction = max(maximum_fraction, pair / max(abs(delta), 1e-12))
    n = len(credit_rows)
    means = tuple(fsum(row[i] for row in credit_rows)/n
                  for i in range(len(trial.cells)))
    # Each per-episode Shapley score is in [-2B, 2B].
    width = 4 * trial.abs_ndu_bound * sqrt(
        log(2 * len(trial.cells) / trial.alpha) / (2 * n)
    )
    lcbs = tuple(x - width for x in means)
    supported = maximum_fraction <= trial.max_pair_interaction_fraction
    return CreditVerdict(
        n, trial.cells, means, lcbs, fsum(deltas)/n, maximum_fraction,
        supported, supported and all(x > 0 for x in lcbs)
    )
