"""One declared NDU objective and an honest operational resource contract.

Bounded operations do not imply a bounded future physical CPU charge. These
contracts deliberately keep those two statements separate.
"""

from dataclasses import asdict, dataclass
import math
import resource

from ..unified_20261028.profile import NduProfile, digest


FEATURE_DIMENSION = 16
ACTIONS = ("keep", "swap")


def cpu_seconds():
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime


@dataclass(frozen=True)
class WorkBudget:
    max_emissions: int = 2
    max_bundle_bytes: int = 4194304
    max_public_bytes: int = 32768
    cpu_admission_seconds: float = 10.0
    native_kernels: int = 17

    def __post_init__(self):
        for name in ("max_emissions", "max_bundle_bytes", "max_public_bytes", "native_kernels"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError("Work capacities must be positive integers")
        if self.max_emissions not in (1, 2) or self.native_kernels != 17:
            raise ValueError("This original-owner continuation supports at most one fresh retry")
        if (isinstance(self.cpu_admission_seconds, bool)
                or not math.isfinite(self.cpu_admission_seconds) or self.cpu_admission_seconds <= 0):
            raise ValueError("CPU admission needs a positive finite threshold")

    def to_dict(self):
        return {**asdict(self), "cpu_threshold_is_a_future_support_bound": False,
                "cpu_overshoot": "fully charged; no new emission admitted after exhaustion",
                "failed_emission": "consumes its work slot and all incurred resources",
                "output_bytes": "writer rejects before an oversized write; partial files remain billed"}


@dataclass(frozen=True)
class Prices:
    cpu_second: float = .001
    native_kernel: float = .0001
    generator_call: float = .01
    delivery: float = .002
    refused_proposal: float = .005
    written_byte: float = 1e-9

    def __post_init__(self):
        if any(isinstance(v, bool) or not math.isfinite(v) or v < 0 for v in asdict(self).values()):
            raise ValueError("Prices must be finite and nonnegative")
        if self.cpu_second <= 0:
            raise ValueError("This complete physical-cost contract must charge measured CPU")


def continuation_contract(*, authority, emission, source_hashes, budget, prices):
    """Algorithm family is frozen here; actual fitted weights bind each policy."""
    return {"schema": "hepta.ndu.host-selected-continuation.v1",
            "authority": authority, "emission": emission, "implementation_sha256": source_hashes,
            "work_budget": budget.to_dict(), "prices": asdict(prices),
            "actions": {"keep": "stop with actual current four-media result",
                        "swap": "one fresh full-bundle sample, subject to unchanged owner gates"},
            "initial": "one actual full-bundle emission before the semantic decision boundary",
            "actor": "fitted conditional complete-return moments; choose the smaller moment; ties keep",
            "actor_context": "arrived transport feedback, unchanged owner abstention, remaining slots, 16 public features",
            "native_role": "original permission/expiry gates only; legacy readout does not select host action",
            "native_authority": "DENY_ALL; scoped research generation authorization only",
            "moment_target": "actual terminal score minus ALL incurred episode costs inside the exponential",
            "stop": "after original-owner decision and any admitted fresh continuation; no unscored future work",
            "cpu_accounting": "entry before prepare through terminal readback/scoring and binding checks; self plus reaped children",
            "unbounded_physical_cpu": True, "time_discount": 1.0,
            "no_silent_omission": "observed failures/refusals retain their costs; unhandled faults invalidate the study",
            "reporting_boundary": "final receipt encoding/checkpoint and optimizer are reported separately"}


def make_profile(*, observer, continuation, gamma=2.0, aggregation="population"):
    objective = {"schema": "hepta.ndu.complete-host-objective.v1",
                 "terminal_observer": observer, "prices": continuation["prices"],
                 "failure_utility": 0.0, "stopping": continuation["stop"],
                 "cost_scope": continuation["cpu_accounting"],
                 "actual_cpu_overshoot_is_charged": True}
    profile = NduProfile(digest(objective), digest(observer), digest(continuation),
                         gamma=gamma, aggregation=aggregation, utility_bounds=(0.0, 1.0),
                         required_modalities=("text", "audio", "image", "video"))
    return profile, objective


def work_charge_upper(budget, prices):
    """Only bounded discrete work, explicitly excluding positive-price CPU."""
    return (budget.native_kernels * prices.native_kernel
            + budget.max_emissions * (prices.generator_call + prices.delivery
                                      + budget.max_bundle_bytes * prices.written_byte)
            + 2 * prices.refused_proposal)


def support_status(budget, prices):
    return {"bounded_discrete_work_charge": work_charge_upper(budget, prices),
            "finite_total_physical_cost_support_proved": False,
            "net_return_lower_bound": None,
            "reason": "a post-stage CPU admission threshold is not a hard limit on complete future CPU",
            "clipped_charges": False, "ndu_moment_certificate_eligible": False}
