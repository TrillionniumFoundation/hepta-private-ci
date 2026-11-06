"""Synthetic gate arithmetic/adversarial inputs. A fabricated PASS is not model evidence."""
import copy
import math
import unittest
from .confirmation import BASELINES, CATEGORIES, evaluate
from .transport import digest


def synthetic():
    proof = {"kind": "synthetic_test_only", "notice": "not model, invoice or independence evidence"}
    artifact = digest(proof)
    arms = {a: {"source_sha256": digest(a)} for a in BASELINES+("full",)}
    p = {"schema": "ndu.confirmation.protocol.v1", "status": "FROZEN", "frozen_at": "2026-01-01T00:00:00+00:00",
         "identity": {"kind": "frozen_llm", "model_id": "SYNTHETIC-NOT-A-MODEL", "revision": "test-v1", "evidence_sha256": artifact},
         "arms": arms, "transport_sha256": artifact, "decoding_sha256": artifact,
         "design": {**{k: artifact for k in ("split_sha256", "order_sha256", "price_card_sha256", "cost_cap_evidence_sha256", "strong_planner_qualification_sha256")},
                    **{k: True for k in ("source_independence_attested", "shared_shocks_clustered", "state_reset", "hard_cost_cap_enforced")}},
         "alpha": .05, "repeats": 1, "currency": "USD", "currency_to_score": 1., "deployment_volume": 1000,
         "precision_h": 1., "deadline_seconds": 2., "time_price": 0., "max_service_cost": .2, "gain_min": 0.,
         "families": [{"id": f, "provenance_sha256": digest(f)} for f in ("f1", "f2")], "tasks": [],
         "comparisons": [{"id": f+":"+str(a), "family": f, "baseline": a} for f in ("f1", "f2") for a in BASELINES+(None,)],
         "M": 10, "lifecycle_plan": [{"id": c, "category": c, "accounting": "actual", "allocation": {a: .2 for a in arms}} for c in CATEGORIES]}
    for f in ("f1", "f2"):
        for i in range(16):
            tid = f+"-"+str(i)
            p["tasks"].append({"id": tid, "sha256": digest(tid), "verifier_sha256": artifact, "family": f,
                               "cluster": tid, "source_groups": [tid], "weight": 1.})
    phash, records, events, invoices = digest(p), [], [], []
    for t in p["tasks"]:
        for a in arms:
            rid = t["id"]+"/"+a
            records.append({"schema": "ndu.confirmation.episode.v1", "task_id": t["id"], "arm": a, "repeat": 0, "protocol_sha256": phash,
                "task_sha256": t["sha256"], "verifier_sha256": t["verifier_sha256"], "method_sha256": arms[a]["source_sha256"],
                "contract": {k: p[k] for k in ("deadline_seconds", "currency_to_score", "time_price")},
                "started_at": "2026-02-01T00:00:00+00:00", "wall_seconds": 1., "quality": float(a == "full"),
                "terminal": "delivered", "stop_requested": True, "delivery_at_seconds": .5, "request_ids": [rid]})
            e = {"schema": "ndu.request.v1", "request_id": rid, "kind": "model", "status": "ok", "task_id": t["id"], "arm": a, "repeat": 0,
                "protocol_sha256": phash, "wall_seconds": .1, "started_monotonic": 1., "finished_monotonic": 1.1,
                "started_at": "2026-02-01T00:00:00+00:00", "finished_at": "2026-02-01T00:00:00.1+00:00",
                "identity_kind": "frozen_llm", "expected_identity_sha256": digest(p["identity"]), "identity_status": "match",
                "observed_identity_sha256": digest({k: p["identity"][k] for k in ("model_id", "revision")}),
                "transport_sha256": p["transport_sha256"], "usage": {"input_tokens": 2, "output_tokens": 1}}
            events.append(e)
            invoices.append({"request_id": rid, "status": "final", "amount": 0., "currency": "USD",
                             "invoice_sha256": artifact, "line_id": rid, "usage": e["usage"]})
    for r, e, bill in list(zip(records, events, invoices)):
        verifier, verifier_bill = copy.deepcopy((e, bill))
        vid = e["request_id"]+"/verify"
        r["request_ids"].append(vid)
        verifier.update(request_id=vid, kind="verifier", status="ok", verified_quality=r["quality"],
                        started_monotonic=1.1, finished_monotonic=1.2)
        verifier_bill.update(request_id=vid, line_id=vid)
        events.append(verifier)
        invoices.append(verifier_bill)
        meter, meter_bill = copy.deepcopy((e, bill))
        rid = e["request_id"]+"/host"
        r["request_ids"].append(rid)
        meter.update(request_id=rid, kind="host_envelope", wall_seconds=1., finished_monotonic=2.)
        meter_bill.update(request_id=rid, line_id=rid)
        events.append(meter)
        invoices.append(meter_bill)
    raw = []
    for e in events:
        e.update(schema="ndu.request.v2", actual_amount=None, reconciliation_status="pending", provider_request_sha256=None)
        if e["kind"] == "host_envelope":
            e.update(phase="meter", status="metered", usage=None, usage_status="not_applicable")
        else:
            e.update(phase="terminal", request_sha256=digest([e["task_id"], e["arm"], e["kind"]]),
                     timeout_seconds=1., deadline_monotonic=2., response_received=True, dispatched=True,
                     intent_finished_monotonic=e["started_monotonic"]+.001,
                     dispatch_monotonic=e["started_monotonic"]+.002,
                     usage_status="reported" if e["kind"] == "model" else "not_applicable")
            if e["kind"] != "model":
                e.update(identity_kind="local_tool", identity_status="not_applicable", observed_identity_sha256=None, usage=None)
            keys = ("request_id", "kind", "task_id", "arm", "repeat", "protocol_sha256", "request_sha256",
                    "transport_sha256", "expected_identity_sha256", "identity_kind", "timeout_seconds", "deadline_monotonic")
            intent = {k: e[k] for k in keys}
            intent.update(schema="ndu.request.v2", phase="intent", status="pending",
                          prepared_at=e["started_at"], prepared_monotonic=e["started_monotonic"])
            e["intent_sha256"] = digest(intent)
            raw.append(intent)
        raw.append(e)
    events = raw
    life = [{"charge_id": c, "status": "final", "amount": 0., "currency": "USD", "invoice_sha256": digest(c), "line_id": c} for c in CATEGORIES]
    evidence = {artifact: {"json": proof}}
    for value in list(arms)+[t["id"] for t in p["tasks"]]+["f1", "f2"]+list(CATEGORIES):
        evidence[digest(value)] = {"json": value}
    return {"protocol": p, "records": records, "events": events, "invoices": invoices,
            "lifecycle_invoices": life, "evidence": evidence}


def rebind(b):
    ph = digest(b["protocol"])
    for r in b["records"]+b["events"]:
        r["protocol_sha256"] = ph
    intents = {e["request_id"]: e for e in b["events"] if e["phase"] == "intent"}
    for e in b["events"]:
        if e["phase"] == "terminal":
            e["intent_sha256"] = digest(intents[e["request_id"]])


class ConfirmationTests(unittest.TestCase):
    def test_exact_hoeffding_radius_and_actual_lifecycle_cost(self):
        b = synthetic()
        result = evaluate(**b)
        self.assertEqual(result["status"], "PASS", result["reasons"])
        self.assertAlmostEqual(result["comparisons"][0]["radius"], 1.2*math.sqrt(2*math.log(200)/16))
        self.assertAlmostEqual(result["comparisons"][4]["radius"], .5*result["comparisons"][0]["radius"])
        b["lifecycle_invoices"][0]["amount"] = 4000
        result = evaluate(**b)
        self.assertEqual(result["status"], "HOLD")
        self.assertGreater(result["comparisons"][4]["service_lower"], 0)
        self.assertLess(result["comparisons"][4]["lifecycle_lower"], 0)

    def test_duplicate_or_split_source_is_not_extra_independence(self):
        for change in ("source", "content", "family"):
            b = synthetic()
            if change == "source":
                b["protocol"]["tasks"][1]["source_groups"] = b["protocol"]["tasks"][0]["source_groups"]
            elif change == "content":
                b["protocol"]["tasks"][1]["sha256"] = b["protocol"]["tasks"][0]["sha256"]
            else:
                b["protocol"]["families"][1]["provenance_sha256"] = b["protocol"]["families"][0]["provenance_sha256"]
            rebind(b)
            self.assertEqual(evaluate(**b)["status"], "HOLD")

    def test_missing_arm_invoice_or_usage_cannot_pass(self):
        for target in ("records", "invoices", "usage", "evidence"):
            b = synthetic()
            if target == "usage":
                next(e for e in b["events"] if e["phase"] == "terminal")["usage"] = b["invoices"][0]["usage"] = None
            elif target == "evidence":
                b["evidence"] = {}
            else:
                b[target].pop()
            self.assertEqual(evaluate(**b)["status"], "HOLD")

    def test_version_cap_late_delivery_and_fixture_fail_closed(self):
        for target in ("version", "cap", "late", "fixture", "nonfinite", "verifier"):
            b = synthetic()
            if target == "version":
                b["events"][0]["expected_identity_sha256"] = "0"*64
            elif target == "cap":
                b["invoices"][0]["amount"] = .200001
            elif target == "late":
                b["records"][0]["delivery_at_seconds"] = 3.
            elif target == "fixture":
                b["protocol"]["identity"]["kind"] = "offline_fixture"
                rebind(b)
            elif target == "verifier":
                next(e for e in b["events"] if e["kind"] == "verifier" and e["phase"] == "terminal")["verified_quality"] = 1.
            else:
                b["records"][0]["quality"] = float("inf")
            self.assertEqual(evaluate(**b)["status"], "HOLD")

    def test_repeat_records_cannot_inflate_n(self):
        b = synthetic()
        b["protocol"]["repeats"] = 2
        for r in list(b["records"]):
            r = copy.deepcopy(r)
            r["repeat"] = 1
            r["request_ids"] = [rid+"/repeat1" for rid in r["request_ids"]]
            b["records"].append(r)
        for e in list(b["events"]):
            e = copy.deepcopy(e)
            e["repeat"] = 1
            e["request_id"] += "/repeat1"
            b["events"].append(e)
        for bill in list(b["invoices"]):
            bill = copy.deepcopy(bill)
            bill["request_id"] += "/repeat1"
            bill["line_id"] += "/repeat1"
            b["invoices"].append(bill)
        rebind(b)
        result = evaluate(**b)
        self.assertEqual(result["status"], "PASS", result["reasons"])
        self.assertTrue(all(c["n_clusters"] == 16 for c in result["comparisons"]))

    def test_failed_attempt_is_retained_and_paid(self):
        b = synthetic()
        r = b["records"][4]
        r.update(terminal="model_failure", quality=0., delivery_at_seconds=None)
        b["invoices"][4]["amount"] = .1
        result = evaluate(**b)
        self.assertEqual(result["status"], "HOLD")
        self.assertAlmostEqual(result["per_task"][0]["utility"]["full"], -.1)

    def test_future_baseline_upper_bound_cannot_artificially_improve_contrast(self):
        b = synthetic()
        charge = {"id": "future", "category": "reporting", "accounting": "frozen_bound",
                  "allocation": {"direct_stop": 1.}, "lower_currency": 0., "upper_currency": 100000.,
                  "bound_evidence_sha256": b["protocol"]["identity"]["evidence_sha256"]}
        b["protocol"]["lifecycle_plan"].append(charge)
        rebind(b)
        result = evaluate(**b)
        self.assertEqual(result["comparisons"][0]["lifecycle_charge_upper"], 0.)

    def test_multiplicity_precision_and_double_charge(self):
        for target in ("M", "precision_h", "double"):
            b = synthetic()
            if target == "M":
                b["protocol"]["M"] = 1
            elif target == "precision_h":
                b["protocol"]["precision_h"] = .01
            else:
                b["lifecycle_invoices"][0].update(invoice_sha256=b["invoices"][0]["invoice_sha256"], line_id=b["invoices"][0]["line_id"])
            rebind(b)
            self.assertEqual(evaluate(**b)["status"], "HOLD")


if __name__ == "__main__":
    unittest.main()
