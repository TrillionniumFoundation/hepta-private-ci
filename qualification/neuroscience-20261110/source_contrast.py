"""Frozen source-level routing analysis; declarations never authenticate owners."""
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math

from study import ARMS, ContractError, TrialRow, paired_evidence


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()).hexdigest()


def valid_hash(value):
    return isinstance(value, str) and len(value) == 64 and all(
        ch in "0123456789abcdef" for ch in value)


def bounded(values, limit):
    result = []
    for value in values:
        if len(result) == limit:
            raise ContractError("source study input exceeds declared limit")
        result.append(value)
    return result


@dataclass(frozen=True)
class PlannedBlock:
    episode_id: str
    seed: int
    family: str
    workload_digest: str
    source_cluster_digest: str
    ability_digest: str
    evaluator_digest: str
    opportunity: tuple[int, int, int, int]  # Feedback bits, queries, updates, compute us.


@dataclass(frozen=True)
class SourcePlan:
    blocks: tuple[PlannedBlock, ...]
    groups: tuple[str, ...]
    shuffled_route: tuple[int, ...]
    clock_domain: str
    boot_id: str
    training_cutoff_us: int


@dataclass(frozen=True)
class Information:
    message_id: str
    source_digest: str
    available_us: int
    payload: bytes  # Original, unrouted bytes, not a caller-supplied digest.


@dataclass(frozen=True)
class Observation:
    episode_id: str
    seed: int
    family: str
    arm: str
    status: str  # KNOWN, UNKNOWN, UNAVAILABLE, FAILED or NOT_RUN.
    trial: TrialRow | None
    information: tuple[Information, ...]
    route: tuple[int, ...]
    clock_domain: str
    boot_id: str


def source_contrast(plan: SourcePlan, observations) -> dict:
    """Validate the frozen denominator and compare equal-weight source means.

    Seed repetitions never manufacture independent task sources. Source grouping
    and availability are declarations; external provenance remains unverified.
    Any missing primary outcome withholds statistics for the entire planned set.
    """
    blocks = bounded(plan.blocks, 10_000)
    n = len(plan.groups)
    if (not blocks or not 2 <= n <= 64 or len(set(plan.groups)) != n
            or any(not isinstance(g, str) or not g for g in plan.groups)
            or len(plan.shuffled_route) != n
            or any(type(i) is not int for i in plan.shuffled_route)
            or sorted(plan.shuffled_route) != list(range(n))
            or any(i == j for i, j in enumerate(plan.shuffled_route))
            or not plan.clock_domain or not plan.boot_id
            or type(plan.training_cutoff_us) is not int or plan.training_cutoff_us < 0):
        raise ContractError("invalid frozen plan or routing permutation")
    roster, source_by_workload = {}, {}
    for b in blocks:
        key = (b.episode_id, b.seed, b.family)
        if (not b.episode_id or not b.family or type(b.seed) is not int or b.seed < 0
                or key in roster or any(not valid_hash(v) for v in
                    (b.workload_digest, b.source_cluster_digest, b.ability_digest, b.evaluator_digest))
                or len(b.opportunity) != 4
                or any(type(v) is not int or v < 0 for v in b.opportunity)):
            raise ContractError("invalid or duplicate planned block")
        if source_by_workload.setdefault(b.workload_digest, b.source_cluster_digest) != b.source_cluster_digest:
            raise ContractError("one workload cannot be split into source aliases")
        roster[key] = b
    rows, frozen_info, counts = {}, {}, dict.fromkeys(
        ("KNOWN", "UNKNOWN", "UNAVAILABLE", "FAILED", "NOT_RUN", "MISSING"), 0)
    for obs in bounded(observations, 40_000):
        key = (obs.episode_id, obs.seed, obs.family)
        fullkey = (*key, obs.arm)
        if (key not in roster or obs.arm not in ARMS or fullkey in rows
                or obs.status not in counts or obs.status == "MISSING"
                or (obs.clock_domain, obs.boot_id) != (plan.clock_domain, plan.boot_id)):
            raise ContractError("unplanned, duplicated or cross-clock observation")
        expected_route = (plan.shuffled_route if obs.arm == "shuffled" else
                          tuple(range(n)) if obs.arm == "routed" else ())
        if obs.route != expected_route:
            raise ContractError("route differs from frozen arm assignment")
        packets, total_bytes = {}, 0
        for packet in bounded(obs.information, 4096):
            if (type(packet) is not Information or type(packet.available_us) is not int
                    or packet.available_us < 0):
                raise ContractError("unknown information availability")
            if packet.available_us > plan.training_cutoff_us:
                continue  # Unavailable payload cannot alter a frozen candidate.
            if (not valid_hash(packet.message_id) or not valid_hash(packet.source_digest)
                    or packet.message_id in packets or type(packet.payload) is not bytes):
                raise ContractError("invalid or duplicate visible information")
            total_bytes += len(packet.payload)
            if total_bytes > 1_048_576:
                raise ContractError("visible information byte budget exceeded")
            packets[packet.message_id] = (packet.source_digest, packet.available_us,
                                          sha256(packet.payload).hexdigest())
        frozen_info[fullkey] = tuple(sorted(packets.items()))
        if obs.status == "KNOWN":
            t = obs.trial
            b = roster[key]
            if (type(t) is not TrialRow or (t.episode_id, t.seed, t.family, t.arm) != fullkey
                    or (t.workload_digest, t.ability_digest, t.evaluator_digest) !=
                    (b.workload_digest, b.ability_digest, b.evaluator_digest)
                    or (t.feedback_budget_bits, t.query_budget, t.training_budget,
                        t.compute_budget_us) != b.opportunity):
                raise ContractError("measured outcome identity differs from plan")
        elif obs.trial is not None:
            raise ContractError("unobserved outcome must not contain imputed metrics")
        rows[fullkey] = obs
        counts[obs.status] += 1
    counts["MISSING"] = len(roster) * len(ARMS) - len(rows)
    for key in roster:
        observed = [frozen_info[(*key, arm)] for arm in ARMS if (*key, arm) in rows]
        if observed and any(info != observed[0] for info in observed):
            raise ContractError("paired arms received different original information")
    canonical = [{"key": key, "status": rows[key].status,
                  "trial": asdict(rows[key].trial) if rows[key].trial else None,
                  "information": frozen_info[key], "route": rows[key].route}
                 for key in sorted(rows)]
    plan_value = {**asdict(plan), "blocks": [asdict(roster[k]) for k in sorted(roster)]}
    result = {
        "schema": "hepta.neuroscience.source-contrast.v1",
        "plan_digest": digest(plan_value),
        "input_digest": digest({"plan": plan_value, "observations": canonical}),
        "planned_rows": len(roster) * len(ARMS), "status_counts": counts,
        "training_seeds": len({b.seed for b in blocks}),
        "declared_source_clusters": len(set(source_by_workload.values())),
        "statistics": None, "confirmatory_p": None,
        "inference_limit": "source grouping, availability and randomization are not attested",
        "qualification": "INCOMPLETE", "authority": "DENY_ALL",
    }
    if counts["KNOWN"] != result["planned_rows"]:
        return result
    # Retain all inherited identity, family roster, evaluator and budget checks.
    legacy = paired_evidence([rows[k].trial for k in sorted(rows)])
    differences = {}
    for key in sorted(roster):
        a, b = (rows[(*key, arm)].trial for arm in ("routed", "shuffled"))
        delta = ((a.gross_value - a.full_cost) - (b.gross_value - b.full_cost),
                 a.full_cost - b.full_cost,
                 None if legacy["mean_retention_difference"] is None else
                 a.retention_value - b.retention_value)
        differences.setdefault(roster[key].source_cluster_digest, []).append(delta)
    means = {source: tuple(None if group[0][j] is None else
                          math.fsum(d[j] for d in group) / len(group) for j in range(3))
             for source, group in sorted(differences.items())}
    overall = [None if next(iter(means.values()))[j] is None else
               math.fsum(x[j] for x in means.values()) / len(means) for j in range(3)]
    if any(x is not None and not math.isfinite(x) for x in overall):
        raise ContractError("non-finite aggregate difference")
    result.update(qualification="DESCRIPTIVE_ONLY", statistics={
        "comparison": "routed minus shuffled; equal weight per declared source",
        "source_differences": means, "mean_net_difference": overall[0],
        "mean_cost_difference": overall[1], "mean_retention_difference": overall[2]})
    return result


def learning_progress(points, *, target):
    """First observed attainment interval; nonattainment stays right-censored.

    Points are (cumulative independent source exposures, elapsed_us, score).
    Repeated seeds and optimizer calls are not independent source exposures.
    """
    points = bounded(points, 10_000)
    if type(target) not in (int, float) or not math.isfinite(target) or not points:
        raise ContractError("invalid learning target or empty curve")
    previous = None
    attainment = None
    for exposures, elapsed, score in points:
        if (type(exposures) is not int or exposures < 0 or type(elapsed) is not int
                or elapsed < 0 or type(score) not in (int, float) or not math.isfinite(score)
                or (previous and (exposures < previous[0] or elapsed <= previous[1]))):
            raise ContractError("invalid or regressing learning curve")
        if attainment is None and score >= target:
            attainment = {"censoring": "left" if previous is None else "interval",
                          "lower": previous[:2] if previous else None,
                          "upper": (exposures, elapsed)}
        previous = (exposures, elapsed, score)
    return attainment or {"censoring": "right", "lower": previous[:2], "upper": None}
