"""Independent local gate checks; execution is opt-in after a stable-source notice.

Only synthetic in-memory bundles are evaluated. No target test helpers, provider
APIs, or source mutations are used. This is not scientific confirmation evidence.
"""
import argparse
import copy
import datetime as dt
import hashlib
import importlib
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ARMS = ("direct_stop", "fixed_budget", "one_step_voi", "strong_planner", "full")
CATEGORIES = ("preparation", "fitting", "allocation_search", "validation", "provisioning", "reporting")
TARGET_DEFAULT = Path("/workspace/scratch/3f6a885bb83c/hepta-research/experiments/multimodal_output_portfolio/joint_hepta_20261029/v3/ndu_llm_confirmation")
WATCH = ("confirmation.py", "transport.py", "tasks.py", "contracts.py", "ledger.py", "policy.py", "schema.json", "test_confirmation.py", "test_transport.py", "test_tasks.py", "test_gate_contracts.py", "test_ledger.py", "test_policy.py", "evidence/qualification-original.json")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def fingerprint(root):
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() if (root / name).is_file() else None for name in WATCH}


def fixture(repeats=1, members_per_cluster=1):
    """Independent declarative fixture, intentionally synthetic and unauthenticated.

    Statistical outcomes are constructed here independently of target fixtures.
    expand_v2 below encodes the declared stable intent/terminal/meter contract
    with independent canonical hashes; no target ledger constructor is called.
    """
    evidence = {}

    def artifact(value):
        sha = digest(value)
        evidence[sha] = {"json": value}
        return sha

    proof = artifact({"kind": "independent_synthetic_review_only", "authentic_model_or_bill": False})
    identity = {"kind": "frozen_llm", "model_id": "INDEPENDENT-SYNTHETIC-NOT-A-MODEL", "revision": "fixture-v1", "evidence_sha256": proof}
    arms = {a: {"source_sha256": artifact({"synthetic_method": a})} for a in ARMS}
    p = {"schema": "ndu.confirmation.protocol.v1", "status": "FROZEN", "frozen_at": "2026-01-01T00:00:00+00:00",
         "identity": identity, "arms": arms, "transport_sha256": proof, "decoding_sha256": proof,
         "design": {**{k: proof for k in ("split_sha256", "order_sha256", "price_card_sha256", "cost_cap_evidence_sha256", "strong_planner_qualification_sha256")},
                    **{k: True for k in ("source_independence_attested", "shared_shocks_clustered", "state_reset", "hard_cost_cap_enforced")}},
         "alpha": .05, "repeats": repeats, "currency": "USD", "currency_to_score": 1., "deployment_volume": 1000,
         "precision_h": 1., "deadline_seconds": 2., "time_price": 0., "max_service_cost": .2, "gain_min": 0.,
         "families": [{"id": f, "provenance_sha256": artifact({"synthetic_family": f})} for f in ("family-a", "family-b")],
         "tasks": [], "comparisons": [{"id": f+":"+str(a), "family": f, "baseline": a} for f in ("family-a", "family-b") for a in ARMS[:-1]+(None,)],
         "M": 10, "lifecycle_plan": [{"id": c, "category": c, "accounting": "actual", "allocation": {a: .2 for a in ARMS}} for c in CATEGORIES]}
    for family in ("family-a", "family-b"):
        for cluster in range(16):
            group = f"{family}/source-{cluster}"
            for member in range(members_per_cluster):
                tid = f"{group}/task-{member}"
                p["tasks"].append({"id": tid, "sha256": artifact({"synthetic_task": tid}), "verifier_sha256": proof,
                                   "family": family, "cluster": group, "source_groups": [group], "weight": 1.})
    phash = digest(p)
    records, events, invoices = [], [], []
    for task in p["tasks"]:
        for arm in ARMS:
            for repeat in range(repeats):
                prefix = f"{task['id']}/{arm}/{repeat}"
                quality = float(arm == "full")
                rids = [prefix+"/model", prefix+"/verify", prefix+"/host"]
                records.append({"schema": "ndu.confirmation.episode.v1", "task_id": task["id"], "arm": arm, "repeat": repeat,
                                "protocol_sha256": phash, "task_sha256": task["sha256"], "verifier_sha256": proof,
                                "method_sha256": arms[arm]["source_sha256"], "started_at": "2026-02-01T00:00:00+00:00",
                                "wall_seconds": 1., "quality": quality, "terminal": "delivered", "stop_requested": True,
                                "delivery_at_seconds": .5, "request_ids": rids,
                                "contract": {k: p[k] for k in ("deadline_seconds", "currency_to_score", "time_price")}})
                for stage, (kind, t0, t1) in enumerate((("model", 1., 1.1), ("verifier", 1.1, 1.2), ("host_envelope", 1., 2.))):
                    event = {"schema": "ndu.request.v1", "request_id": rids[stage], "kind": kind, "task_id": task["id"], "arm": arm, "repeat": repeat,
                             "protocol_sha256": phash, "started_at": "2026-02-01T00:00:00+00:00", "finished_at": "2026-02-01T00:00:01+00:00",
                             "started_monotonic": t0, "finished_monotonic": t1, "wall_seconds": t1-t0,
                             "status": "metered" if kind == "host_envelope" else "ok", "usage": None, "actual_amount": None,
                             "provider_request_sha256": None, "reconciliation_status": "pending"}
                    if kind == "model":
                        event.update(identity_kind="frozen_llm", expected_identity_sha256=digest(identity), identity_status="match",
                                     observed_identity_sha256=digest({k: identity[k] for k in ("model_id", "revision")}),
                                     transport_sha256=proof, usage={"input_tokens": 2, "output_tokens": 1}, usage_status="reported")
                    if kind == "verifier":
                        event["verified_quality"] = quality
                    events.append(event)
                    bill = {"request_id": rids[stage], "status": "final", "amount": 0., "currency": "USD",
                            "invoice_sha256": artifact({"synthetic_invoice_line": rids[stage], "amount": 0.}), "line_id": rids[stage],
                            "usage": event["usage"], "provider_request_sha256": None}
                    if kind == "model":
                        bill["identity_sha256"] = digest(identity)
                    invoices.append(bill)
    lifecycle = [{"charge_id": c, "status": "final", "amount": 0., "currency": "USD",
                  "invoice_sha256": artifact({"synthetic_setup": c, "amount": 0.}), "line_id": c} for c in CATEGORIES]
    return expand_v2({"protocol": p, "records": records, "events": events, "invoices": invoices, "lifecycle_invoices": lifecycle, "evidence": evidence})


def expand_v2(bundle):
    raw = []
    for original in bundle["events"]:
        e = copy.deepcopy(original)
        e["schema"] = "ndu.request.v2"
        if e["kind"] == "host_envelope":
            e.update(phase="meter", usage_status="not_applicable")
            raw.append(e)
            continue
        expected = e.get("expected_identity_sha256", digest({"review": "local-verifier"}))
        binding = {k: e[k] for k in ("schema", "request_id", "kind", "task_id", "arm", "repeat", "protocol_sha256")}
        binding.update(request_sha256=digest({"synthetic_payload_for": e["request_id"]}), transport_sha256=bundle["protocol"]["transport_sha256"],
                       expected_identity_sha256=expected, identity_kind="frozen_llm" if e["kind"] == "model" else "local_tool",
                       timeout_seconds=1., deadline_monotonic=e["started_monotonic"]+1.)
        intent = {**binding, "phase": "intent", "status": "pending", "prepared_at": e["started_at"], "prepared_monotonic": e["started_monotonic"]}
        e.update(binding)
        e.update(phase="terminal", intent_sha256=digest(intent), intent_finished_monotonic=e["started_monotonic"]+.01,
                 dispatched=True, dispatch_monotonic=e["started_monotonic"]+.02, response_received=True)
        if e["kind"] != "model":
            e.update(identity_status="not_applicable", observed_identity_sha256=None, usage_status="not_applicable")
        raw.extend((intent, e))
    bundle["events"] = raw
    return bundle


def refresh_intents(bundle):
    intents = {e["request_id"]: e for e in bundle["events"] if e.get("phase") == "intent" and "request_id" in e}
    for e in bundle["events"]:
        if e.get("phase") == "terminal" and e.get("request_id") in intents:
            e["intent_sha256"] = digest(intents[e["request_id"]])


def failed_fixture(dispatched=True):
    b = fixture()
    record = b["records"][0]
    rid, verify_id = record["request_ids"][:2]
    record.update(terminal="model_failure", quality=0., delivery_at_seconds=None)
    record["request_ids"].remove(verify_id)
    b["events"] = [e for e in b["events"] if e["request_id"] != verify_id]
    b["invoices"] = [e for e in b["invoices"] if e["request_id"] != verify_id]
    intent = next(e for e in b["events"] if e["request_id"] == rid and e["phase"] == "intent")
    terminal = next(e for e in b["events"] if e["request_id"] == rid and e["phase"] == "terminal")
    terminal.update(status="timeout", response_received=False, identity_status="unobserved", observed_identity_sha256=None,
                    usage=None, usage_status="unknown", dispatched=dispatched, dispatch_monotonic=1.02 if dispatched else None)
    for e in (intent, terminal):
        e.update(timeout_seconds=.1, deadline_monotonic=1.1)
    if not dispatched:
        terminal["intent_finished_monotonic"] = 1.1
    bill = next(e for e in b["invoices"] if e["request_id"] == rid)
    bill["usage"] = {"input_tokens": 0, "output_tokens": 0}
    receipt = {"schema": "ndu.provider.identity_receipt.v1", "request_id": rid,
               "invoice_sha256": bill["invoice_sha256"], "issuer": "INDEPENDENT-SYNTHETIC-ONLY",
               **{k: b["protocol"]["identity"][k] for k in ("model_id", "revision")}}
    ref = digest(receipt)
    bill["identity_evidence_sha256"] = ref
    b["evidence"][ref] = {"json": receipt}
    refresh_intents(b)
    return b


def rebind(bundle):
    p = bundle["protocol"]
    try:
        phash = digest(p)
    except (TypeError, ValueError):
        return  # Leave malformed numeric input for the target's fail-closed path.
    for item in bundle["records"]+bundle["events"]:
        item["protocol_sha256"] = phash
    tasks = {t["id"]: t for t in p.get("tasks", []) if "id" in t}
    for record in bundle["records"]:
        task = tasks.get(record["task_id"], {})
        for field in ("sha256", "verifier_sha256"):
            if field in task:
                record["task_sha256" if field == "sha256" else field] = task[field]
    refresh_intents(bundle)


def set_path(bundle, path, value):
    target = bundle
    for component in path[:-1]:
        target = target[component]
    target[path[-1]] = value


def delete_path(bundle, path):
    target = bundle
    for component in path[:-1]:
        target = target[component]
    del target[path[-1]]


def run_suite(evaluate):
    rows = []
    control = evaluate(**fixture())
    if control.get("status") != "PASS":
        return {"status": "FIXTURE_ADAPTATION_REQUIRED", "positive_control": control,
                "checks": [], "note": "No negative case is certified when the independent positive control is incompatible."}

    def record(name, b, expected="HOLD", predicate=None):
        try:
            output = evaluate(**b)
            okay = output.get("status") == expected and (predicate(output) if predicate else True)
            rows.append({"name": name, "passed": bool(okay), "expected": expected, "actual": output.get("status"), "reasons": output.get("reasons", [])})
        except Exception as exc:
            rows.append({"name": name, "passed": False, "expected": expected, "actual": "EXCEPTION", "exception_type": type(exc).__name__})

    def mutation(name, mutate, expected="HOLD", predicate=None):
        b = fixture()
        mutate(b)
        rebind(b)
        record(name, b, expected, predicate)

    # Independent arithmetic and grouping, without target test fixtures.
    expected_radius = 1.2*math.sqrt(2*math.log(10/.05)/16)
    record("independent_primary_radius", fixture(), "PASS", lambda r: all(c["n_clusters"] == 16 and math.isclose(c["radius"], expected_radius*(1 if c["baseline"] else .5), rel_tol=1e-12) for c in r["comparisons"]))
    for label, b in (("repeats_do_not_inflate_n", fixture(repeats=2)), ("members_do_not_inflate_n", fixture(members_per_cluster=2))):
        record(label, b, "PASS", lambda r: all(c["n_clusters"] == 16 and math.isclose(c["radius"], expected_radius*(1 if c["baseline"] else .5), rel_tol=1e-12) for c in r["comparisons"]))

    for path, value in ((["records", 0, "quality"], False), (["records", 0, "repeat"], False),
                        (["events", 0, "repeat"], False), (["events", 3, "verified_quality"], False),
                        (["records", 0, "contract", "currency_to_score"], True), (["records", 0, "contract", "time_price"], False),
                        (["invoices", 0, "amount"], False), (["lifecycle_invoices", 0, "amount"], False),
                        (["events", 1, "wall_seconds"], False), (["invoices", 0, "line_id"], True),
                        (["lifecycle_invoices", 0, "line_id"], True)):
        mutation("strict_type:"+"/".join(map(str, path)), lambda b, path=path, value=value: set_path(b, path, value))
    for raw in ({}, True, {"input_tokens": True, "output_tokens": False}, {"input_tokens": 1, "output_tokens": 0, "cached_input_tokens": 2}):
        mutation("invalid_usage:"+repr(raw), lambda b, raw=raw: (b["events"][1].update(usage=raw), b["invoices"][0].update(usage=None)))
    for value in (float("nan"), float("inf"), -float("inf")):
        mutation("nonfinite_quality:"+str(value), lambda b, value=value: b["records"][0].update(quality=value))

    required = {
        "records": ("schema", "task_id", "arm", "repeat", "protocol_sha256", "task_sha256", "verifier_sha256", "method_sha256", "started_at", "wall_seconds", "quality", "terminal", "stop_requested", "delivery_at_seconds", "request_ids", "contract"),
        "events": ("schema", "request_id", "kind", "task_id", "arm", "repeat", "protocol_sha256", "started_at", "finished_at", "started_monotonic", "finished_monotonic", "wall_seconds", "status"),
        "invoices": ("request_id", "status", "amount", "currency", "invoice_sha256", "line_id"),
        "lifecycle_invoices": ("charge_id", "status", "amount", "currency", "invoice_sha256", "line_id")}
    # Do not rebind after deleting a field: rebuilding would repair that mutation.
    for collection, fields in required.items():
        for field in fields:
            b = fixture()
            delete_path(b, (collection, 1 if collection == "events" else 0, field))
            record("missing:"+collection+"/"+field, b)

    for key in ("identity_status", "observed_identity_sha256"):
        mutation("successful_identity_missing:"+key, lambda b, key=key: b["events"][1].pop(key))
    mutation("observed_version_mismatch", lambda b: b["events"][1].update(observed_identity_sha256="0"*64))
    mutation("unknown_invoice_status", lambda b: b["invoices"][0].update(status="pending"))
    mutation("missing_invoice", lambda b: b["invoices"].pop())
    mutation("missing_record", lambda b: b["records"].pop())
    mutation("duplicate_record", lambda b: b["records"].append(copy.deepcopy(b["records"][0])))
    mutation("duplicate_invoice", lambda b: b["invoices"].append(copy.deepcopy(b["invoices"][0])))
    mutation("duplicate_event", lambda b: b["events"].append(copy.deepcopy(b["events"][0])))
    mutation("all_success_claims_have_only_model_timeouts", lambda b: [e.update(status="timeout") for e in b["events"] if e["kind"] == "model" and e["phase"] == "terminal"])
    mutation("all_evidence_missing", lambda b: b.update(evidence={}))
    mutation("source_split_into_clusters", lambda b: b["protocol"]["tasks"][1].update(source_groups=b["protocol"]["tasks"][0]["source_groups"]))
    mutation("empty_source_group", lambda b: b["protocol"]["tasks"][0].update(source_groups=[""]))
    mutation("duplicate_content", lambda b: b["protocol"]["tasks"][1].update(sha256=b["protocol"]["tasks"][0]["sha256"]))
    mutation("underdeclared_M", lambda b: b["protocol"].update(M=1))
    mutation("mechanism_without_registered_comparison", lambda b: b["protocol"].update(mechanism_claims=["no_paid_identification"]))
    mutation("precision_without_enough_clusters", lambda b: b["protocol"].update(precision_h=.01))
    mutation("pending_lifecycle_bill", lambda b: b["lifecycle_invoices"][0].update(status="pending"))
    mutation("missing_lifecycle_bill", lambda b: b["lifecycle_invoices"].pop())
    mutation("service_lifecycle_double_count", lambda b: b["lifecycle_invoices"][0].update(invoice_sha256=b["invoices"][0]["invoice_sha256"], line_id=b["invoices"][0]["line_id"]))

    def future(b, arm, lower, upper):
        b["protocol"]["lifecycle_plan"].append({"id": "future-review", "category": "reporting", "accounting": "frozen_bound",
              "allocation": {arm: 1.}, "lower_currency": lower, "upper_currency": upper,
              "bound_evidence_sha256": b["protocol"]["identity"]["evidence_sha256"]})
    mutation("baseline_upper_bound_cannot_improve_contrast", lambda b: future(b, "direct_stop", 0., 100000.), "PASS",
             lambda r: all(c["lifecycle_charge_upper"] == 0 for c in r["comparisons"]))
    mutation("candidate_upper_bound_is_subtracted", lambda b: future(b, "full", 0., 1000.))
    mutation("negative_future_cost_rejected", lambda b: future(b, "full", -1., 0.))
    # New dual-phase ledger invariants, all within complete independently built bundles.
    for label, mutate in (
        ("unfinished_intent_with_final_zero_invoice", lambda b: b["events"].pop(1)),
        ("terminal_without_intent", lambda b: b["events"].pop(0)),
        ("duplicate_intent", lambda b: b["events"].insert(0, copy.deepcopy(b["events"][0]))),
        ("duplicate_terminal", lambda b: b["events"].insert(2, copy.deepcopy(b["events"][1]))),
        ("intent_terminal_request_hash_mismatch", lambda b: b["events"][1].update(request_sha256="0"*64)),
        ("success_without_dispatch", lambda b: b["events"][1].update(dispatched=False, dispatch_monotonic=None)),
        ("success_without_response", lambda b: b["events"][1].update(response_received=False)),
        ("dispatch_after_recorded_finish", lambda b: b["events"][1].update(dispatch_monotonic=b["events"][1]["finished_monotonic"]+.01)),
        ("intent_admission_after_finish", lambda b: b["events"][1].update(intent_finished_monotonic=1.2)),
        ("dispatch_at_deadline", lambda b: b["events"][1].update(dispatch_monotonic=b["events"][1]["deadline_monotonic"]))):
        mutation(label, mutate)
    b = fixture(); b["events"][0], b["events"][1] = b["events"][1], b["events"][0]
    record("terminal_before_intent", b)
    b = fixture(); b["events"][1]["intent_sha256"] = "0"*64
    record("wrong_intent_digest", b)
    b = fixture(); b["invoices"][0]["amount"] = .05
    record("intent_terminal_billed_once", b, "PASS", lambda r: math.isclose(r["per_task"][0]["utility"]["direct_stop"], -.05, abs_tol=1e-12))
    def reverse_final_dependency(b):
        r = next(r for r in b["records"] if r["arm"] == "full")
        model, verifier, meter = r["request_ids"]
        selected = {rid: [e for e in b["events"] if e["request_id"] == rid] for rid in r["request_ids"]}
        for rid, start in ((verifier, 1.), (model, 1.1)):
            intent, terminal = selected[rid]
            intent.update(prepared_monotonic=start, deadline_monotonic=start+1.)
            terminal.update(started_monotonic=start, finished_monotonic=start+.1, wall_seconds=.1,
                            intent_finished_monotonic=start+.01, dispatch_monotonic=start+.02, deadline_monotonic=start+1.)
        first = next(i for i, e in enumerate(b["events"]) if e["request_id"] == model)
        b["events"][first:first+5] = selected[verifier]+selected[model]+selected[meter]
        r["request_ids"] = [verifier, model, meter]
    mutation("verifier_cannot_precede_final_successful_model", reverse_final_dependency)
    def wrong_raw_order(b):
        b["events"][:5] = b["events"][2:4]+b["events"][:2]+b["events"][4:5]
    mutation("raw_completion_order_must_match_episode_order", wrong_raw_order)
    def meter_before_work(b):
        r = b["records"][0]
        r["request_ids"] = [r["request_ids"][2]]+r["request_ids"][:2]
        b["events"][:5] = b["events"][4:5]+b["events"][:4]
    mutation("host_meter_must_follow_completed_work", meter_before_work)
    mutation("successful_response_after_its_request_deadline", lambda b: (b["events"][0].update(deadline_monotonic=1.05), b["events"][1].update(deadline_monotonic=1.05)))
    mutation("deadline_cannot_exceed_declared_request_timeout", lambda b: (b["events"][0].update(deadline_monotonic=2.5), b["events"][1].update(deadline_monotonic=2.5)))
    mutation("fractional_deployment_volume_rejected", lambda b: b["protocol"].update(deployment_volume=1.5))
    mutation("boolean_deployment_volume_rejected", lambda b: b["protocol"].update(deployment_volume=True))
    for dispatched in (False, True):
        good = failed_fixture(dispatched)
        record("valid_reconciled_timeout_dispatched_"+str(dispatched), good, "PASS")
        for field in ("stop_requested", "contract", "request_ids"):
            b = copy.deepcopy(good); b["records"][0].pop(field)
            record("failed_episode_missing_"+field+"_"+str(dispatched), b)
        b = copy.deepcopy(good); b["invoices"][0].pop("identity_evidence_sha256")
        record("unobserved_identity_missing_receipt_"+str(dispatched), b)
        for field in ("request_id", "invoice_sha256", "revision"):
            b = copy.deepcopy(good)
            ref = b["invoices"][0]["identity_evidence_sha256"]
            receipt = copy.deepcopy(b["evidence"][ref]["json"])
            receipt[field] = "0"*64 if field == "invoice_sha256" else "wrong-binding"
            ref = digest(receipt); b["evidence"][ref] = {"json": receipt}; b["invoices"][0]["identity_evidence_sha256"] = ref
            record("unobserved_identity_wrong_receipt_"+field+"_"+str(dispatched), b)
    return {"status": "PASS" if all(row["passed"] for row in rows) else "FAIL", "positive_control": {"status": control["status"], "synthetic_only": True},
            "checks": rows, "check_count": len(rows), "passed": sum(row["passed"] for row in rows), "failed": sum(not row["passed"] for row in rows)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, default=TARGET_DEFAULT)
    parser.add_argument("--execute-after-stable-notice", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.execute_after_stable_notice:
        print(json.dumps({"status": "NOT_RUN", "reason": "Awaiting parent stable-source notice; opt-in execution required."}))
        return 0
    if args.output is None or args.output.exists():
        raise SystemExit("Provide a new --output path; existing review receipts are never overwritten.")
    before = fingerprint(args.target)
    sys.path.insert(0, str(args.target.parent))
    confirmation = importlib.import_module(args.target.name+".confirmation")
    report = run_suite(confirmation.evaluate)
    after = fingerprint(args.target)
    report.update(schema="ndu.independent.local-review.v1", reviewed_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                  target=str(args.target.resolve()), source_sha256_before=before, source_sha256_after=after,
                  source_stable=before == after, scope="Synthetic engineering acceptance only; no real model, billing authentication, or external scientific review.",
                  runtime_durable_and_callback_checks="Raw bundle pairing tested; dispatch fault injection and callback binding are in review_runtime.py")
    if before != after:
        report["status"] = "INVALIDATED_SOURCE_CHANGED"
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"status": report["status"], "check_count": report.get("check_count", 0), "failed": report.get("failed", 0), "output": str(args.output)}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
