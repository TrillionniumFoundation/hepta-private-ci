"""Synthetic observer controls only: no real source, model or memory benefit."""

import hashlib
import json
import unittest
from pathlib import Path

from .episodic_causal_contract import (
    BASELINES,
    LAYERS,
    PUBLIC_SELECTOR,
    AuthenticatedObservation,
    admit_protocol,
)
from .episodic_memory import canonical_bytes, digest


class CausalContractTests(unittest.TestCase):
    def setUp(self):
        self.artifacts = {}
        selector_source = self.pin(
            Path(__file__).with_name("candidate_selector.py").read_bytes()
        )
        task = canonical_bytes({"query": "shipping address", "key": "address"})
        retrieval = {
            "query_sha256": hashlib.sha256(task).hexdigest(),
            "source_ids": ["s"],
            "limit": 8,
            "max_context_bytes": 4096,
            "replay_seed": 0,
            "selector_sha256": PUBLIC_SELECTOR,
            "selector_mode": "public_rule",
            "selector_source_sha256": selector_source["sha256"],
            "selector_checkpoint_sha256": "9" * 64,
        }
        self.plan = {
            "schema": "hepta.mem9.causal-plan.v1",
            "selector_sha256": PUBLIC_SELECTOR,
            "selector_mode": "public_rule",
            "selector_source": selector_source,
            "actor_sha256": "1" * 64,
            "launcher_sha256": "2" * 64,
            "model_sha256": "a" * 64,
            "analysis_sha256": "b" * 64,
            "evaluator_sha256": "c" * 64,
            "context_bytes": 4096,
            "baselines": dict.fromkeys(BASELINES, "PLANNED"),
            "ablations": dict.fromkeys(LAYERS, "PLANNED"),
            "sources": {
                "s": self.observe(
                    "source_admission",
                    {
                        "source_id": "s",
                        "exposure_status": "UNSEEN",
                        "exposure_manifest_sha256": "d" * 64,
                        "checked_at": "2026-11-11T00:00:00Z",
                    },
                )
            },
            "cases": [
                {
                    "case_id": "p",
                    "source_id": "s",
                    "task_a_sha256": "e" * 64,
                    "task_c_sha256": hashlib.sha256(task).hexdigest(),
                    "retrieval": retrieval,
                }
            ],
        }
        self.plan_sha = digest(self.plan)
        self.plan["registration"] = self.observe(
            "registration",
            {"protocol_sha256": self.plan_sha, "registered_at": "2026-11-11T01:00:00Z"},
        )

    def pin(self, raw):
        identity = hashlib.sha256(raw).hexdigest()
        self.artifacts[identity] = raw
        return {"sha256": identity, "bytes": len(raw)}

    def observe(self, kind, payload):
        return self.pin(
            canonical_bytes(
                {
                    "schema": "hepta.mem9.observation.v1",
                    "kind": kind,
                    "payload": payload,
                }
            )
        )

    def verifier(self, kind, raw):
        # Deliberately fake authentication port; results are contract controls.
        return AuthenticatedObservation(
            kind, hashlib.sha256(raw).hexdigest(), "fixture-only"
        )

    def test_digest_without_trusted_observer_does_not_admit(self):
        result = admit_protocol(self.plan, self.artifacts.__getitem__)
        self.assertEqual(result["blockers"], ["AUTHENTICATED_OBSERVER_UNAVAILABLE"])

    def test_authenticated_fixture_admits_only_protocol(self):
        result = admit_protocol(self.plan, self.artifacts.__getitem__, self.verifier)
        self.assertEqual(result["status"], "ADMITTED_FOR_EXECUTION")
        self.assertEqual(result["scientific_acceptance"], "HOLD")
        self.assertIs(result["production_adoption"], False)
        self.assertIs(result["benefit_established"], False)

    def test_registration_does_not_cover_changed_plan(self):
        self.plan["context_bytes"] += 1
        self.assertEqual(
            admit_protocol(self.plan, self.artifacts.__getitem__, self.verifier)[
                "blockers"
            ],
            ["PROTOCOL_BINDING_MISMATCH"],
        )

    def test_unknown_source_and_boolean_budgets_fail_closed(self):
        for mutate in (
            lambda: self.plan.update(context_bytes=True),
            lambda: self.plan.update(selector_sha256="0" * 64),
            lambda: self.plan.update(selector_mode="frozen_neural"),
        ):
            self.setUp()
            mutate()
            self.assertEqual(
                admit_protocol(self.plan, self.artifacts.__getitem__, self.verifier)[
                    "status"
                ],
                "HOLD",
            )
        self.setUp()
        source = {
            "source_id": "s",
            "exposure_status": "UNKNOWN",
            "exposure_manifest_sha256": "d" * 64,
            "checked_at": "2026-11-11T00:00:00Z",
        }
        self.plan["sources"]["s"] = self.observe("source_admission", source)
        self.plan["registration"] = self.observe(
            "registration",
            {
                "protocol_sha256": digest(
                    {k: v for k, v in self.plan.items() if k != "registration"}
                ),
                "registered_at": "2026-11-11T01:00:00Z",
            },
        )
        self.assertEqual(
            admit_protocol(self.plan, self.artifacts.__getitem__, self.verifier)[
                "blockers"
            ],
            ["SOURCE_EXPOSURE_NOT_VERIFIED_UNSEEN"],
        )

    def test_malformed_and_nan_protocol_returns_hold(self):
        for plan in (None, [], {"schema": True}, json.loads('{"context_bytes":NaN}')):
            self.assertEqual(
                admit_protocol(plan, self.artifacts.__getitem__, self.verifier)[
                    "status"
                ],
                "HOLD",
            )


if __name__ == "__main__":
    unittest.main()
