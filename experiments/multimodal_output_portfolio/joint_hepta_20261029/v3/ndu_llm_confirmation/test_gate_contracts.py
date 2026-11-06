"""Regression counterexamples from independent review; all records remain synthetic."""
import copy
import json
from pathlib import Path
import unittest
from .confirmation import evaluate
from .contracts import digest
from .test_confirmation import synthetic, rebind


def terminal(bundle, kind="model", full=False):
    return next(e for e in bundle["events"] if e["phase"] == "terminal" and e["kind"] == kind
                and (not full or e["arm"] == "full"))


def attach_identity_receipt(bundle, event):
    bill = next(b for b in bundle["invoices"] if b["request_id"] == event["request_id"])
    receipt = {"schema": "ndu.provider.identity_receipt.v1", "request_id": event["request_id"],
               "invoice_sha256": bill["invoice_sha256"], "issuer": "SYNTHETIC_PROVIDER_NOT_REAL",
               **{k: bundle["protocol"]["identity"][k] for k in ("model_id", "revision")}}
    bill.update(identity_sha256=event["expected_identity_sha256"], identity_evidence_sha256=digest(receipt))
    bundle["evidence"][digest(receipt)] = {"json": receipt}
    return bill, receipt


class ContractRegressions(unittest.TestCase):
    def assert_hold(self, bundle):
        result = evaluate(**bundle)
        self.assertEqual(result["status"], "HOLD", result)
        return result

    def test_booleans_are_not_quality_cost_repeat_or_deployment_counts(self):
        for field in ("quality", "repeat", "currency_to_score", "time_price", "deployment_bool", "deployment_fraction", "deployment_float"):
            b = synthetic()
            with self.subTest(field=field):
                if field == "quality":
                    terminal(b, "verifier", full=True)["verified_quality"] = True
                elif field == "repeat":
                    terminal(b)["repeat"] = False
                elif field.startswith("deployment"):
                    b["protocol"]["deployment_volume"] = {"deployment_bool": True, "deployment_fraction": .5,
                                                           "deployment_float": 1.}[field]
                    rebind(b)
                else:
                    b["records"][0]["contract"][field] = field == "currency_to_score"
                self.assert_hold(b)

    def test_every_declared_required_field_is_enforced_including_failure_records(self):
        base = synthetic()
        base["records"][0].update(terminal="model_failure", quality=0., delivery_at_seconds=None)
        self.assertEqual(evaluate(**base)["status"], "PASS")
        schema = json.loads(Path(__file__).with_name("schema.json").read_text())["$defs"]
        def required(name):
            node = schema[name]
            keys = set(node.get("required", []))
            for parent in node.get("allOf", []):
                if "$ref" in parent:
                    keys.update(required(parent["$ref"].rsplit("/", 1)[1]))
            return keys
        selectors = {"protocol": lambda b: b["protocol"], "episode": lambda b: b["records"][0],
                     "intent": lambda b: b["events"][0], "terminal": lambda b: terminal(b),
                     "meter": lambda b: next(e for e in b["events"] if e["phase"] == "meter"),
                     "invoice": lambda b: b["invoices"][0], "lifecycle_invoice": lambda b: b["lifecycle_invoices"][0],
                     "task": lambda b: b["protocol"]["tasks"][0]}
        for name, select in selectors.items():
            for field in required(name):
                with self.subTest(definition=name, missing=field):
                    b = copy.deepcopy(base)
                    del select(b)[field]
                    if name in ("protocol", "task"):
                        rebind(b)
                    self.assert_hold(b)

    def test_source_groups_cluster_and_invoice_keys_have_strict_types(self):
        for target in ("groups_string", "empty_group", "bool_cluster", "service_bool", "service_empty", "life_int", "life_empty"):
            b = synthetic()
            with self.subTest(target=target):
                if target == "groups_string": b["protocol"]["tasks"][0]["source_groups"] = "unique-z"
                elif target == "empty_group": b["protocol"]["tasks"][0]["source_groups"] = [""]
                elif target == "bool_cluster": b["protocol"]["tasks"][0]["cluster"] = True
                elif target.startswith("service"): b["invoices"][0]["line_id"] = True if target.endswith("bool") else ""
                else: b["lifecycle_invoices"][0]["line_id"] = 1 if target.endswith("int") else ""
                rebind(b)
                self.assert_hold(b)

    def test_ok_model_cannot_borrow_identity_from_final_invoice(self):
        for mutation in ("missing_status", "missing_observation", "wrong_observation", "unobserved", "explicit_mismatch", "received_failure"):
            b = synthetic()
            e = terminal(b)
            attach_identity_receipt(b, e)
            with self.subTest(mutation=mutation):
                if mutation == "missing_status": del e["identity_status"]
                elif mutation == "missing_observation": del e["observed_identity_sha256"]
                elif mutation == "wrong_observation": e["observed_identity_sha256"] = "0"*64
                elif mutation == "explicit_mismatch": e.update(identity_status="mismatch", status="identity_mismatch")
                else:
                    e.update(identity_status="unobserved", observed_identity_sha256=None, response_received=False)
                    if mutation == "received_failure": e.update(status="failure", response_received=True)
                self.assert_hold(b)

    def test_no_unexecuted_attempt_can_have_a_success_or_observed_response(self):
        for kind in ("model", "verifier"):
            for change in ("undispatched_ok", "response_without_dispatch", "ok_without_response"):
                b = synthetic()
                e = terminal(b, kind)
                with self.subTest(kind=kind, change=change):
                    if change == "ok_without_response": e["response_received"] = False
                    else:
                        e.update(dispatched=False, dispatch_monotonic=None)
                        if change == "response_without_dispatch": e["status"] = "failure"
                    self.assert_hold(b)
        b = synthetic()
        e = terminal(b)
        e.update(status="timeout", dispatched=False, dispatch_monotonic=None, response_received=False,
                 identity_status="unobserved", observed_identity_sha256=None, usage=None, usage_status="unknown")
        b["records"][0].update(terminal="model_failure", quality=0., delivery_at_seconds=None)
        attach_identity_receipt(b, e)
        self.assertEqual(evaluate(**b)["status"], "PASS")  # Synthetic zero-bill pre-dispatch timeout, still retained.

    def test_no_response_failure_requires_substantive_request_bound_identity_receipt(self):
        b = synthetic()
        e = terminal(b)
        e.update(status="timeout", identity_status="unobserved", observed_identity_sha256=None,
                 response_received=False, usage=None, usage_status="unknown")
        b["records"][0].update(terminal="model_failure", quality=0., delivery_at_seconds=None)
        self.assert_hold(b)
        bill, receipt = attach_identity_receipt(b, e)
        self.assertEqual(evaluate(**b)["status"], "PASS")
        for field in ("request_id", "revision", "invoice_sha256"):
            bad = copy.deepcopy(b)
            material = {**receipt, field: "0"*64 if field == "invoice_sha256" else "wrong"}
            new_hash = digest(material)
            bad["invoices"][0]["identity_evidence_sha256"] = new_hash
            bad["evidence"][new_hash] = {"json": material}
            self.assert_hold(bad)
        del b["evidence"][bill["identity_evidence_sha256"]]
        self.assert_hold(b)

    def test_intent_pairing_missing_duplicate_mismatch_and_orphans_fail_closed(self):
        for mutation in ("no_intent", "unfinished", "duplicate_intent", "duplicate_terminal", "wrong_order", "context", "orphan"):
            b = synthetic()
            with self.subTest(mutation=mutation):
                if mutation == "no_intent": b["events"].pop(0)
                elif mutation == "unfinished": b["events"].pop(1)
                elif mutation == "duplicate_intent": b["events"].insert(1, copy.deepcopy(b["events"][0]))
                elif mutation == "duplicate_terminal": b["events"].insert(2, copy.deepcopy(b["events"][1]))
                elif mutation == "wrong_order": b["events"][0], b["events"][1] = b["events"][1], b["events"][0]
                elif mutation == "context":
                    b["events"][0]["arm"] = "full"
                    b["events"][1]["intent_sha256"] = digest(b["events"][0])
                else:
                    intent, end = copy.deepcopy(b["events"][:2])
                    intent["request_id"] = end["request_id"] = "unassigned"
                    end["intent_sha256"] = digest(intent)
                    b["events"].extend((intent, end))
                    b["invoices"].append({**b["invoices"][0], "request_id": "unassigned", "line_id": "unassigned"})
                self.assert_hold(b)

    def test_dispatch_and_success_must_fit_the_recorded_request_interval(self):
        for kind in ("model", "verifier"):
            for change in ("dispatch_after_finish", "success_after_deadline", "deadline_exceeds_timeout"):
                b = synthetic()
                e = terminal(b, kind)
                intent = next(x for x in b["events"] if x["phase"] == "intent" and x["request_id"] == e["request_id"])
                with self.subTest(kind=kind, change=change):
                    if change == "dispatch_after_finish":
                        e["dispatch_monotonic"] = e["finished_monotonic"]+.05
                    elif change == "success_after_deadline":
                        e["deadline_monotonic"] = intent["deadline_monotonic"] = e["finished_monotonic"]-.01
                    else:
                        e["timeout_seconds"] = intent["timeout_seconds"] = .5
                    rebind(b)
                    self.assert_hold(b)

    def test_verification_cannot_precede_final_model_or_reorder_raw_episode_history(self):
        for change in ("verifier_first", "record_order_only"):
            b = synthetic()
            r = next(r for r in b["records"] if r["arm"] == "full")
            model, verifier, host = r["request_ids"]
            pairs = {rid: [e for e in b["events"] if e["request_id"] == rid] for rid in (model, verifier)}
            for rid, start in ((verifier, 1.), (model, 1.1)):
                intent, end = pairs[rid]
                intent["prepared_monotonic"] = start
                end.update(started_monotonic=start, finished_monotonic=start+.1,
                           intent_finished_monotonic=start+.001, dispatch_monotonic=start+.002)
            r["request_ids"] = [verifier, model, host]
            if change == "verifier_first":
                b["events"] = pairs[verifier]+pairs[model]+[e for e in b["events"] if e["request_id"] not in pairs]
            rebind(b)
            self.assert_hold(b)

    def test_a_valid_intent_terminal_pair_is_charged_exactly_once(self):
        b = synthetic()
        b["invoices"][0]["amount"] = .1
        outcome = evaluate(**b)
        self.assertEqual(outcome["status"], "PASS", outcome["reasons"])
        self.assertAlmostEqual(outcome["per_task"][0]["utility"]["direct_stop"], -.1)


if __name__ == "__main__":
    unittest.main()
