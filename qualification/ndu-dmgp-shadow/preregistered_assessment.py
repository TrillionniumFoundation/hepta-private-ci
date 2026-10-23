"""Read-only A0-A5 paired diagnostics; never grants real-evidence authority.

Hoeffding is meaningful only with externally established independent clusters.
Source hashes and caller-reported measurements do not establish that premise.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite, log, sqrt
from statistics import mean

from reference import Freeze, Outcome, digest, require

ARMS = ("A0", "A1", "A2", "A3", "A4", "A5")
BASELINES = ARMS[:-1]


@dataclass(frozen=True)
class PairedProtocol:
    objective: str
    generation: int
    critic_digest: str
    max_total_us: int
    cost_per_us: float
    familywise_alpha: float = 0.05
    min_future_episodes: int = 32

    def check(self, freeze: Freeze) -> None:
        freeze.validate()
        require(self.objective == freeze.objective
                and self.generation == freeze.generation
                and self.critic_digest == freeze.critic_digest,
                "unfrozen assessment objective, generation or critic")
        require(type(self.max_total_us) is int and 0 < self.max_total_us < 2**64
                and type(self.min_future_episodes) is int
                and 32 <= self.min_future_episodes <= 4096,
                "unregistered work or future support bound")
        require(type(self.cost_per_us) in (int, float)
                and isfinite(self.cost_per_us) and self.cost_per_us >= 0
                and isfinite(4.0 + 2.0 * self.cost_per_us * self.max_total_us),
                "invalid resource price")
        require(type(self.familywise_alpha) in (int, float)
                and isfinite(self.familywise_alpha)
                and 0 < self.familywise_alpha <= .05,
                "invalid preregistered familywise error budget")


def assess_paired_a0_a5(
    rows: tuple[Outcome, ...], freeze: Freeze, protocol: PairedProtocol
) -> dict[str, object]:
    """Matched NDU-minus-cost arithmetic; never an independent signed review."""
    protocol.check(freeze)
    require(len(rows) >= len(ARMS) * protocol.min_future_episodes
            and len(rows) <= len(ARMS) * 4096,
            "insufficient or unbounded A0-A5 trial collection")
    groups: dict[str, dict[str, Outcome]] = {}
    work_keys: set[str] = set()
    for row in rows:
        row.validate(freeze)
        require(row.split == "future", "leaked training or retention observations")
        require(row.arm in ARMS and row.work_key not in work_keys,
                "unexpected arm or duplicate physical work")
        work_keys.add(row.work_key)
        require(row.total_us <= protocol.max_total_us,
                "trial exceeds preregistered compute ceiling")
        cohort = groups.setdefault(row.episode, {})
        require(row.arm not in cohort, "duplicate arm in episode")
        cohort[row.arm] = row

    require(len(groups) >= protocol.min_future_episodes,
            "insufficient future paired clusters")
    source_ids = set()
    for arms in groups.values():
        require(set(arms) == set(ARMS), "incomplete paired A0-A5 cohort")
        source = {r.source_digest for r in arms.values()}
        require(len(source) == 1, "unmatched paired input")
        source_id = next(iter(source))
        require(source_id not in source_ids,
                "reused source across episodes: pseudoreplicated future cohort")
        source_ids.add(source_id)

    n = len(groups)
    # Observed utility [-1,1]; cost in [0,price*max_us].
    # Pair difference is in [-2-price*max_us,2+price*max_us].
    span = 4.0 + 2.0 * protocol.cost_per_us * protocol.max_total_us
    radius = span * sqrt(log(len(BASELINES) / protocol.familywise_alpha)
                         / (2.0 * n))
    paired = {}
    for base in BASELINES:
        delta = []
        for group in groups.values():
            c, b = group["A5"], group[base]
            delta.append(c.observed_utility - b.observed_utility
                         - protocol.cost_per_us * (c.total_us - b.total_us))
        mu = mean(delta)
        paired[base] = {"mean_net_delta": mu,
                        "assumption_based_lcb": mu - radius,
                        "lcb_positive": mu - radius > 0}
    return {
        "schema": "hepta.ndu-dmgp.shadow-paired-a0-a5.v1",
        "frozen_protocol_digest": digest(asdict(protocol)),
        "future_paired_episode_count": n,
        "familywise_alpha": protocol.familywise_alpha,
        "hoeffding_radius": radius,
        "paired_net_advantage": paired,
        "all_lcb_positive_given_iid": all(x["lcb_positive"] for x in paired.values()),
        "external_independence_authenticated": False,
        "external_observation_signed": False,
        "physical_decoder_meter_attested": False,
        "production_blockers_closed": False,
        "no_promotion_authority": True,
    }
