"""Serialized finite-selector fixtures connect verified bytes to real admission.

These are integration controls, not a language task or a measured model benefit.
Resource vectors are explicit synthetic fixtures; no device cost claim is made.
"""

import json
from pathlib import Path
import tempfile
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from admission import Case, MatchedEvaluator, Protocol, Run, budget_digest
from admission_test_support import fixture_cost_protocol, fixture_ledger, fixture_registration
from authority import COMPONENTS, Authority, GateDecision, Rejected, bundle, canonical, digest, public, sign


class IntegratedAdmissionTests(unittest.TestCase):
    def test_verified_parameter_bytes_control_activation(self):
        keys = [Ed25519PrivateKey.generate() for _ in range(3)]
        service_key, admin, owner = keys
        protocol = fixture_cost_protocol(Protocol("serialized-fixture-v1", True, 1000, .05, 1, .1, 30, 1.,
                            ("old", "new"), (("train_cpu_s", 1.),), ()))
        cases = [Case(str(i), str(i), "old" if i < 2000 else "new",
                      "old" if i < 2000 else "new", i, i) for i in range(4000)]
        known = {}
        reports = []

        def load_run(identifier, manifest, verified):
            # Load the exact bytes just checked by authority, not a client model label.
            if verified["runtime"] != b"finite-selector-v1":
                raise Rejected("unsupported fixture runtime")
            for component, raw in verified.items():
                if digest(raw) != manifest["components"][component]:
                    raise Rejected("loader bytes changed")
            parameters = json.loads(verified["model"])
            return Run(identifier, manifest["components"]["memory"],
                       manifest["components"]["memory"], "copy-executor-v1",
                       budget_digest(protocol), lambda query: parameters.get(query),
                       "fixture-encoder", "fixture-decoder", "fixture-tools")

        def costs(evaluator, model, verified):
            ledger = fixture_ledger(evaluator, model)
            if json.loads(verified["model"]).get("unmeasured_energy"):
                ledger["resources"]["energy_joules"] = None
            return ledger

        def gate(identifier, parents, manifest, verified):
            if not parents:
                # Only this pre-registered exact baseline can bootstrap the fixture.
                approved = identifier == original["id"]
                return GateDecision(identifier, parents, approved, digest(b"bootstrap-fixture"))
            prior = known[parents[0]]
            prior_bytes = {k: bytes.fromhex(v) for k, v in prior["objects"].items()}
            candidate = load_run(identifier, manifest, verified)
            incumbent = load_run(parents[0], prior["manifest"], prior_bytes)
            evaluator = MatchedEvaluator(cases,
                        lambda: (lambda choice, payload: payload if choice == "copy" else None),
                        protocol, registration=fixture_registration(cases, protocol, candidate, incumbent))
            report = evaluator.evaluate(candidate, incumbent,
                     costs(evaluator, candidate, verified), costs(evaluator, incumbent, prior_bytes),
                     manifest=dict(manifest, bundle=identifier, memory=manifest["components"]["memory"]))
            reports.append(report)
            return GateDecision(identifier, parents, report["approved"], report["evidence"])

        with tempfile.TemporaryDirectory() as tmp:
            service = Authority(Path(tmp) / "authority.sqlite", service_key, public(admin), gate)
            def call(key, operation, args):
                return service.apply(sign(key, service.identity, operation, args))["result"]
            source = call(admin, "source", dict(scope="fixture", id="records", expected_revision=0,
                                                active=True, body="same-input-memory"))
            dependencies = [{k: source[k] for k in ("id", "revision", "hash")}]
            def artifact(model):
                objects = {k: ("fixture-" + k).encode() for k in COMPONENTS}
                objects.update(model=canonical(model), memory=b"same-input-memory", runtime=b"finite-selector-v1")
                return bundle("fixture", ["record"], [public(owner)], dependencies, objects)
            original = artifact({"old": "copy", "new": "miss"})
            known[original["id"]] = original
            state = call(admin, "create", dict(cell="cell", owner=public(owner), bundle=original))
            good = artifact({"old": "copy", "new": "copy"})
            args = dict(cell="cell", epoch=state["epoch"], expected=original["id"], bundle=good)
            state = call(owner, "publish", args)
            known[good["id"]] = good
            self.assertTrue(reports[-1]["approved"])
            self.assertEqual(reports[-1]["candidate"], good["id"])
            self.assertEqual(state["bundle"], good["id"])

            bad = artifact({"old": "miss", "new": "copy"})
            with self.assertRaises(Rejected):
                call(owner, "publish", dict(cell="cell", epoch=state["epoch"], expected=good["id"],
                                            bundle=bad, approved=True))
            self.assertFalse(reports[-1]["approved"])
            self.assertIn("retention_not_established:old", reports[-1]["reasons"])
            actual = call(owner, "read", dict(scope="fixture", address="record"))
            self.assertEqual(actual["bundle"]["id"], good["id"])

            unknown = artifact({"old": "copy", "new": "copy", "unmeasured_energy": True})
            with self.assertRaises(Rejected):
                call(owner, "publish", dict(cell="cell", epoch=state["epoch"], expected=good["id"], bundle=unknown))
            self.assertIn("full_cost_net_value_unknown", reports[-1]["reasons"])
            self.assertEqual(call(owner, "read", dict(scope="fixture", address="record"))["bundle"]["id"], good["id"])
            service.close()


if __name__ == "__main__":
    unittest.main()
