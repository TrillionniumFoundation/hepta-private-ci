"""Frozen task-cluster confirmation; Bonferroni-Hoeffding, never bootstrap selection."""
import argparse
from collections import defaultdict
import datetime as dt
import json
import math
import os
import hashlib
from pathlib import Path
from .transport import canonical, digest, load, number, reconcile, stamp
from .contracts import validate
from .ledger import complete_events

BASELINES = ("direct_stop", "fixed_budget", "one_step_voi", "strong_planner")
CATEGORIES = ("preparation", "fitting", "allocation_search", "validation", "provisioning", "reporting")


def sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def protocol_check(p):
    require(p["schema"] == "ndu.confirmation.protocol.v1", "wrong_protocol_schema")
    require(p["status"] == "FROZEN", "protocol_not_frozen")
    validate(p, "protocol")
    identity = p["identity"]
    require(identity["kind"] == "frozen_llm", "fixture_is_not_llm_evidence")
    require(all(isinstance(identity[k], str) and identity[k] for k in ("model_id", "revision")),
            "missing_model_identity")
    require(identity["revision"].lower() not in ("latest", "main", "unknown", "unfrozen"), "mutable_revision")
    require(sha(identity["evidence_sha256"]), "missing_revision_evidence")
    arms = p["arms"]
    require(set(BASELINES+("full",)) <= set(arms), "required_baseline_missing")
    require(all(sha(v["source_sha256"]) for v in arms.values()), "missing_method_source")
    require(sha(p["transport_sha256"]) and sha(p["decoding_sha256"]), "unfrozen_transport_or_decoding")
    for key in ("split_sha256", "order_sha256", "price_card_sha256", "cost_cap_evidence_sha256", "strong_planner_qualification_sha256"):
        require(sha(p["design"][key]), "missing_"+key)
    for key in ("source_independence_attested", "shared_shocks_clustered", "state_reset", "hard_cost_cap_enforced"):
        require(p["design"][key] is True, "unresolved_"+key)
    require(p["alpha"] == .05, "wrong_familywise_alpha")
    require(type(p["repeats"]) is int and p["repeats"] > 0, "invalid_repeats")
    require(type(p["deployment_volume"]) is int and p["deployment_volume"] > 0, "invalid_deployment_volume")
    for key in ("currency_to_score", "deployment_volume", "precision_h", "deadline_seconds"):
        require(number(p[key]) and p[key] > 0, "invalid_"+key)
    for key in ("time_price", "max_service_cost", "gain_min"):
        require(number(p[key]), "invalid_"+key)
    require(isinstance(p["currency"], str) and p["currency"], "missing_currency")
    frozen = dt.datetime.fromisoformat(p["frozen_at"])
    require(frozen.tzinfo is not None, "freeze_timezone_missing")
    families = [f["id"] for f in p["families"]]
    require(len(families) >= 2 and len(set(families)) == len(families), "need_two_registered_families")
    require(all(sha(f["provenance_sha256"]) for f in p["families"]), "missing_family_provenance")
    require(len({f["provenance_sha256"] for f in p["families"]}) == len(families), "families_share_provenance")
    ids, hashes, groups, clusters = set(), set(), {}, defaultdict(set)
    for task in p["tasks"]:
        require(task["id"] not in ids and task["sha256"] not in hashes, "duplicate_task_or_content")
        require(sha(task["sha256"]) and sha(task["verifier_sha256"]), "missing_task_or_verifier_hash")
        ids.add(task["id"])
        hashes.add(task["sha256"])
        family, cluster = task["family"], task["cluster"]
        require(family in families and cluster and number(task["weight"]) and task["weight"] > 0,
                "invalid_task_cluster_or_weight")
        require(task["source_groups"], "missing_source_group")
        for group in task["source_groups"]:
            require(group not in groups or groups[group] == (family, cluster), "source_split_into_pseudo_units")
            groups[group] = (family, cluster)
        clusters[family].add(cluster)
    comparisons, pairs = p["comparisons"], set()
    require(p["M"] == len(comparisons) and p["M"] > 0, "multiplicity_mismatch")
    require(len({c["id"] for c in comparisons}) == len(comparisons), "duplicate_comparison_id")
    for c in comparisons:
        pair = c["family"], c["baseline"]
        require(pair not in pairs and c["family"] in families, "duplicate_or_unknown_contrast")
        require(c["baseline"] is None or c["baseline"] in arms and c["baseline"] != "full", "invalid_baseline")
        pairs.add(pair)
    for family in families:
        require(all((family, b) in pairs for b in BASELINES+(None,)), "missing_required_contrast")
        nmin = math.ceil(2*(1+p["max_service_cost"])**2*math.log(p["M"]/.05)/p["precision_h"]**2)
        require(len(clusters[family]) >= nmin, "insufficient_preregistered_clusters:"+family)
    if p.get("mechanism_claims"):
        require(set(p["mechanism_claims"]) <= {"no_paid_identification", "no_timing_posterior", "fixed_step_clock"},
                "unknown_mechanism_claim")
        for ablation in p["mechanism_claims"]:
            require(all((f, ablation) in pairs for f in families), "unregistered_mechanism_contrast")
    return frozen


def lifecycle(p, invoices, service_invoices):
    lower, upper, coverage = defaultdict(float), defaultdict(float), set()
    actual = {x["charge_id"]: x for x in invoices}
    require(len(actual) == len(invoices), "duplicate_lifecycle_charge")
    used, line_keys = set(), {(x.get("invoice_sha256"), x.get("line_id")) for x in service_invoices}
    plan_ids = set()
    for charge in p["lifecycle_plan"]:
        cid, category, allocation = charge["id"], charge["category"], charge["allocation"]
        require(cid not in plan_ids, "duplicate_lifecycle_plan")
        plan_ids.add(cid)
        require(category in CATEGORIES and set(allocation) <= set(p["arms"]), "invalid_lifecycle_allocation")
        require(all(number(w) for w in allocation.values()) and
                math.isclose(math.fsum(allocation.values()), 1, abs_tol=1e-12), "allocation_must_sum_to_one")
        if charge["accounting"] == "actual":
            item = actual.get(cid)
            require(item is not None and item.get("status") == "final" and item.get("currency") == p["currency"]
                    and number(item.get("amount")) and sha(item.get("invoice_sha256"))
                    and item.get("line_id"), "unreconciled_lifecycle:"+cid)
            key = item["invoice_sha256"], item["line_id"]
            require(key not in line_keys, "cost_counted_twice")
            line_keys.add(key)
            used.add(cid)
            lo = hi = item["amount"]
        else:
            require(charge["accounting"] == "frozen_bound" and sha(charge["bound_evidence_sha256"]),
                    "invalid_future_cost_bound")
            lo, hi = charge["lower_currency"], charge["upper_currency"]
            require(number(lo) and number(hi) and lo <= hi, "invalid_future_cost_interval")
        for arm, weight in allocation.items():
            lower[arm] += lo*weight*p["currency_to_score"]
            upper[arm] += hi*weight*p["currency_to_score"]
            if weight > 0:
                coverage.add((arm, category))
    require(used == set(actual), "unregistered_lifecycle_charge")
    require(all((a, c) in coverage for a in p["arms"] for c in CATEGORIES), "incomplete_full_cost_accounting")
    return lower, upper


def check_evidence(p, invoices, lifecycle_invoices, evidence):
    """Hashes are references, not evidence: require reconstructible matching material."""
    refs = {p["identity"]["evidence_sha256"], p["transport_sha256"], p["decoding_sha256"]}
    refs.update(v for k, v in p["design"].items() if k.endswith("_sha256"))
    refs.update(a["source_sha256"] for a in p["arms"].values())
    refs.update(f["provenance_sha256"] for f in p["families"])
    refs.update(t[k] for t in p["tasks"] for k in ("sha256", "verifier_sha256"))
    refs.update(x["invoice_sha256"] for x in invoices+lifecycle_invoices)
    refs.update(x["identity_evidence_sha256"] for x in invoices if "identity_evidence_sha256" in x)
    refs.update(x["bound_evidence_sha256"] for x in p["lifecycle_plan"] if x["accounting"] == "frozen_bound")
    require(isinstance(evidence, dict), "evidence_material_missing")
    materials = {}
    for ref in refs:
        item = evidence.get(ref)
        require(isinstance(item, dict), "evidence_material_missing:"+str(ref))
        if set(item) == {"json"}:
            data = canonical(item["json"]).encode()
        elif set(item) == {"text"}:
            data = item["text"].encode()
        elif set(item) == {"path"}:
            path = Path(item["path"])
            require(path.stat().st_size <= 10485760, "evidence_artifact_too_large")
            data = path.read_bytes()
        else:
            raise ValueError("invalid_evidence_reference")
        require(hashlib.sha256(data).hexdigest() == ref, "evidence_digest_mismatch:"+ref)
        materials[ref] = data
    for bill in invoices:
        if "identity_evidence_sha256" in bill:
            receipt = json.loads(materials[bill["identity_evidence_sha256"]])
            validate(receipt, "identity_receipt")
            require(receipt["request_id"] == bill["request_id"] and
                    receipt["invoice_sha256"] == bill["invoice_sha256"] and
                    all(receipt[k] == p["identity"][k] for k in ("model_id", "revision")),
                    "invoice_identity_evidence_mismatch")


def evaluate(protocol, records, events, invoices, lifecycle_invoices, evidence=None):
    """HOLD on invalid inputs; a PASS is conditional on externally verified assumptions."""
    result = {"schema": "ndu.confirmation.result.v1", "status": "HOLD", "reasons": [],
              "comparisons": [], "protocol_sha256": None, "independence_unit": "source/task cluster"}
    try:
        canonical([protocol, records, events, invoices, lifecycle_invoices])
        result["protocol_sha256"] = digest(protocol)
        frozen = protocol_check(protocol)
        p, phash = protocol, result["protocol_sha256"]
        validate({"protocol": p, "records": records, "events": events, "invoices": invoices,
                  "lifecycle_invoices": lifecycle_invoices, "evidence": evidence})
        events = complete_events(events)
        charges, problems = reconcile(events, invoices, p["currency"])
        require(not problems, ";".join(problems))
        require(all(sha(x["invoice_sha256"]) for x in invoices), "invalid_invoice_evidence")
        check_evidence(p, invoices, lifecycle_invoices, evidence)
        low_k, high_k = lifecycle(p, lifecycle_invoices, invoices)
        event_index = {e["request_id"]: e for e in events}
        require(len(event_index) == len(events), "duplicate_request")
        completion_order = defaultdict(list)
        for e in events:
            completion_order[e["task_id"], e["arm"], e["repeat"]].append(e["request_id"])
        tasks = {t["id"]: t for t in p["tasks"]}
        expected = {(t, a, r) for t in tasks for a in p["arms"] for r in range(p["repeats"])}
        observed, used, values, per_task = set(), set(), {}, []
        for record in records:
            key = record["task_id"], record["arm"], record["repeat"]
            require(type(record["repeat"]) is int, "invalid_repeat_index")
            require(key in expected and key not in observed, "missing_or_duplicate_paired_record")
            observed.add(key)
            require(record["schema"] == "ndu.confirmation.episode.v1", "episode_schema_mismatch")
            task, arm = tasks[key[0]], key[1]
            require(record["protocol_sha256"] == phash, "record_protocol_mismatch")
            require(all(record["contract"][k] == p[k] for k in ("deadline_seconds", "currency_to_score", "time_price")),
                    "execution_contract_mismatch")
            require(record["task_sha256"] == task["sha256"] and
                    record["verifier_sha256"] == task["verifier_sha256"] and
                    record["method_sha256"] == p["arms"][arm]["source_sha256"], "record_source_mismatch")
            start = dt.datetime.fromisoformat(record["started_at"])
            require(start.tzinfo is not None and start >= frozen, "outcome_precedes_freeze")
            wall, quality = record["wall_seconds"], record["quality"]
            require(number(wall) and number(quality) and quality <= 1, "invalid_quality_or_clock")
            if record["terminal"] == "delivered":
                delivery = record["delivery_at_seconds"]
                require(record["stop_requested"] is True and number(delivery) and
                        delivery <= p["deadline_seconds"] and delivery <= wall, "invalid_or_late_delivery")
            else:
                require(quality == 0 and record["delivery_at_seconds"] is None, "failed_delivery_has_quality")
            rids = record["request_ids"]
            require(rids and len(set(rids)) == len(rids) and not used.intersection(rids), "missing_or_reused_attempt")
            require(rids == completion_order[key] and event_index[rids[-1]]["kind"] == "host_envelope",
                    "episode_ledger_order_mismatch")
            used.update(rids)
            subtotal, model_count, meters = 0., 0, 0
            for rid in rids:
                event = event_index[rid]
                require(event["schema"] == "ndu.request.v2", "request_schema_mismatch")
                require(event["kind"] in ("model", "tool", "verifier", "host_envelope"), "invalid_attempt_kind")
                require(event["status"] in ("ok", "failure", "timeout", "invalid_response", "identity_mismatch", "metered"),
                        "invalid_attempt_status")
                require((event["task_id"], event["arm"], event["repeat"]) == key and
                        event["protocol_sha256"] == phash, "attempt_pairing_mismatch")
                require(number(event["wall_seconds"]) and number(event["started_monotonic"])
                        and number(event["finished_monotonic"]) and
                        math.isclose(event["finished_monotonic"]-event["started_monotonic"],
                                     event["wall_seconds"], rel_tol=1e-7, abs_tol=1e-7), "invalid_attempt_clock")
                require(dt.datetime.fromisoformat(event["started_at"]) >= start and
                        dt.datetime.fromisoformat(event["finished_at"]) >= frozen, "invalid_attempt_timestamp")
                if event["kind"] == "host_envelope":
                    meters += 1
                    require(math.isclose(event["wall_seconds"], wall, abs_tol=1e-9), "host_meter_mismatch")
                else:
                    subtotal += event["wall_seconds"]
                if event["kind"] == "model":
                    model_count += 1
                    require(event["identity_kind"] == "frozen_llm" and
                            event["expected_identity_sha256"] == digest(p["identity"]), "model_identity_mismatch")
                    require(event["transport_sha256"] == p["transport_sha256"], "transport_changed")
                    if event.get("identity_status") == "match":
                        expected_observed = {k: p["identity"][k] for k in ("model_id", "revision")}
                        require(event["observed_identity_sha256"] == digest(expected_observed), "observed_version_mismatch")
            require(meters == 1 and model_count > 0 and subtotal <= wall+1e-9, "missing_model_or_incomplete_envelope")
            meter = next(event_index[rid] for rid in rids if event_index[rid]["kind"] == "host_envelope")
            prior_end = meter["started_monotonic"]
            for rid in rids:
                e = event_index[rid]
                if e["kind"] != "host_envelope":
                    require(e["deadline_monotonic"] <= meter["started_monotonic"]+p["deadline_seconds"],
                            "request_deadline_exceeds_episode")
                    require(e["started_monotonic"] >= prior_end and e["finished_monotonic"] <= meter["finished_monotonic"],
                            "attempt_outside_serial_envelope")
                    prior_end = e["finished_monotonic"]
            if record["terminal"] == "delivered":
                checks = [event_index[rid] for rid in rids if event_index[rid]["kind"] == "verifier"]
                require(len(rids) >= 3 and event_index[rids[-3]]["kind"] == "model" and
                        event_index[rids[-3]]["status"] == "ok" and event_index[rids[-2]]["kind"] == "verifier" and
                        len(checks) == 1 and checks[0]["status"] == "ok" and
                        checks[0]["verified_quality"] == quality and
                        checks[0]["finished_monotonic"]-meter["started_monotonic"] <= record["delivery_at_seconds"],
                        "missing_or_inconsistent_verification")
            cost = math.fsum(charges[rid] for rid in rids)*p["currency_to_score"] + p["time_price"]*wall
            require(cost <= p["max_service_cost"], "hard_service_cost_cap_breached")
            values[key] = quality-cost
        require(observed == expected and used == set(event_index), "incomplete_pairs_or_unassigned_attempts")
        clusters = defaultdict(dict)
        for task in p["tasks"]:
            row = {a: math.fsum(values[task["id"], a, r] for r in range(p["repeats"]))/p["repeats"]
                   for a in p["arms"]}
            per_task.append({"task_id": task["id"], "utility": row})
            clusters[task["family"], task["cluster"]][task["id"]] = row
        for contrast in p["comparisons"]:
            base, differences = contrast["baseline"], []
            for (family, _), members in clusters.items():
                if family != contrast["family"]:
                    continue
                weights = math.fsum(tasks[t]["weight"] for t in members)
                differences.append(math.fsum(tasks[t]["weight"]*(v["full"]-(v[base] if base else 0))
                                             for t, v in members.items())/weights)
            n, B = len(differences), 1+p["max_service_cost"]
            radius = B*math.sqrt((2 if base else .5)*math.log(p["M"]/.05)/n)
            charge = (high_k["full"]-(low_k[base] if base else 0))/p["deployment_volume"]
            mean = math.fsum(differences)/n
            lower = mean-radius-charge
            passed = lower > (p["gain_min"] if base else 0)
            result["comparisons"].append({**contrast, "n_clusters": n, "cluster_values": differences,
                "service_mean": mean, "service_lower": mean-radius, "radius": radius,
                "lifecycle_charge_upper": charge, "lifecycle_lower": lower, "passed": passed})
            if not passed:
                result["reasons"].append("lower_bound_not_positive:"+contrast["id"])
        result["per_task"] = per_task
        result["status"] = "PASS" if not result["reasons"] else "HOLD"
    except (ValueError, KeyError, TypeError, AttributeError, OSError, OverflowError, RecursionError, ZeroDivisionError) as exc:
        result["reasons"].append(str(exc) if isinstance(exc, ValueError) else "invalid_input:"+type(exc).__name__)
    return result


def freeze(protocol, output):
    p = {**protocol, "status": "FROZEN", "frozen_at": stamp()}
    protocol_check(p)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(canonical(p)+"\n")
        stream.flush()
        os.fsync(stream.fileno())
    return {"protocol_sha256": digest(p), "frozen_at": p["frozen_at"], "registration": "local_only"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle")
    parser.add_argument("--output", required=True)
    parser.add_argument("--freeze", action="store_true")
    args = parser.parse_args()
    if args.freeze:
        print(canonical(freeze(load(args.bundle), args.output)))
    else:
        bundle = load(args.bundle)
        outcome = evaluate(**bundle)
        with open(args.output, "w", encoding="utf-8") as stream:
            stream.write(canonical(outcome)+"\n")
        print(canonical({"status": outcome["status"], "reasons": outcome["reasons"]}))
