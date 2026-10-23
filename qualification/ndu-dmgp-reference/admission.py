"""Shadow-only attested-evidence and matched A0-A5 analysis gate.

This is a research adapter, NOT a trusted host/verifier or promotion authority.
Only a deployment-owned, external verifier could supply trusted signatures.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from hashlib import sha256
import json
import math
from collections import defaultdict
from collections.abc import Callable, Sequence

from reference import ARMS, Covariance, GateRejected, Objective, paired_covariance

Verifier = Callable[[str, str, str], bool]


def _valid_digest(value: str) -> bool:
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)


@dataclass(frozen=True)
class RunEvidence:
    run_id: str
    episode: str
    arm: str
    split: str
    stratum: str
    objective_digest: str
    generation: int
    input_digest: str
    encoder_digest: str
    decoder_registry_digest: str
    selected_snapshot_digest: str
    critic_digest: str
    actor_id: str
    observer_id: str
    meter_id: str
    observed_at: int
    quality: float
    compute_units: float
    risk: float
    wall_us: float
    encoder_us: float
    decoder_us: float
    controller_us: float
    peak_rss_bytes: int
    peak_vram_bytes: int
    energy_mj: float
    required_modalities: tuple[str, ...]
    emitted_modalities: tuple[str, ...]
    consistency_evidence_digest: str
    evidence_kind: str
    observer_signature: str
    meter_signature: str


def evidence_digest(record: RunEvidence) -> str:
    """The entire semantically relevant receipt, excluding detached signatures."""
    body = {f.name: getattr(record, f.name) for f in fields(record)
            if f.name not in ("observer_signature", "meter_signature")}
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")
    return sha256(b"hepta.ndu-dmgp.shadow-run-evidence.v1\x00" + blob).hexdigest()


@dataclass(frozen=True)
class AdmittedRun:
    evidence: RunEvidence
    net_ndu: float
    # Structurally verified through a caller-supplied callback; NOT real trust.
    production_authority: bool = False


def admit_run(record: RunEvidence, objective: Objective,
              verifier: Verifier | None = None) -> AdmittedRun:
    """Fail-closed *shadow* validation; production trust roots are not available here."""
    if verifier is None:
        raise GateRejected("external observer and meter verifier unavailable")
    if (not record.run_id or not record.episode or not record.stratum
            or record.arm not in ARMS or record.split not in ("train", "future", "retention")
            or record.generation != objective.generation
            or record.objective_digest != objective.digest
            or not record.actor_id or not record.observer_id or not record.meter_id
            or len({record.actor_id, record.observer_id, record.meter_id}) != 3
            or record.observed_at <= 0
            or record.evidence_kind != "independent_observation"):
        raise GateRejected("unmatched objective, source, scope or independent identities")
    if (type(record.generation) is not int or type(record.observed_at) is not int
            or type(record.peak_rss_bytes) is not int
            or type(record.peak_vram_bytes) is not int):
        raise GateRejected("wrong typed immutable identity or resource measurement")
    for value in (record.input_digest, record.encoder_digest,
                  record.decoder_registry_digest, record.selected_snapshot_digest,
                  record.critic_digest, record.consistency_evidence_digest):
        if not _valid_digest(value):
            raise GateRejected("missing immutable artifact or consistency evidence")
    if (not record.required_modalities
            or len(set(record.required_modalities)) != len(record.required_modalities)
            or len(set(record.emitted_modalities)) != len(record.emitted_modalities)
            or not set(record.required_modalities).issubset(objective.required_modalities)
            or not set(record.emitted_modalities).issubset(objective.allowed_modalities)
            or not set(record.required_modalities).issubset(record.emitted_modalities)
            or set(record.required_modalities) != set(objective.required_modalities)):
        raise GateRejected("illegal or incomplete multimodal output")
    for name in ("quality", "compute_units", "risk", "wall_us", "encoder_us",
                 "decoder_us", "controller_us", "energy_mj"):
        value = getattr(record, name)
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0):
            raise GateRejected("nonfinite or negative real metering and quality")
    if not 0 <= record.quality <= 1 or not 0 <= record.risk <= 1:
        raise GateRejected("quality/risk normalization unqualified")
    if (record.compute_units <= 0
            or record.compute_units > objective.budget_units
            or record.risk > objective.max_action_risk
            or record.wall_us <= 0 or record.decoder_us <= 0
            or record.energy_mj <= 0
            or record.wall_us < max(record.encoder_us, record.decoder_us,
                                    record.controller_us)
            or record.peak_rss_bytes <= 0 or record.peak_vram_bytes < 0
):
        raise GateRejected("unqualified host resource envelope")
    if not record.observer_signature or not record.meter_signature:
        raise GateRejected("missing independent signatures")
    digest = evidence_digest(record)
    if (not verifier(record.observer_id, digest, record.observer_signature)
            or not verifier(record.meter_id, digest, record.meter_signature)):
        raise GateRejected("independent observer or host meter signature rejected")
    return AdmittedRun(record, record.quality
                       - objective.resource_price * record.compute_units
                       - objective.risk_price * record.risk)


@dataclass(frozen=True)
class PortfolioComparison:
    episodes: int
    simultaneous_lcb: tuple[tuple[str, float], ...]
    max_observed_controller_fraction: float
    qualifies_statistically: bool
    # Even a statistical result cannot authorize deployment in this module.
    production_blockers_closed: bool = False
    production_authority: bool = False


def _matched(records: Sequence[AdmittedRun], *, split: str,
             arms: Sequence[str]) -> dict[str, dict[str, AdmittedRun]]:
    if len(set(arms)) != len(arms) or not arms or any(arm not in ARMS for arm in arms):
        raise GateRejected("invalid preregistered comparison arms")
    paired: dict[str, dict[str, AdmittedRun]] = defaultdict(dict)
    seen_runs: set[str] = set()
    for record in records:
        e = record.evidence
        if record.production_authority or e.split != split or e.arm not in arms:
            raise GateRejected("wrong split, arm or unauthorized evidence")
        if e.run_id in seen_runs or e.arm in paired[e.episode]:
            raise GateRejected("duplicate run or episode-arm evidence")
        seen_runs.add(e.run_id)
        paired[e.episode][e.arm] = record
    if not paired:
        raise GateRejected("no observed episodes")
    manifests: set[tuple[object, ...]] = set()
    for episode, group in paired.items():
        if set(group) != set(arms):
            raise GateRejected(f"unpaired, missing or selectively dropped arm: {episode}")
        # Same actual task/context and fixed selected model across all arms.
        frozen = {(r.evidence.objective_digest, r.evidence.generation,
                   r.evidence.input_digest, r.evidence.encoder_digest,
                   r.evidence.decoder_registry_digest,
                   r.evidence.selected_snapshot_digest,
                   r.evidence.critic_digest, r.evidence.stratum, r.evidence.required_modalities)
                  for r in group.values()}
        if len(frozen) != 1:
            raise GateRejected("unmatched task, encoder, snapshot or modality contract")
        obj, gen, _input, encoder, decoders, selected, critic, stratum, required = next(iter(frozen))
        manifests.add((obj, gen, encoder, decoders, selected, critic, stratum, required))
    if len(manifests) != 1:
        raise GateRejected("unsupported cross-condition pooling")
    return paired


def compare_a0_a5(
    records: Sequence[AdmittedRun], *,
    ndu_abs_bound: float, alpha: float = 0.05,
    minimum_gain: float = 0., max_controller_fraction: float = .1,
) -> PortfolioComparison:
    """Paired, Bonferroni-Hoeffding one-sided LCBs against all A0..A4.

    Requires independent episodes and preregistered bounds. Never a CI/release gate.
    """
    if (not all(math.isfinite(x) for x in (ndu_abs_bound, alpha, minimum_gain,
                                           max_controller_fraction))
            or ndu_abs_bound <= 0 or not 0 < alpha < 1
            or minimum_gain < 0 or not 0 <= max_controller_fraction <= 1):
        raise GateRejected("invalid preregistered statistical profile")
    paired = _matched(records, split="future", arms=ARMS)
    n = len(paired)
    if n < 32:
        raise GateRejected("insufficient independent future episode support")
    width = 4 * ndu_abs_bound * math.sqrt(math.log((len(ARMS)-1)/alpha)/(2*n))
    comparisons: list[tuple[str, float]] = []
    observed_overhead = 0.
    for group in paired.values():
        for run in group.values():
            if abs(run.net_ndu) > ndu_abs_bound:
                raise GateRejected("NDU outcome exceeds predeclared support")
            observed_overhead = max(observed_overhead,
                                    run.evidence.controller_us / run.evidence.wall_us)
    for arm in ARMS[:-1]:
        diffs = [group["A5"].net_ndu - group[arm].net_ndu
                 for group in paired.values()]
        comparisons.append((arm, math.fsum(diffs)/n - width))
    passes = (all(lcb > minimum_gain for _, lcb in comparisons)
              and observed_overhead <= max_controller_fraction)
    return PortfolioComparison(n, tuple(comparisons), observed_overhead, passes)


def conditional_covariance(
    records: Sequence[AdmittedRun], experts: Sequence[str], *,
    train_cutoff: int, stratum: str, rank: int | None = None,
) -> Covariance:
    """Risk covariance fitted only from prior paired train outcomes, never future."""
    if train_cutoff <= 0 or not stratum or len(experts) < 2:
        raise GateRejected("invalid conditional covariance freeze")
    paired = _matched(records, split="train", arms=experts)
    if any(r.evidence.observed_at >= train_cutoff or
           r.evidence.stratum != stratum
           for row in paired.values() for r in row.values()):
        raise GateRejected("future leakage or cross-stratum covariance")
    data = {episode: {arm: row[arm].net_ndu for arm in experts}
            for episode, row in paired.items()}
    return paired_covariance(data, experts, rank=rank)
