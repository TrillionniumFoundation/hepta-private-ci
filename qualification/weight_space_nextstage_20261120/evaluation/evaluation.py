#!/usr/bin/env python3
"""Bounded, read-only evaluation and finite research decision protocol.

Trust boundary: an experiment owner supplies the SHA of an owner pin file outside
the candidate request. Pins authenticate bytes relative to that trusted input;
they do not authenticate a remote producer, prove semantic correctness, or create
external holdout custody. This module never publishes, trains or adopts a model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import statistics
import time

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_SAMPLES = 4096
MAX_UNITS = 64
MAX_CANDIDATES = 16
MAX_DOMAINS = 4
STOP = "KEEP_ORIGINAL_AND_STOP"
RECOMMEND = "RECOMMEND_RESEARCH_CANDIDATE"
ROLES = {"protocol", "clock", "originals", "model_graph", "task", "input_schema",
         "label_source", "objective", "semantics", "seal", "samples", "labels",
         "exposures", "outcomes", "costs"}
BINDINGS = {"originals", "model_graph", "task", "input_schema", "label_source",
            "objective", "semantics"}


class Invalid(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Invalid(message)


def fields(value, names, where):
    require(type(value) is dict and set(value) == set(names), f"{where}: exact fields required")
    return value


def number(value, where, minimum=None, maximum=None):
    require(type(value) in (int, float) and math.isfinite(value), f"{where}: finite number required")
    if minimum is not None:
        require(value >= minimum, f"{where}: below minimum")
    if maximum is not None:
        require(value <= maximum, f"{where}: above maximum")
    return float(value)


def integer(value, where, minimum=0, maximum=2**53-1):
    require(type(value) is int and minimum <= value <= maximum, f"{where}: bounded integer required")
    return value


def name(value, where):
    require(type(value) is str and 0 < len(value) <= 160 and "\0" not in value,
            f"{where}: bounded name required")
    return value


def digest(value):
    return hashlib.sha256(value).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode()


def sha(value, where):
    require(type(value) is str and len(value) == 64 and
            all(c in "0123456789abcdef" for c in value), f"{where}: lowercase SHA256 required")
    return value


def unique(values, where):
    require(len(values) == len(set(values)), f"{where}: duplicates")


def _pairs(values):
    result = {}
    for k, v in values:
        require(k not in result, "duplicate JSON key")
        result[k] = v
    return result


def decode(raw, max_string_chars=16384):
    integer(max_string_chars, "JSON string character bound", 1, MAX_FILE_BYTES)
    def bad_constant(value):
        raise Invalid(f"nonfinite JSON constant: {value}")
    try:
        obj = json.loads(raw, object_pairs_hook=_pairs, parse_constant=bad_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise Invalid("invalid bounded JSON") from exc
    todo, count = [(obj, 0)], 0
    while todo:
        value, depth = todo.pop()
        count += 1
        require(depth <= 16 and count <= 300000, "JSON nesting/node budget exceeded")
        if isinstance(value, dict):
            todo.extend((v, depth + 1) for v in value.values())
        elif isinstance(value, list):
            todo.extend((v, depth + 1) for v in value)
        elif isinstance(value, str):
            require(len(value) <= max_string_chars, "JSON string budget exceeded")
        elif type(value) in (float, int):
            try:
                finite = math.isfinite(value)
            except OverflowError:
                finite = False
            require(finite, "nonfinite or out-of-range JSON number")
    return obj


def read_pinned(root, record):
    fields(record, {"path", "sha256"}, "artifact pin")
    sha(record["sha256"], "artifact pin")
    relative = Path(record["path"])
    require(not relative.is_absolute() and ".." not in relative.parts, "artifact path must be confined")
    path = root / relative
    require(path.resolve().is_relative_to(root.resolve()), "artifact escapes root")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as f:
            info = os.fstat(f.fileno())
            require(stat.S_ISREG(info.st_mode), "artifact must be a regular file")
            require(info.st_size <= MAX_FILE_BYTES, "artifact byte budget exceeded")
            data = f.read(MAX_FILE_BYTES + 1)
    except OSError as exc:
        raise Invalid("artifact cannot be read") from exc
    require(len(data) <= MAX_FILE_BYTES, "artifact byte budget exceeded")
    require(digest(data) == record["sha256"], f"artifact SHA mismatch: {relative}")
    return data


class OwnerContext:
    """Out-of-band owner pins. No candidate file may create or alter this object."""
    def __init__(self, root, owner_path, expected_owner_sha256):
        self.root = Path(root).resolve()
        raw = read_pinned(self.root, {"path": owner_path, "sha256": expected_owner_sha256})
        self.owner_sha256 = digest(raw)
        self.owner = decode(raw)
        fields(self.owner, {"schema", "owner_id", "scope", "pins"}, "owner")
        require(self.owner["schema"] == "hepta.research-owner-pins.v1", "owner schema")
        name(self.owner["owner_id"], "owner_id")
        require(self.owner["scope"] in {"local_research", "synthetic_test"}, "owner scope")
        pins = self.owner["pins"]
        require(type(pins) is dict and ROLES <= set(pins) and len(pins) <= 1200, "owner roles missing/too many")
        self.raw, self.total = {}, len(raw)
        for role, record in pins.items():
            name(role, "artifact role")
            self.raw[role] = read_pinned(self.root, record)
            self.total += len(self.raw[role])
            require(self.total <= MAX_TOTAL_BYTES, "total evidence byte budget exceeded")

    def json(self, role):
        require(role in self.raw, f"missing owner artifact: {role}")
        return decode(self.raw[role])

    def hash(self, role):
        require(role in self.raw, f"missing owner artifact: {role}")
        return digest(self.raw[role])


def _beta_cf(a, b, x):
    # Lentz continued fraction for the regularized incomplete beta function.
    tiny, eps = 1e-300, 3e-14
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab*x/qap
    d = 1 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 201):
        for aa in (m*(b-m)*x/((qam+2*m)*(a+2*m)),
                   -(a+m)*(qab+m)*x/((a+2*m)*(qap+2*m))):
            d = 1 + aa*d
            c = 1 + aa/c
            d = d if abs(d) > tiny else tiny
            c = c if abs(c) > tiny else tiny
            d = 1/d
            delta = d*c
            h *= delta
        if abs(delta-1) < eps:
            return h
    raise Invalid("Student t numerical convergence failed")


def _ibeta(a, b, x):
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    v = math.exp(math.lgamma(a+b)-math.lgamma(a)-math.lgamma(b)+a*math.log(x)+b*math.log1p(-x))
    if x < (a+1)/(a+b+2):
        return v*_beta_cf(a, b, x)/a
    return 1-v*_beta_cf(b, a, 1-x)/b


def t_critical(probability, df):
    require(0.5 < probability < 1 and 1 <= df <= MAX_UNITS-1, "unsupported Student t quantile")
    lo, hi = 0.0, 1.0
    def cdf(x):
        return 1 - .5*_ibeta(df/2, .5, df/(df+x*x))
    for _ in range(30):
        if cdf(hi) >= probability:
            break
        hi *= 2
    else:
        raise Invalid("Student t quantile bracket exceeded")
    for _ in range(80):
        mid = (lo+hi)/2
        if cdf(mid) < probability:
            lo = mid
        else:
            hi = mid
    return hi


def interval(differences, alpha, comparisons, method, utility_span):
    require(2 <= len(differences) <= MAX_UNITS, "independent unit count outside bounds")
    mean = statistics.fmean(differences)
    if method == "paired_t_bonferroni":
        half = t_critical(1-alpha/(2*comparisons), len(differences)-1)*statistics.stdev(differences)/math.sqrt(len(differences))
    elif method == "hoeffding_bonferroni":
        half = 2*utility_span*math.sqrt(math.log(2*comparisons/alpha)/(2*len(differences)))
    else:
        raise Invalid("unsupported confidence method")
    return {"n_units": len(differences), "mean": mean, "lower": mean-half, "upper": mean+half}


def _document(ctx, role, names, protocol_hash, seal_hash=None):
    doc = ctx.json(role)
    fields(doc, names | {"protocol_sha256"}, role)
    require(doc["protocol_sha256"] == protocol_hash, f"{role}: protocol identity mismatch")
    if seal_hash is not None:
        require(doc["seal_sha256"] == seal_hash, f"{role}: candidate seal mismatch")
    return doc


def _future_bound(value, coordinate, basis):
    """Version 2: a declared bound is never inferred from past measured timing."""
    fields(value, {coordinate, "unmeasured_components", "basis"}, "future resource bound")
    require(value["basis"] == basis, "future resource bound basis")
    resources = value[coordinate]
    require(type(resources) is dict and 1 <= len(resources) <= 8, "future resource coordinate count")
    for unit, quantity in resources.items():
        name(unit, "future resource unit")
        if quantity is not None:
            number(quantity, "future resource bound", 0, 1e15)
    unknown = value["unmeasured_components"]
    require(type(unknown) is list and len(unknown) <= 32, "future unknown components")
    for item in unknown:
        name(item, "future unknown component")
    return {"resources": resources, "unknown": unknown}


def evaluate(ctx, system_now_ms=None):
    # CLI never accepts caller-provided now. This injection is only for deterministic tests.
    now = time.time_ns()//1_000_000 if system_now_ms is None else integer(system_now_ms, "test clock")
    result = {"schema": "hepta.finite-research-decision.v1", "decision": STOP,
              "selected_candidate": None, "owner_sha256": ctx.owner_sha256,
              "scope": ctx.owner["scope"], "source_pin_checks": len(ctx.raw),
              "production_eligible": False, "weights_modified": False,
              "external_holdout_custody_verified": False,
              "global_neural_weight_optimality_claimed": False,
              "trust_boundary": "out-of-band owner pins; local provenance and stated statistical assumptions only",
              "blockers": [], "candidate_results": []}
    try:
        _evaluate(ctx, now, result)
    except (Invalid, KeyError, TypeError, OverflowError, ZeroDivisionError, ValueError) as exc:
        result["decision"], result["selected_candidate"] = STOP, None
        result["blockers"].append(str(exc))
    return result


def _evaluate(ctx, now, result):
    p = ctx.json("protocol")
    require(type(p) is dict, "protocol must be an object")
    version2 = p.get("schema") == "hepta.finite-evaluation-protocol.v2"
    quality_field = "maximum_quality_loss" if version2 else "minimum_gain"
    fields(p, {"schema", "experiment_id", "frozen_ms", "binding", "source_mode", "freshness",
               "utility_unit", "utility_bounds", "domains", "domain_weights", quality_field,
               "statistics", "candidates", "horizon_episodes", "exchange_rates", "cost_scope"}, "protocol")
    require(p["schema"] in {"hepta.finite-evaluation-protocol.v1", "hepta.finite-evaluation-protocol.v2"}, "protocol schema")
    name(p["experiment_id"], "experiment id")
    protocol_hash = ctx.hash("protocol")
    result["protocol_sha256"] = protocol_hash
    integer(p["frozen_ms"], "protocol frozen time")
    fields(p["binding"], BINDINGS, "binding")
    for role in BINDINGS:
        require(p["binding"][role] == ctx.hash(role), f"binding mismatch: {role}")
    require(p["source_mode"] in {"observed", "simulation"}, "source mode")
    name(p["utility_unit"], "utility unit")
    require(type(p["utility_bounds"]) is list and len(p["utility_bounds"]) == 2, "utility bounds")
    ulo, uhi = (number(x, "utility bound", -1e6, 1e6) for x in p["utility_bounds"])
    require(ulo < uhi, "utility bounds order")
    domains = p["domains"]
    require(type(domains) is list and 1 <= len(domains) <= MAX_DOMAINS, "domain count")
    for d in domains:
        name(d, "domain")
    unique(domains, "domains")
    fields(p["domain_weights"], set(domains), "domain weights")
    weights = {d: number(p["domain_weights"][d], "domain weight", 0, 1) for d in domains}
    require(abs(math.fsum(weights.values())-1) <= 1e-12, "domain weights must sum to one")
    fields(p[quality_field], set(domains), "domain quality thresholds")
    if version2:
        thresholds = {d: -number(p[quality_field][d], "maximum quality loss", 0, uhi-ulo) for d in domains}
        result["quality_gate"] = "each simultaneous lower bound >= negative predeclared maximum_quality_loss"
    else:
        thresholds = {d: number(p[quality_field][d], "gain threshold", -(uhi-ulo), uhi-ulo) for d in domains}
    st = fields(p["statistics"], {"method", "unit", "minimum_units", "assumptions"}, "statistics")
    require(st["method"] in {"paired_t_bonferroni", "hoeffding_bonferroni"}, "statistics method")
    require(st["unit"] == "independently_trained_model_fit", "rows/worlds are not independent model units")
    integer(st["minimum_units"], "minimum independent units", 2, MAX_UNITS)
    expected_assumptions = ["independent_fit_effects_conditional_on_fixed_task"]
    if st["method"] == "paired_t_bonferroni":
        expected_assumptions.append("approximately_normal_fit_level_paired_differences")
    require(st["assumptions"] == expected_assumptions, "statistical assumptions must be explicit")
    result["statistical_assumptions"] = expected_assumptions
    freshness = fields(p["freshness"], {"clock_age_ms", "clock_uncertainty_ms", "source_age_ms", "label_age_ms"}, "freshness")
    for key, value in freshness.items():
        integer(value, "freshness."+key, 0, 366*86400000)
    clock = fields(ctx.json("clock"), {"source", "observed_utc_ms", "uncertainty_ms"}, "clock")
    require(clock["source"] == "clock.curr_time", "clock is not the independently acquired configured source")
    clock_lo = integer(clock["observed_utc_ms"], "clock timestamp")
    uncertainty = integer(clock["uncertainty_ms"], "clock uncertainty")
    require(uncertainty <= freshness["clock_uncertainty_ms"], "clock uncertainty too large")
    require(clock_lo <= now <= clock_lo+uncertainty+freshness["clock_age_ms"], "clock stale or future")
    clock_hi = clock_lo+uncertainty
    result["decision_clock"] = {**clock, "owner_pinned_sha256": ctx.hash("clock")}
    seal = _document(ctx, "seal", {"sealed_ms", "selection_completed_ms", "candidates"}, protocol_hash)
    seal_hash = ctx.hash("seal")
    seal_ms = integer(seal["sealed_ms"], "candidate seal time")
    selection_ms = integer(seal["selection_completed_ms"], "selection completed")
    require(p["frozen_ms"] <= selection_ms <= seal_ms <= clock_lo, "protocol/selection/seal/clock order")
    candidates = p["candidates"]
    require(type(candidates) is list and 1 <= len(candidates) <= MAX_CANDIDATES, "candidate count")
    for c in candidates:
        fields(c, {"id", "kind"}, "candidate")
        name(c["id"], "candidate id")
        kinds = {"compute_specialization"} if version2 else {"weight_edit", "training", "analytic_controller", "oracle_diagnostic"}
        require(c["id"] != "ORIGINAL" and c["kind"] in kinds, "candidate kind/id")
    candidate_ids = [c["id"] for c in candidates]
    unique(candidate_ids, "candidate ids")
    fields(seal["candidates"], set(candidate_ids), "sealed candidate set")
    units = ctx.json("originals")
    fields(units, {"schema", "units"}, "original registry")
    require(units["schema"] == "hepta.independent-fit-registry.v1", "unit registry schema")
    require(type(units["units"]) is list and st["minimum_units"] <= len(units["units"]) <= MAX_UNITS, "insufficient independent units")
    unit_ids, seeds, runs = [], [], []
    model_hashes = {}
    for u in units["units"]:
        fields(u, {"id", "training_seed", "training_run_role", "original_role"}, "unit")
        unit_ids.append(name(u["id"], "unit id"))
        seeds.append(integer(u["training_seed"], "training seed"))
        runs.append(ctx.hash(u["training_run_role"]))
        model_hashes[("ORIGINAL", u["id"])] = ctx.hash(u["original_role"])
        training = fields(ctx.json(u["training_run_role"]),
                          {"training_seed", "checkpoint_sha256", "model_graph_sha256", "status"},
                          "training provenance receipt")
        require(training["training_seed"] == u["training_seed"] and
                training["checkpoint_sha256"] == ctx.hash(u["original_role"]) and
                training["model_graph_sha256"] == p["binding"]["model_graph"] and
                training["status"] == "completed", "training provenance does not bind this independent unit")
    unique(unit_ids, "unit ids")
    unique(seeds, "training seeds")
    unique(runs, "training run identities")
    for cid in candidate_ids:
        fields(seal["candidates"][cid], set(unit_ids), "sealed per-unit models")
        for uid in unit_ids:
            model_hashes[(cid, uid)] = ctx.hash(seal["candidates"][cid][uid])
    result["statistical_units"] = len(unit_ids)
    result["candidate_set_sha256"] = seal_hash
    samples_doc = _document(ctx, "samples", {"seal_sha256", "samples"}, protocol_hash, seal_hash)
    require(type(samples_doc["samples"]) is list and 1 <= len(samples_doc["samples"]) <= MAX_SAMPLES, "no bounded confirmation samples")
    labels_doc = _document(ctx, "labels", {"label_source_sha256", "records"}, protocol_hash)
    require(labels_doc["label_source_sha256"] == p["binding"]["label_source"], "label source identity mismatch")
    require(type(labels_doc["records"]) is list and len(labels_doc["records"]) <= MAX_SAMPLES, "label count")
    labels = {}
    for row in labels_doc["records"]:
        fields(row, {"sample_id", "available_ms", "value"}, "label record")
        sid = sha(row["sample_id"], "label sample identity")
        require(sid not in labels and row["value"] is not None, "duplicate/missing label")
        integer(row["available_ms"], "label availability")
        labels[sid] = row
    exposures = _document(ctx, "exposures", {"history_scope", "events"}, protocol_hash)
    require(exposures["history_scope"] == "available_local_recorded_history", "unsupported exposure authority")
    require(type(exposures["events"]) is list and len(exposures["events"]) <= 20000, "exposure budget")
    seen = set()
    for event in exposures["events"]:
        fields(event, {"sample_id", "phase", "observed_ms"}, "exposure event")
        sha(event["sample_id"], "exposure identity")
        integer(event["observed_ms"], "exposure time")
        require(event["phase"] in {"TRAIN", "SELECTION", "PRIOR_CONFIRMATION", "DISCOVERY"}, "exposure phase")
        seen.add(event["sample_id"])
    samples, groups = {}, {(uid, d): [] for uid in unit_ids for d in domains}
    for row in samples_doc["samples"]:
        fields(row, {"sample_id", "unit_id", "domain", "split", "content", "content_sha256", "source_ms", "anchor_ms",
                     "target_end_ms", "label_available_ms", "label_record_sha256"}, "sample")
        sid = sha(row["sample_id"], "sample id")
        require(sid == row["content_sha256"] == digest(canonical(row["content"])),
                "sample identity must match actual canonical content")
        require(sid not in samples and sid not in seen, "confirmation sample duplicated or previously exposed")
        require(row["split"] == "CONFIRMATION", "TRAIN/SELECTION rows cannot establish confirmation benefit")
        require((row["unit_id"], row["domain"]) in groups, "unknown sample unit/domain")
        source, anchor, target, available = [integer(row[k], k) for k in ("source_ms", "anchor_ms", "target_end_ms", "label_available_ms")]
        require(source <= anchor <= target <= available <= clock_lo, "label immature, future, or event-time order invalid")
        require(anchor > seal_ms and source > seal_ms, "prospective sample predates frozen candidates")
        require(clock_hi-source <= freshness["source_age_ms"], "source observation stale")
        require(clock_hi-available <= freshness["label_age_ms"], "label stale")
        require(sid in labels and labels[sid]["available_ms"] == available, "label availability lacks matching receipt")
        require(digest(canonical(labels[sid])) == row["label_record_sha256"], "label record identity mismatch")
        samples[sid] = row
        groups[(row["unit_id"], row["domain"])].append(sid)
    require(set(labels) == set(samples), "label/sample population mismatch")
    require(all(groups.values()), "missing independent unit/domain block")
    # Equal sample counts prevent accidental uneven weighting across fits.
    require(len({len(v) for v in groups.values()}) == 1, "unequal confirmation block sizes")
    outcomes_doc = _document(ctx, "outcomes", {"seal_sha256", "utility_unit", "records"}, protocol_hash, seal_hash)
    require(outcomes_doc["utility_unit"] == p["utility_unit"], "outcome utility unit mismatch")
    rows = outcomes_doc["records"]
    require(type(rows) is list and len(rows) == len(samples)*(len(candidate_ids)+1), "missing/extra outcome records")
    values = {}
    for row in rows:
        fields(row, {"candidate_id", "sample_id", "model_sha256", "label_record_sha256", "utility", "scored_ms"}, "outcome")
        cid, sid = row["candidate_id"], row["sample_id"]
        require(cid in ["ORIGINAL"]+candidate_ids and sid in samples, "outcome candidate/sample mismatch")
        key = (cid, sid)
        require(key not in values, "duplicate outcome record")
        require(row["model_sha256"] == model_hashes[(cid, samples[sid]["unit_id"])], "outcome model identity mismatch")
        require(row["label_record_sha256"] == samples[sid]["label_record_sha256"], "outcome label identity mismatch")
        scored = integer(row["scored_ms"], "outcome scored time")
        require(samples[sid]["label_available_ms"] <= scored <= clock_lo, "outcome scored before label or in future")
        values[key] = number(row["utility"], "utility", ulo, uhi)
    alpha, comparisons = .05, len(candidate_ids)*len(domains)
    cost_fields = {"seal_sha256", "scope", "records"}
    if version2:
        cost_fields |= {"horizon_episodes", "original"}
    costs = _document(ctx, "costs", cost_fields, protocol_hash, seal_hash)
    require(costs["scope"] == p["cost_scope"] == "incremental_future_fixed_horizon", "sunk or differently scoped costs cannot be subtracted")
    fields(costs["records"], set(candidate_ids), "candidate costs")
    horizon = p["horizon_episodes"]
    if horizon is not None:
        integer(horizon, "horizon episodes", 1, 1000000000)
    original = None
    if version2:
        require(costs["horizon_episodes"] == horizon, "future resource bounds horizon mismatch")
        original = _future_bound(costs["original"], "resources_lower_bound", "owner_pinned_lower_bound")
    rates = p["exchange_rates"]
    if rates is not None:
        require(type(rates) is dict and 1 <= len(rates) <= 8, "exchange-rate map")
        for resource, rate in rates.items():
            name(resource, "resource unit")
            fields(rate, {"utility_unit", "per_resource_unit"}, "resource conversion")
            require(rate["utility_unit"] == p["utility_unit"], "cost/benefit utility unit mismatch")
            number(rate["per_resource_unit"], "conversion coefficient", 0, 1e12)
    for c in candidates:
        cid = c["id"]
        scores = {}
        for domain in domains:
            diffs = [statistics.fmean(values[(cid, sid)]-values[("ORIGINAL", sid)] for sid in groups[(uid, domain)]) for uid in unit_ids]
            scores[domain] = interval(diffs, alpha, comparisons, st["method"], uhi-ulo)
        lower = math.fsum(weights[d]*scores[d]["lower"] for d in domains)
        mean = math.fsum(weights[d]*scores[d]["mean"] for d in domains)
        extra, bound_blockers = {}, []
        if version2:
            candidate = _future_bound(costs["records"][cid], "resources_upper_bound", "owner_pinned_upper_bound")
            unknown = ["original:"+x for x in original["unknown"]]+["candidate:"+x for x in candidate["unknown"]]
            complete = set(original["resources"]) == set(candidate["resources"])
            if not complete:
                bound_blockers.append("baseline and candidate resource coordinates differ")
                unknown.append("incomparable_resource_coordinates")
            incremental = {}
            for unit in sorted(set(original["resources"]) | set(candidate["resources"])):
                base_lower = original["resources"].get(unit)
                candidate_upper = candidate["resources"].get(unit)
                if base_lower is None or candidate_upper is None:
                    unknown.append("missing_future_bound:"+unit)
                else:
                    incremental[unit] = candidate_upper-base_lower
            cost = {"resources": incremental, "unmeasured_components": unknown}
            extra = {"original_future_resources_lower_bound": original["resources"],
                     "candidate_future_resources_upper_bound": candidate["resources"],
                     "incremental_resources_upper_bound": incremental,
                     "future_bound_scope": "owner assumptions over exactly the declared future horizon, not past timing measurements"}
        else:
            cost = fields(costs["records"][cid], {"resources", "unmeasured_components", "basis"}, "candidate cost")
            require(cost["basis"] == "owner_pinned_upper_bound", "future cost needs an upper-bound basis")
            require(type(cost["resources"]) is dict and len(cost["resources"]) <= 8, "resource count")
            for unit, quantity in cost["resources"].items():
                name(unit, "cost resource unit")
                number(quantity, "future cost upper bound", 0, 1e15)
            require(type(cost["unmeasured_components"]) is list and len(cost["unmeasured_components"]) <= 32, "unmeasured cost list")
            for item in cost["unmeasured_components"]:
                name(item, "unmeasured component")
        blockers = []
        blockers.extend(bound_blockers)
        if c["kind"] == "oracle_diagnostic":
            blockers.append("oracle rescue is not an executable candidate with ordinary information")
        quality_failed = any(scores[d]["lower"] < thresholds[d] for d in domains) if version2 else any(scores[d]["lower"] <= thresholds[d] for d in domains)
        if quality_failed:
            blockers.append("familywise confidence lower bound fails predeclared quality retention" if version2 else
                            "familywise confidence lower bound fails required domain margin")
        if horizon is None or rates is None:
            blockers.append("missing fixed horizon or resource-to-utility conversion")
        if cost["unmeasured_components"]:
            blockers.append("unknown cost components")
        if rates is not None and set(cost["resources"]) - set(rates):
            blockers.append("unpriced resource unit")
        net, converted = None, None
        if horizon is not None and rates is not None and not cost["unmeasured_components"] and set(cost["resources"]) <= set(rates):
            converted = math.fsum(q*rates[k]["per_resource_unit"] for k,q in cost["resources"].items())
            net = horizon*lower-converted
            require(math.isfinite(net), "net lower value overflow")
            if net <= 0:
                blockers.append("conservative net value not positive")
        # These are break-even coordinates, not invented conversions or adoption claims.
        sensitivity = {unit: (None if horizon is None or q == 0 else horizon*lower/q)
                       for unit,q in cost["resources"].items()}
        if version2:
            extra["resource_conversion_sensitivity"] = {
                unit: {"incremental_resource_bound": q,
                       "strict_net_positive_condition_with_other_costs_zero":
                           "lambda > boundary" if q < 0 else "lambda < boundary" if q > 0 else
                           "net positive iff horizon times gain lower is positive",
                       "boundary": sensitivity[unit], "lambda_must_be_nonnegative": True}
                for unit,q in cost["resources"].items()}
        result["candidate_results"].append({"candidate_id": cid, "kind": c["kind"], "domains": scores,
                "weighted_gain_mean": mean, "weighted_gain_lower": lower,
                "resources_upper_bound": cost["resources"], "unmeasured_components": cost["unmeasured_components"],
                "break_even_utility_per_resource_unit_if_all_other_costs_zero": sensitivity,
                "converted_future_cost": converted, "net_value_lower": net, "blockers": blockers, **extra})
    result["evidence_qualified_for_local_research"] = True
    result["sample_count"] = len(samples)
    result["confidence"] = {"alpha": alpha, "simultaneous_comparisons": comparisons, "method": st["method"]}
    result["utility_unit"] = p["utility_unit"]
    result["horizon_episodes"] = horizon
    result["cost_scope"] = p["cost_scope"]
    result["independence_scope"] = "prospective nonoverlap against pinned local exposure history plus stated fit assumptions; not externally proven independence"
    result["pareto_scope"] = "known resource coordinates and conservative gain only; not a utility conversion"
    points = [{"candidate_id": "ORIGINAL", "gain_lower": 0.0, "resources": {}}]
    points += [{"candidate_id": c["candidate_id"], "gain_lower": c["weighted_gain_lower"],
                "resources": c["resources_upper_bound"]} for c in result["candidate_results"]
               if not c["unmeasured_components"] and c["kind"] != "oracle_diagnostic"]
    def dominates(a, b):
        # ORIGINAL has exactly zero incremental cost. Other incomplete vectors
        # are not filled with invented zeros and cannot dominate one another.
        if a["candidate_id"] != "ORIGINAL" and b["candidate_id"] != "ORIGINAL" and set(a["resources"]) != set(b["resources"]):
            return False
        keys = set(a["resources"]) | set(b["resources"])
        le = all(a["resources"].get(k, 0) <= b["resources"].get(k, 0) for k in keys)
        strict = a["gain_lower"] > b["gain_lower"] or any(a["resources"].get(k, 0) < b["resources"].get(k, 0) for k in keys)
        return a["gain_lower"] >= b["gain_lower"] and le and strict
    result["pareto_candidates"] = [b["candidate_id"] for b in points
                                    if not any(dominates(a, b) for a in points if a is not b)]
    eligible = [c for c in result["candidate_results"] if not c["blockers"]]
    if eligible:
        best = min(eligible, key=lambda c: (-c["net_value_lower"], c["candidate_id"]))
        result["decision"], result["selected_candidate"] = RECOMMEND, best["candidate_id"]
        result["selection_scope"] = "maximum conservative net lower value among this fixed finite admissible list only"
    else:
        result["blockers"].append("no fixed candidate has complete qualifying evidence and positive conservative net value")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--owner-sha256", required=True)
    args = parser.parse_args()
    try:
        result = evaluate(OwnerContext(args.root, args.owner, args.owner_sha256))
    except (Invalid, OSError, ValueError) as exc:
        result = {"schema": "hepta.finite-research-decision.v1", "decision": STOP,
                  "selected_candidate": None, "production_eligible": False,
                  "weights_modified": False, "blockers": [str(exc)]}
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
