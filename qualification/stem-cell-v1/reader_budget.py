"""Observed Reader inference budgets and preregistered work-frontier reports.

Callback wall includes subprocess waiting; native wall is a subset, never an
additional wall charge. Process CPU excludes children, whose measured CPU is
separate and nullable. Formula FLOPs describe covered operators, not measured
silicon operations. Unknown work cannot qualify matching on that dimension;
measured CPU/wall can still support explicitly partial descriptive comparisons.
"""
import copy
import hashlib
import json
import time


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"integer {name} >= {minimum} required")


def _identity(value):
    if not isinstance(value, str) or not 1 <= len(value.encode()) <= 256:
        raise ValueError("bounded provenance identity required")


class BudgetExceeded(RuntimeError):
    """Measured work or a declared upper support exceeded the fixed budget."""


class Budget:
    """Debit completed callbacks, including failures; no unmeasured savings.

    Upper supports are registered per phase. Their validity is not certified.
    Proposal depth increments only when increment_step=True, independently of
    callback_count. Unknown actual formula work makes future admission fail.
    """
    def __init__(self, *, max_steps, max_formula_flops, max_wall_ns,
                 registered_upper, max_callbacks=None):
        for name, value in (("max_steps", max_steps), ("max_formula_flops", max_formula_flops),
                            ("max_wall_ns", max_wall_ns)):
            _integer(value, name, 1)
        max_callbacks = max_callbacks if max_callbacks is not None else max_steps * 8
        _integer(max_callbacks, "max_callbacks", 1)
        if max_steps > 4096 or max_callbacks > 32768:
            raise ValueError("bounded inference callback/step count required")
        if not isinstance(registered_upper, dict) or not 1 <= len(registered_upper) <= 64:
            raise ValueError("bounded registered phase upper supports required")
        for phase, bound in registered_upper.items():
            _identity(phase)
            if not isinstance(bound, dict) or set(bound) != {"formula_flops", "wall_ns", "source_id"}:
                raise ValueError("complete registered formula/wall support required")
            _identity(bound["source_id"])
            _integer(bound["formula_flops"], "upper formula FLOPs")
            _integer(bound["wall_ns"], "upper wall time", 1)
        self.limits = dict(max_steps=max_steps, max_formula_flops=max_formula_flops,
                           max_wall_ns=max_wall_ns, max_callbacks=max_callbacks)
        self.registered_upper = copy.deepcopy(registered_upper)
        self.registration_id = _digest(dict(limits=self.limits, upper=self.registered_upper))
        self.receipts = []
        self.steps = 0
        self.wall_ns = 0
        self.formula_flops = 0
        self.stopped = False

    def can_start(self, phase, *, increment_step=False):
        if self.registration_id != _digest(dict(limits=self.limits, upper=self.registered_upper)):
            raise ValueError("registered callback upper supports changed")
        if type(increment_step) is not bool or phase not in self.registered_upper:
            raise ValueError("registered phase and explicit proposal increment required")
        bound = self.registered_upper[phase]
        return (not self.stopped and len(self.receipts) < self.limits["max_callbacks"]
                and self.steps + int(increment_step) <= self.limits["max_steps"]
                and self.formula_flops + bound["formula_flops"] <= self.limits["max_formula_flops"]
                and self.wall_ns + bound["wall_ns"] <= self.limits["max_wall_ns"])

    def debit(self, phase, *, wall_ns, cpu_ns, formula_flops, formula_source,
              source_id, increment_step=False, native_subprocess_wall_ns=0,
              native_child_cpu_ns=0, native_source_id=None, failed=False):
        """Record one completed callback; overrun is recorded BEFORE raising."""
        if phase not in self.registered_upper or type(increment_step) is not bool:
            raise ValueError("registered phase required")
        _identity(source_id)
        for name, value in (("wall_ns", wall_ns), ("cpu_ns", cpu_ns),
                            ("native_subprocess_wall_ns", native_subprocess_wall_ns)):
            _integer(value, name)
        if native_subprocess_wall_ns > wall_ns:
            raise ValueError("native wall must be a subset of callback wall")
        if native_child_cpu_ns is not None:
            _integer(native_child_cpu_ns, "native_child_cpu_ns")
        if native_subprocess_wall_ns or native_child_cpu_ns is None or native_child_cpu_ns:
            _identity(native_source_id)
        if formula_flops is not None:
            _integer(formula_flops, "observed formula FLOPs")
        complete = formula_flops is not None and formula_source == "operator_formula_complete.v1"
        _identity(formula_source) if formula_source is not None else None
        admitted = self.can_start(phase, increment_step=increment_step)
        bound = self.registered_upper[phase]
        self.steps += int(increment_step)
        self.wall_ns += wall_ns
        self.formula_flops += formula_flops or 0
        overrun = (not admitted or wall_ns > bound["wall_ns"]
                   or (formula_flops is not None and formula_flops > bound["formula_flops"])
                   or self.wall_ns > self.limits["max_wall_ns"]
                   or self.formula_flops > self.limits["max_formula_flops"])
        receipt = dict(phase=phase, wall_ns=wall_ns, cpu_ns=cpu_ns, formula_flops=formula_flops,
            formula_source=formula_source, source_id=source_id, increment_step=increment_step,
            native_subprocess_wall_ns=native_subprocess_wall_ns,
            native_child_cpu_ns=native_child_cpu_ns, native_source_id=native_source_id,
            failed=bool(failed), qualified=complete and native_child_cpu_ns is not None and not overrun and not failed,
            overrun=overrun, registered_upper_source_id=bound["source_id"])
        self.receipts.append(receipt)
        self.stopped = self.stopped or overrun or not complete or bool(failed)
        if overrun:
            raise BudgetExceeded("completed callback exceeded registered support or remaining budget")
        return receipt

    def measure(self, phase, callback, *, work_receipt, increment_step=False):
        """Measure callback; work_receipt() supplies post-callback operator work.

        Its dict contains debit's formula_flops/formula_source/source_id and
        optional native fields. Exceptions still debit CPU/wall; work-receipt
        failures preserve unknown formula work and stop subsequent execution.
        """
        if not self.can_start(phase, increment_step=increment_step):
            raise BudgetExceeded("registered next callback upper does not fit")
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        failed = True
        try:
            value = callback()
            failed = False
            return value
        finally:
            elapsed_wall, elapsed_cpu = time.perf_counter_ns() - wall, time.process_time_ns() - cpu
            try:
                work = work_receipt()
            except Exception:
                work = dict(formula_flops=None, formula_source=None,
                            source_id="unavailable-work-receipt")
            try:
                self.debit(phase, wall_ns=elapsed_wall, cpu_ns=elapsed_cpu,
                           increment_step=increment_step, failed=failed, **work)
            except (ValueError, TypeError):
                self.debit(phase, wall_ns=elapsed_wall, cpu_ns=elapsed_cpu,
                    increment_step=increment_step, failed=failed, formula_flops=None,
                    formula_source=None, source_id="invalid-work-receipt",
                    native_child_cpu_ns=None, native_source_id="invalid-native-receipt")

    def report(self):
        known = all(r["formula_flops"] is not None
                    and r["formula_source"] == "operator_formula_complete.v1" for r in self.receipts)
        qualified = all(r["qualified"] for r in self.receipts)
        child_known = all(r["native_child_cpu_ns"] is not None for r in self.receipts)
        return dict(schema="hepta.reader.actual-budget.v1", registration_id=self.registration_id,
            limits=dict(self.limits), steps=self.steps, callback_count=len(self.receipts),
            wall_ns=self.wall_ns, cpu_ns=sum(r["cpu_ns"] for r in self.receipts),
            native_child_cpu_ns=(sum(r["native_child_cpu_ns"] for r in self.receipts)
                                 if child_known else None),
            formula_flops=self.formula_flops if known else None,
            covered_formula_flops=self.formula_flops, qualified=bool(self.receipts) and qualified,
            stopped=self.stopped, receipts=copy.deepcopy(self.receipts),
            measurement_scope="completed_callback_payload_only",
            strict_equal_work_established=False, provenance_authenticity_verified=False)


def allocate_shared_feature_cost(cost, uses):
    """Conserve one physical feature cost over registered ACTUAL logical uses.

    Freeze the observed-use membership before final scoring. No projected or
    counterfactual uses qualify. Allocation changes accounting, never physical
    cost. Integer remainder allocation follows sorted use IDs deterministically.
    """
    if not isinstance(cost, dict) or set(cost) != {"feature_id", "source_id", "cpu_ns", "wall_ns",
            "formula_flops", "native_child_cpu_ns", "formula_source"}:
        raise ValueError("complete measured shared feature cost required")
    for key in ("feature_id", "source_id"):
        _identity(cost[key])
    if not isinstance(uses, (list, tuple)) or not 1 <= len(uses) <= 1_000_000:
        raise ValueError("nonempty actual feature uses required")
    ids = []
    for use in uses:
        if (not isinstance(use, dict) or set(use) != {"use_id", "feature_id", "source_id", "observed"}
                or use["observed"] is not True or use["feature_id"] != cost["feature_id"]):
            raise ValueError("complete observed feature-use receipt required")
        _identity(use["use_id"])
        _identity(use["source_id"])
        ids.append(use["use_id"])
    if len(set(ids)) != len(ids):
        raise ValueError("unique logical feature-use IDs required")
    allocations = {i: {} for i in sorted(ids)}
    for meter in ("cpu_ns", "wall_ns", "formula_flops", "native_child_cpu_ns"):
        value = cost[meter]
        if value is not None:
            _integer(value, meter)
        for position, identity in enumerate(allocations):
            allocations[identity][meter] = None if value is None else value // len(ids) + (position < value % len(ids))
    return dict(schema="hepta.reader.shared-cost-allocation.v1", feature_id=cost["feature_id"],
        allocation_id=_digest(dict(cost=cost, uses=sorted(uses, key=lambda u: u["use_id"]))),
        physical_cost=dict(cost), observed_logical_uses=len(ids), allocations=allocations,
        uses=copy.deepcopy(sorted(uses, key=lambda u: u["use_id"])),
        qualified=all(cost[m] is not None for m in ("cpu_ns", "wall_ns", "formula_flops", "native_child_cpu_ns"))
                  and cost["formula_source"] == "operator_formula_complete.v1",
        membership_frozen_before_final_verified=False, counterfactual_savings_claimed=False)


def observation_manifest_sha256(observations):
    return _digest(sorted((r["case_id"], r["arm"], r["source_group"], r["split"]) for r in observations))


def _cost_complete(row):
    """Completeness is per dimension; valid execution does not imply full cost."""
    for meter in ("formula_flops", "wall_ns", "cpu_ns", "native_child_cpu_ns"):
        if row.get(meter) is not None:
            _integer(row[meter], meter)
    complete = dict(formula_flops=row.get("formula_flops") is not None
                    and row.get("formula_source") == "operator_formula_complete.v1",
                    wall_ns=row.get("wall_ns") is not None,
                    cpu_ns=row.get("cpu_ns") is not None and row.get("native_child_cpu_ns") is not None)
    flags = row.get("cost_complete", dict.fromkeys(complete, True))
    if not isinstance(flags, dict) or set(flags) != set(complete) or any(type(v) is not bool for v in flags.values()):
        raise ValueError("explicit cost-completeness flags must cover every dimension")
    return {meter: value and flags[meter] for meter, value in complete.items()}


def freeze_frontier_bins(*, observations, arms, metric, edges):
    """Register membership and bins without consulting final outcome labels."""
    if metric not in ("formula_flops", "wall_ns", "cpu_ns"):
        raise ValueError("registered actual-work metric required")
    if not isinstance(arms, (list, tuple)) or not 2 <= len(arms) <= 16 or len(set(arms)) != len(arms):
        raise ValueError("distinct registered comparison arms required")
    for arm in arms:
        _identity(arm)
    if not isinstance(observations, (list, tuple)) or not 1 <= len(observations) <= 1_000_000:
        raise ValueError("bounded nonempty registered observation membership required")
    if len({r["split"] for r in observations}) != 1:
        raise ValueError("report each registered evaluation partition separately")
    if (not isinstance(edges, (list, tuple)) or not 2 <= len(edges) <= 64
            or any(type(e) is not int or e < 0 for e in edges)
            or any(a >= b for a, b in zip(edges, edges[1:]))):
        raise ValueError("strictly increasing preregistered integer bin edges required")
    body = dict(schema="hepta.reader.work-frontier-protocol.v1", arms=list(arms), metric=metric,
                edges=list(edges), observation_manifest_sha256=observation_manifest_sha256(observations))
    return {**body, "protocol_id": _digest(body)}


def summarize_work_frontier(observations, bins, *, preregistered_protocol_id):
    """Report all registered bins; same-bin matching is not exact equal work.

    All arms must have the same case/source/split and fall in the same bin.
    qualified means valid execution; cost completeness is checked separately
    for the registered metric. Other missing dimensions remain visible.
    Outcome-blind exclusions are fully counted. This descriptive final analysis
    chooses no arm, threshold or model and gives no causal/independence claim.
    """
    expected = freeze_frontier_bins(observations=observations, arms=bins["arms"],
                                    metric=bins["metric"], edges=bins["edges"])
    if bins != expected or bins["protocol_id"] != preregistered_protocol_id:
        raise ValueError("frontier protocol/membership differs from registration")
    cases, excluded = {}, dict(incomplete_cost=0, invalid_execution=0, missing_arm=0,
                              different_bin=0, outside_support=0)
    dimensions = ("formula_flops", "cpu_ns", "wall_ns")
    registered_incomplete, matched_incomplete = (dict.fromkeys(dimensions, 0) for _ in range(2))
    completeness = {}
    for row in observations:
        for key in ("case_id", "source_group", "source_id", "split", "arm"):
            _identity(row[key])
        if row["arm"] not in bins["arms"] or type(row["success"]) is not bool:
            raise ValueError("registered arm and externally observed success required")
        identity = row["case_id"]
        group = cases.setdefault(identity, {})
        if row["arm"] in group:
            raise ValueError("duplicate case/arm observation")
        if group and any((r["source_group"], r["split"]) != (row["source_group"], row["split"]) for r in group.values()):
            raise ValueError("case/source/split mismatch")
        group[row["arm"]] = row
        complete = _cost_complete(row)
        completeness[(identity, row["arm"])] = complete
        for meter in dimensions:
            registered_incomplete[meter] += not complete[meter]
    reports = [dict(lower=a, upper=b, cases=0, source_groups=set(),
                   incomplete_cost_rows=dict.fromkeys(dimensions, 0), unqualified_full_cost_cases=0,
                   arms={arm: dict(n=0, correct=0,
                   actual_work_min=None, actual_work_max=None, actual_work_sum=0) for arm in bins["arms"]})
               for a, b in zip(bins["edges"], bins["edges"][1:])]
    for group in cases.values():
        if set(group) != set(bins["arms"]):
            excluded["missing_arm"] += 1
            continue
        if any(r.get("qualified") is not True for r in group.values()):
            excluded["invalid_execution"] += 1
            continue
        if any(not completeness[(r["case_id"], r["arm"])][bins["metric"]] for r in group.values()):
            excluded["incomplete_cost"] += 1
            continue
        indices = []
        for row in group.values():
            work = row[bins["metric"]] + (row["native_child_cpu_ns"] if bins["metric"] == "cpu_ns" else 0)
            indices.append(next((i for i, r in enumerate(reports) if r["lower"] <= work < r["upper"]), None))
        if None in indices:
            excluded["outside_support"] += 1
            continue
        if len(set(indices)) != 1:
            excluded["different_bin"] += 1
            continue
        report = reports[indices[0]]
        report["cases"] += 1
        report["source_groups"].add(next(iter(group.values()))["source_group"])
        full_cost_complete = all(all(completeness[(r["case_id"], r["arm"])].values()) for r in group.values())
        report["unqualified_full_cost_cases"] += not full_cost_complete
        for arm, row in group.items():
            for meter in dimensions:
                incomplete = not completeness[(row["case_id"], arm)][meter]
                report["incomplete_cost_rows"][meter] += incomplete
                matched_incomplete[meter] += incomplete
            summary = report["arms"][arm]
            work = row[bins["metric"]] + (row["native_child_cpu_ns"] if bins["metric"] == "cpu_ns" else 0)
            summary["n"] += 1
            summary["correct"] += row["success"]
            summary["actual_work_sum"] += work
            summary["actual_work_min"] = work if summary["actual_work_min"] is None else min(work, summary["actual_work_min"])
            summary["actual_work_max"] = work if summary["actual_work_max"] is None else max(work, summary["actual_work_max"])
    for report in reports:
        report["source_groups"] = sorted(report["source_groups"])
        report["cost_complete"] = {m: report["cases"] > 0 and report["incomplete_cost_rows"][m] == 0 for m in dimensions}
        report["unqualified_full_cost"] = report["cases"] == 0 or report["unqualified_full_cost_cases"] > 0
    matched_cases = sum(r["cases"] for r in reports)
    return dict(schema="hepta.reader.observed-work-frontier.v1", protocol_id=bins["protocol_id"],
        bins=reports, excluded=excluded, registered_cases=len(cases),
        registered_incomplete_cost_rows=registered_incomplete, matched_incomplete_cost_rows=matched_incomplete,
        cost_complete={m: matched_cases > 0 and matched_incomplete[m] == 0 for m in dimensions},
        unqualified_full_cost_cases=sum(r["unqualified_full_cost_cases"] for r in reports),
        unqualified_full_cost=matched_cases == 0 or any(matched_incomplete.values()),
        metric=bins["metric"], strict_equal_work_established=False, selection_authority=False,
        matching="paired_case_all_registered_arms_same_preregistered_work_bin",
        preregistration_time_verified=False, provenance_authenticity_verified=False)
