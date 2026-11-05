"""Trusted, prospective paired evaluator; never accepts a client approval flag.

This is a research admission predicate, not an authentication or sandbox boundary.
The host supplies frozen cases, runners, resource receipts and prices. Cluster
independence and measurement integrity remain explicit experiment assumptions.
"""

from dataclasses import dataclass, replace
import hashlib
import json
import math

from cohort import INFORMATION, check_arms, check_registration
from isolated_runner import run_arm


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class Case:
    key: str
    cluster: str
    stratum: str
    query: str
    payload: object
    expected: object


@dataclass(frozen=True)
class Run:
    bundle: str
    memory: str
    training_inputs: str
    executor: str
    budget: str
    predict: object
    encoder: str = ""
    decoder: str = ""
    tool_permissions: str = ""


@dataclass(frozen=True)
class Protocol:
    identity: str
    prospective: bool
    expected_reads: int
    alpha: float
    comparisons: int
    retention_margin: float
    minimum_clusters: int
    deadline_seconds: float
    required_strata: tuple
    prices: tuple
    limits: tuple
    planned_looks: int = 1
    cost_model: str = "resources"
    zero_cost_reasons: tuple = ()
    workload_digest: str = ""
    worker_cpu_seconds: int = 30
    worker_wall_seconds: float = 60.0
    worker_address_space_bytes: int = 1073741824


CPU_PHASES = ("acquire_cpu_s", "train_cpu_s", "search_cpu_s", "update_cpu_s",
              "verify_cpu_s", "serve_cpu_s", "restore_cpu_s", "migration_cpu_s")
COSTS = CPU_PHASES + ("retained_byte_seconds", "network_bytes", "energy_joules",
                     "billed_usd", "peak_rss_bytes", "p99_seconds")


def budget_digest(protocol):
    """Bind actual common caps, including each arm's cold worker envelope."""
    return digest({"schema": "hepta.memory.resource-budget.v1",
                   "limits": sorted(protocol.limits),
                   "deadline_seconds": protocol.deadline_seconds,
                   "worker_cpu_seconds": protocol.worker_cpu_seconds,
                   "worker_wall_seconds": protocol.worker_wall_seconds,
                   "worker_address_space_bytes": protocol.worker_address_space_bytes})


def paired_bound(differences, alpha):
    """One-sided Hoeffding bound for independent cluster means in [-1, 1]."""
    if not differences:
        raise ValueError("no independent units")
    mean = sum(differences) / len(differences)
    return mean, max(-1.0, mean - math.sqrt(2 * math.log(1 / alpha) / len(differences)))


class MatchedEvaluator:
    """Execute the same public inputs and executor; labels stay in the evaluator.

    Costs cover a declared deployment horizon, including failed searches and
    retained versions. Unknowns reject full-cost admission even at zero price.
    Each arm starts in a separate, bounded interpreter and private working
    directory. That isolates Python state, not external services or hostile code.
    Worker measurements are lower bounds for the supplied full lifecycle ledger;
    they cannot fill unknown energy, network, training or retained-version costs.
    """

    def __init__(self, cases, executor_factory, protocol, *, registration=None):
        # A frozen dataclass alone does not freeze nested payload/expected objects.
        self._cases_wire = json.dumps([vars(x) for x in cases], sort_keys=True, allow_nan=False)
        cases = tuple(Case(**row) for row in json.loads(self._cases_wire))
        self.executor_factory = executor_factory
        self.protocol = replace(protocol, required_strata=tuple(protocol.required_strata),
                                prices=tuple(tuple(x) for x in protocol.prices),
                                limits=tuple(tuple(x) for x in protocol.limits),
                                zero_cost_reasons=tuple(tuple(x) for x in protocol.zero_cost_reasons))
        self._frozen_protocol = self.protocol
        self._frozen_protocol_digest = digest(vars(self.protocol))
        self.case_count = len(cases)
        p = self.protocol
        if (not cases or len({x.key for x in cases}) != len(cases)
                or any(not x.cluster or not x.stratum for x in cases)
                or type(p.expected_reads) is not int or p.expected_reads <= 0
                or type(p.comparisons) is not int or p.comparisons <= 0
                or type(p.planned_looks) is not int or p.planned_looks <= 0
                or type(p.minimum_clusters) is not int or p.minimum_clusters < 2
                or not 0 < p.alpha < 1 or not 0 <= p.retention_margin < 1
                or not math.isfinite(p.deadline_seconds) or p.deadline_seconds <= 0
                or type(p.worker_cpu_seconds) is not int or p.worker_cpu_seconds <= 0
                or type(p.worker_address_space_bytes) is not int or p.worker_address_space_bytes < 16 * 1024 * 1024
                or type(p.worker_wall_seconds) not in (int, float)
                or not math.isfinite(p.worker_wall_seconds) or p.worker_wall_seconds <= 0
                or not p.identity or not p.required_strata
                or len(set(p.required_strata)) != len(p.required_strata)):
            raise ValueError("invalid frozen experiment")
        prices, limits, zero_reasons = dict(p.prices), dict(p.limits), dict(p.zero_cost_reasons)
        if (len(prices) != len(p.prices) or len(limits) != len(p.limits)
                or len(zero_reasons) != len(p.zero_cost_reasons)
                or not set(prices) <= set(COSTS) or not set(limits) <= set(COSTS)
                or not set(zero_reasons) <= set(COSTS)
                or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0
                       for v in list(prices.values()) + list(limits.values()))
                or any(not isinstance(v, str) or not v.strip() for v in zero_reasons.values())
                or p.cost_model not in ("resources", "bill")):
            raise ValueError("invalid resource prices or common limits")
        positive = {key for key, value in prices.items() if value > 0}
        if positive & set(zero_reasons):
            raise ValueError("a priced resource cannot also have a zero-price reason")
        if ((p.cost_model == "resources" and prices.get("billed_usd", 0))
                or (p.cost_model == "bill" and any(prices.get(k, 0) for k in COSTS
                                                   if k not in ("billed_usd", "p99_seconds")))):
            raise ValueError("use bills or resource pricing, not both")
        self._economic_reasons = []
        if not positive:
            self._economic_reasons.append("empty_cost_model")
        missing_treatment = sorted(set(COSTS) - positive - set(zero_reasons))
        if missing_treatment:
            self._economic_reasons.append("missing_cost_treatment:" + ",".join(missing_treatment))
        if p.cost_model == "bill" and not prices.get("billed_usd", 0):
            self._economic_reasons.append("bill_cost_model_missing_bill_price")
        self.budget_digest = budget_digest(p)
        self.data_digest = digest(json.loads(self._cases_wire))
        self._registration_wire = json.dumps(registration, sort_keys=True, allow_nan=False)
        self._registration_reasons = check_registration(json.loads(self._registration_wire),
                                    cases, p, self.data_digest, digest(vars(p)))

    def cost_binding(self, model):
        """Expected ledger identity; this does not manufacture resource evidence."""
        return {"bundle": model.bundle, "protocol": self._frozen_protocol.identity,
                "protocol_settings": self._frozen_protocol_digest,
                "horizon_reads": self._frozen_protocol.expected_reads,
                "data": self.data_digest,
                "cohort_registration": digest(json.loads(self._registration_wire)),
                **{field: getattr(model, field) for field in INFORMATION},
                "budget": self.budget_digest, "workload": self._frozen_protocol.workload_digest}

    def evaluate(self, candidate, incumbent, candidate_cost, incumbent_cost, *, manifest):
        p, quality_reasons = self._frozen_protocol, list(self._registration_reasons)
        resource_reasons, economic_reasons = [], list(self._economic_reasons)
        try:
            observed_settings = digest(vars(self.protocol))
        except (TypeError, ValueError):
            observed_settings = None
        if observed_settings != self._frozen_protocol_digest:
            quality_reasons.append("protocol_changed_after_freeze")
        registration = json.loads(self._registration_wire)
        quality_reasons.extend(check_arms(registration, candidate, incumbent))
        # Freeze caller-owned nested receipts before invoking any model callbacks.
        frozen = json.loads(json.dumps({"candidate_cost": candidate_cost,
                                       "incumbent_cost": incumbent_cost, "manifest": manifest},
                                      allow_nan=False))
        candidate_cost, incumbent_cost, manifest = (frozen["candidate_cost"],
                                                    frozen["incumbent_cost"], frozen["manifest"])
        if p.prospective is not True:
            quality_reasons.append("retrospective_evidence_cannot_authorize_growth")
        if candidate.bundle == incumbent.bundle:
            quality_reasons.append("candidate_equals_incumbent")
        for field in INFORMATION:
            if not getattr(candidate, field) or getattr(candidate, field) != getattr(incumbent, field):
                quality_reasons.append("unmatched_" + field)
        # The complete new bundle identity must be supplied by the trusted loader.
        if manifest.get("bundle") != candidate.bundle or manifest.get("memory") != candidate.memory:
            quality_reasons.append("candidate_manifest_mismatch")
        if not p.limits:
            resource_reasons.append("missing_common_resource_caps")
        if (not isinstance(p.workload_digest, str) or len(p.workload_digest) != 64
                or any(c not in "0123456789abcdef" for c in p.workload_digest)):
            resource_reasons.append("missing_or_invalid_workload_identity")
        costs = []
        for label, model, ledger in (("candidate", candidate, candidate_cost),
                                     ("incumbent", incumbent, incumbent_cost)):
            if model.budget != self.budget_digest:
                resource_reasons.append(label + "_budget_identity_mismatch")
            mismatch = [key for key, value in self.cost_binding(model).items() if ledger.get(key) != value]
            if mismatch or ledger.get("all_searches_and_failures_included") is not True:
                resource_reasons.append(label + "_unbound_cost_receipt")
                resource_reasons.extend(label + "_cost_identity_mismatch:" + key for key in mismatch)
            values = ledger.get("resources", {})
            missing = [k for k in COSTS if type(values.get(k)) not in (int, float)
                       or not math.isfinite(values[k]) or values[k] < 0]
            if missing:
                resource_reasons.append(label + "_unmeasured_or_invalid:" + ",".join(missing))
            for key, limit in p.limits:
                value = values.get(key)
                if type(value) in (int, float) and math.isfinite(value) and value > limit:
                    resource_reasons.append(label + "_budget_exceeded:" + key)
            costs.append(values)
        runs = [run_arm(self._cases_wire, model, self.executor_factory, p.deadline_seconds,
                        cpu_seconds=p.worker_cpu_seconds, wall_seconds=p.worker_wall_seconds,
                        address_space_bytes=p.worker_address_space_bytes)
                for model in (candidate, incumbent)]
        left, right = (run[0] for run in runs)
        for label, values, (_, measured) in zip(("candidate", "incumbent"), costs, runs, strict=True):
            if measured["status"] != "completed":
                resource_reasons.append(label + "_worker_incomplete:" + measured["status"])
            for key, measured_key in (("serve_cpu_s", "cpu_seconds"), ("peak_rss_bytes", "peak_rss_bytes")):
                value, actual = values.get(key), measured.get(measured_key)
                if type(actual) not in (int, float) or not math.isfinite(actual) or actual < 0:
                    resource_reasons.append(label + "_worker_unmeasured:" + measured_key)
                elif type(value) in (int, float) and math.isfinite(value) and value < actual:
                    resource_reasons.append(label + "_cost_understates_worker:" + key)
        groups, by_stratum = {}, {}
        for a, b in zip(left, right, strict=True):
            value = int(a["correct"]) - int(b["correct"])
            groups.setdefault(a["cluster"], []).append(value)
            by_stratum.setdefault(a["stratum"], {}).setdefault(a["cluster"], []).append(value)
        alpha = p.alpha / (p.comparisons * p.planned_looks * (1 + len(p.required_strata)))
        averages = [sum(v) / len(v) for v in groups.values()]
        mean, lower = paired_bound(averages, alpha)
        if len(groups) < p.minimum_clusters:
            quality_reasons.append("insufficient_independent_clusters")
        retention = {}
        for stratum in p.required_strata:
            units = by_stratum.get(stratum, {})
            if len(units) < p.minimum_clusters:
                quality_reasons.append("missing_or_small_stratum:" + stratum)
            if units:
                value, bound = paired_bound([sum(v) / len(v) for v in units.values()], alpha)
                retention[stratum] = {"mean": value, "lower": bound, "clusters": len(units)}
                if bound < -p.retention_margin:
                    quality_reasons.append("retention_not_established:" + stratum)
        complete = all(all(type(cost.get(k)) in (int, float) and math.isfinite(cost[k])
                           and cost[k] >= 0 for k in COSTS) for cost in costs)
        extra_cost = None
        if complete and not economic_reasons:
            try:
                extra_cost = math.fsum(price * (costs[0][key] - costs[1][key])
                                       for key, price in p.prices) / p.expected_reads
                if not math.isfinite(extra_cost):
                    raise ValueError("nonfinite cost result")
            except (OverflowError, ValueError):
                extra_cost = None
                economic_reasons.append("nonfinite_cost_arithmetic")
            if extra_cost is not None and lower - extra_cost <= 0:
                economic_reasons.append("positive_full_cost_net_value_not_established")
        if not complete:
            economic_reasons.append("full_cost_net_value_unknown")
        reasons = quality_reasons + resource_reasons + economic_reasons
        report = {"schema": "hepta.memory.matched-admission.v15.cost-bound-v1", "approved": not reasons,
                  "quality_qualified": not quality_reasons,
                  "resource_qualified": not resource_reasons,
                  "economic_qualified": not reasons,
                  "qualification_reasons": {"quality": quality_reasons, "resource": resource_reasons,
                                            "economic": economic_reasons},
                  "candidate": candidate.bundle, "incumbent": incumbent.bundle,
                  "manifest": digest(manifest), "protocol": p.identity,
                  "protocol_settings": digest(vars(p)), "data": self.data_digest,
                  "observed_protocol_settings": observed_settings,
                  "cohort_registration": digest(registration),
                  "budget": self.budget_digest, "workload": p.workload_digest,
                  "paired_mean": mean, "paired_lower_bound": lower, "per_bound_alpha": alpha,
                  "clusters": len(groups), "requests_per_arm": self.case_count,
                  "qualified_clusters": len(groups) if not self._registration_reasons else None,
                  "extra_cost_per_read": extra_cost, "retention": retention,
                  "reasons": reasons, "traces": {"candidate": left, "incumbent": right},
                  "execution": {"candidate": runs[0][1], "incumbent": runs[1][1]},
                  "costs": {"candidate": candidate_cost, "incumbent": incumbent_cost},
                  "statistical_scope": "Equal-weight independent cluster means; fixed prospective comparisons and monitoring looks. Cost horizon must use the same uniform-cluster workload mixture.",
                  "production_authority": False}
        report["evidence"] = digest(report)
        return report
