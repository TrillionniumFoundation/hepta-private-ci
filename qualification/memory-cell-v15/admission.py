"""Trusted, prospective paired evaluator; never accepts a client approval flag.

This is a research admission predicate, not an authentication or sandbox boundary.
The host supplies frozen cases, runners, resource receipts and prices. Cluster
independence and measurement integrity remain explicit experiment assumptions.
"""

from dataclasses import dataclass, replace
import hashlib
import json
import math
import time

from cohort import INFORMATION, check_arms, check_registration


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


CPU_PHASES = ("acquire_cpu_s", "train_cpu_s", "search_cpu_s", "update_cpu_s",
              "verify_cpu_s", "serve_cpu_s", "restore_cpu_s", "migration_cpu_s")
COSTS = CPU_PHASES + ("retained_byte_seconds", "network_bytes", "energy_joules",
                     "billed_usd", "peak_rss_bytes", "p99_seconds")


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
    Deadline overruns count as failures; this in-process evaluator cannot preempt
    a hung predictor and must run inside an externally bounded worker.
    """

    def __init__(self, cases, executor_factory, protocol, *, registration=None):
        # A frozen dataclass alone does not freeze nested payload/expected objects.
        self._cases_wire = json.dumps([vars(x) for x in cases], sort_keys=True, allow_nan=False)
        cases = tuple(Case(**row) for row in json.loads(self._cases_wire))
        self.executor_factory = executor_factory
        self.protocol = replace(protocol, required_strata=tuple(protocol.required_strata),
                                prices=tuple(tuple(x) for x in protocol.prices),
                                limits=tuple(tuple(x) for x in protocol.limits))
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
                or not p.identity or not p.required_strata
                or len(set(p.required_strata)) != len(p.required_strata)):
            raise ValueError("invalid frozen experiment")
        prices, limits = dict(p.prices), dict(p.limits)
        if (len(prices) != len(p.prices) or len(limits) != len(p.limits)
                or not set(prices) <= set(COSTS) or not set(limits) <= set(COSTS)
                or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0
                       for v in list(prices.values()) + list(limits.values()))):
            raise ValueError("invalid resource prices or common limits")
        if prices.get("billed_usd", 0) and any(prices.get(k, 0) for k in COSTS
                                                if k not in ("billed_usd", "p99_seconds")):
            raise ValueError("use bills or resource pricing, not both")
        self.data_digest = digest(json.loads(self._cases_wire))
        self._registration_wire = json.dumps(registration, sort_keys=True, allow_nan=False)
        self._registration_reasons = check_registration(json.loads(self._registration_wire),
                                    cases, p, self.data_digest, digest(vars(p)))

    def _run(self, model, executor):
        rows = []
        for raw in json.loads(self._cases_wire):
            case = Case(**raw)
            began = time.perf_counter()
            try:
                # Isolate mutable inputs between arms and between requests.
                query = json.loads(json.dumps(case.query, allow_nan=False))
                payload = json.loads(json.dumps(case.payload, allow_nan=False))
                choice = model.predict(query)
                output = executor(choice, payload)
                correct = output == case.expected
                error = None
            except Exception as exc:
                correct, error = False, type(exc).__name__
            elapsed = time.perf_counter() - began
            if elapsed > self.protocol.deadline_seconds:
                correct, error = False, "deadline"
            rows.append({"id": case.key, "cluster": case.cluster, "stratum": case.stratum,
                         "correct": bool(correct), "error": error, "seconds": elapsed})
        return rows

    def evaluate(self, candidate, incumbent, candidate_cost, incumbent_cost, *, manifest):
        p, reasons = self.protocol, list(self._registration_reasons)
        registration = json.loads(self._registration_wire)
        reasons.extend(check_arms(registration, candidate, incumbent))
        # Freeze caller-owned nested receipts before invoking any model callbacks.
        frozen = json.loads(json.dumps({"candidate_cost": candidate_cost,
                                       "incumbent_cost": incumbent_cost, "manifest": manifest},
                                      allow_nan=False))
        candidate_cost, incumbent_cost, manifest = (frozen["candidate_cost"],
                                                    frozen["incumbent_cost"], frozen["manifest"])
        if p.prospective is not True:
            reasons.append("retrospective_evidence_cannot_authorize_growth")
        if candidate.bundle == incumbent.bundle:
            reasons.append("candidate_equals_incumbent")
        for field in INFORMATION:
            if not getattr(candidate, field) or getattr(candidate, field) != getattr(incumbent, field):
                reasons.append("unmatched_" + field)
        # The complete new bundle identity must be supplied by the trusted loader.
        if manifest.get("bundle") != candidate.bundle or manifest.get("memory") != candidate.memory:
            reasons.append("candidate_manifest_mismatch")
        costs = []
        for label, ledger in (("candidate", candidate_cost), ("incumbent", incumbent_cost)):
            if (ledger.get("bundle") != getattr(candidate if label == "candidate" else incumbent, "bundle")
                    or ledger.get("protocol") != p.identity
                    or ledger.get("protocol_settings") != digest(vars(p))
                    or ledger.get("horizon_reads") != p.expected_reads
                    or ledger.get("all_searches_and_failures_included") is not True):
                reasons.append(label + "_unbound_cost_receipt")
            values = ledger.get("resources", {})
            missing = [k for k in COSTS if type(values.get(k)) not in (int, float)
                       or not math.isfinite(values[k]) or values[k] < 0]
            if missing:
                reasons.append(label + "_unmeasured_or_invalid:" + ",".join(missing))
            for key, limit in p.limits:
                value = values.get(key)
                if type(value) in (int, float) and math.isfinite(value) and value > limit:
                    reasons.append(label + "_budget_exceeded:" + key)
            costs.append(values)
        left_executor, right_executor = self.executor_factory(), self.executor_factory()
        if left_executor is right_executor:
            raise ValueError("executor factory must create isolated arm instances")
        left, right = self._run(candidate, left_executor), self._run(incumbent, right_executor)
        groups, by_stratum = {}, {}
        for a, b in zip(left, right, strict=True):
            value = int(a["correct"]) - int(b["correct"])
            groups.setdefault(a["cluster"], []).append(value)
            by_stratum.setdefault(a["stratum"], {}).setdefault(a["cluster"], []).append(value)
        alpha = p.alpha / (p.comparisons * p.planned_looks * (1 + len(p.required_strata)))
        averages = [sum(v) / len(v) for v in groups.values()]
        mean, lower = paired_bound(averages, alpha)
        if len(groups) < p.minimum_clusters:
            reasons.append("insufficient_independent_clusters")
        retention = {}
        for stratum in p.required_strata:
            units = by_stratum.get(stratum, {})
            if len(units) < p.minimum_clusters:
                reasons.append("missing_or_small_stratum:" + stratum)
            if units:
                value, bound = paired_bound([sum(v) / len(v) for v in units.values()], alpha)
                retention[stratum] = {"mean": value, "lower": bound, "clusters": len(units)}
                if bound < -p.retention_margin:
                    reasons.append("retention_not_established:" + stratum)
        complete = all(all(type(cost.get(k)) in (int, float) and math.isfinite(cost[k])
                           and cost[k] >= 0 for k in COSTS) for cost in costs)
        extra_cost = None
        if complete:
            extra_cost = sum(price * (costs[0][key] - costs[1][key])
                             for key, price in p.prices) / p.expected_reads
            if lower - extra_cost <= 0:
                reasons.append("positive_full_cost_net_value_not_established")
        else:
            reasons.append("full_cost_net_value_unknown")
        report = {"schema": "hepta.memory.matched-admission.v15.cohort-v1", "approved": not reasons,
                  "candidate": candidate.bundle, "incumbent": incumbent.bundle,
                  "manifest": digest(manifest), "protocol": p.identity,
                  "protocol_settings": digest(vars(p)), "data": self.data_digest,
                  "cohort_registration": digest(registration),
                  "paired_mean": mean, "paired_lower_bound": lower, "per_bound_alpha": alpha,
                  "clusters": len(groups), "requests_per_arm": self.case_count,
                  "qualified_clusters": len(groups) if not self._registration_reasons else None,
                  "extra_cost_per_read": extra_cost, "retention": retention,
                  "reasons": reasons, "traces": {"candidate": left, "incumbent": right},
                  "costs": {"candidate": candidate_cost, "incumbent": incumbent_cost},
                  "statistical_scope": "Equal-weight independent cluster means; fixed prospective comparisons and monitoring looks. Cost horizon must use the same uniform-cluster workload mixture.",
                  "production_authority": False}
        report["evidence"] = digest(report)
        return report
