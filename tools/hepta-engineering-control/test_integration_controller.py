from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from control_engineering_v2 import (
    EngineeringCapacity,
    EngineeringStore,
    EngineeringWorkPackage,
    HmacTrustStore,
    IntegrationTerminalReceipt,
    ReviewCapacity,
    WorkerProfile,
    WorkEnvelope,
    integration_queue_generation,
    integration_queue_item,
    plan_engineering_work,
    publish_integration_queue,
    reconcile_integration_item,
)
from control_engineering_v2.control_plane import DENIED_AUTHORITIES


class IntegrationControllerTests(unittest.TestCase):
    def setUp(self):
        self.now = 10_000_000
        self.envelope = WorkEnvelope(
            "env",
            "a" * 40,
            "b" * 40,
            "c" * 64,
            "d" * 64,
            "developer-productivity",
            ("src",),
            tuple(sorted(DENIED_AUTHORITIES)),
            4,
            self.now + 1_000_000_000,
        )
        self.base_commit = "e" * 40
        self.base_tree = "f" * 40
        self.trust = HmacTrustStore(
            {("integration_terminal_observer", "terminal-key"): b"terminal"}
        )

    def terminal_receipt(self, *, outcome="merged_observed", observed=None):
        observed = self.now + 5 if observed is None else observed
        value = IntegrationTerminalReceipt(
            "queue-a",
            "package-a",
            "1" * 64,
            "2" * 64,
            "3" * 64,
            outcome,
            "integration_terminal_observer",
            "terminal-key",
            observed,
            observed + 1_000_000,
        )
        return replace(
            value,
            signature=self.trust.sign(
                value, value.issuer, value.signing_identity
            ),
        )

    def plan(self, store):
        store.issue_work_envelope(self.envelope, now_ns=self.now)
        return plan_engineering_work(
            store,
            self.envelope,
            (
                EngineeringWorkPackage(
                    0,
                    "package-a",
                    (),
                    ("src/a",),
                    required_skills=("python",),
                    review_roles=("architecture",),
                    expected_value_q32=10,
                ),
            ),
            (WorkerProfile("worker-a", ("python",), 1, ("src",)),),
            (),
            HmacTrustStore({}),
            EngineeringCapacity(1, (ReviewCapacity("architecture", 1),)),
            generation_id="generation-a",
            now_ns=self.now,
        )

    def publish(self, store):
        return publish_integration_queue(
            store,
            self.plan(store),
            queue_generation_id="queue-a",
            base_commit=self.base_commit,
            base_tree=self.base_tree,
            now_ns=self.now + 1,
        )

    def test_evidence_progression_reopen_and_terminal_observation(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "engineering.sqlite3"
            with EngineeringStore(path) as store:
                self.publish(store)
                candidate = reconcile_integration_item(
                    store,
                    "queue-a",
                    "package-a",
                    current_base_commit=self.base_commit,
                    current_base_tree=self.base_tree,
                    candidate_digest="1" * 64,
                    now_ns=self.now + 2,
                )
                self.assertEqual(candidate.state, "awaiting_review")
                reviewed = reconcile_integration_item(
                    store,
                    "queue-a",
                    "package-a",
                    current_base_commit=self.base_commit,
                    current_base_tree=self.base_tree,
                    review_digest="2" * 64,
                    now_ns=self.now + 3,
                )
                self.assertEqual(reviewed.state, "awaiting_ci")
                ready = reconcile_integration_item(
                    store,
                    "queue-a",
                    "package-a",
                    current_base_commit=self.base_commit,
                    current_base_tree=self.base_tree,
                    ci_digest="3" * 64,
                    now_ns=self.now + 4,
                )
                self.assertEqual(ready.state, "ready_external_merge")
            with EngineeringStore(path) as reopened:
                self.assertEqual(
                    integration_queue_item(reopened, "queue-a", "package-a").state,
                    "ready_external_merge",
                )
                terminal = reconcile_integration_item(
                    reopened,
                    "queue-a",
                    "package-a",
                    current_base_commit=self.base_commit,
                    current_base_tree=self.base_tree,
                    terminal_outcome="merged_observed",
                    terminal_receipt=self.terminal_receipt(),
                    trust_store=self.trust,
                    now_ns=self.now + 5,
                )
                self.assertEqual(terminal.state, "terminal_merged")
                self.assertEqual(
                    integration_queue_generation(reopened, "queue-a").state,
                    "terminal",
                )

    def test_base_drift_invalidates_generation_and_requires_replan(self):
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                self.publish(store)
                item = reconcile_integration_item(
                    store,
                    "queue-a",
                    "package-a",
                    current_base_commit="9" * 40,
                    current_base_tree="8" * 40,
                    candidate_digest="1" * 64,
                    now_ns=self.now + 2,
                )
                self.assertEqual(item.state, "invalidated")
                self.assertEqual(item.reason, "base_drift")
                self.assertEqual(
                    integration_queue_generation(store, "queue-a").state,
                    "requires_replan",
                )
                with self.assertRaisesRegex(
                    ValueError, "integration_generation_requires_replan"
                ):
                    reconcile_integration_item(
                        store,
                        "queue-a",
                        "package-a",
                        current_base_commit=self.base_commit,
                        current_base_tree=self.base_tree,
                        now_ns=self.now + 3,
                    )

    def test_observation_digest_drift_invalidates_instead_of_replacing(self):
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                self.publish(store)
                reconcile_integration_item(
                    store,
                    "queue-a",
                    "package-a",
                    current_base_commit=self.base_commit,
                    current_base_tree=self.base_tree,
                    candidate_digest="1" * 64,
                    now_ns=self.now + 2,
                )
                invalid = reconcile_integration_item(
                    store,
                    "queue-a",
                    "package-a",
                    current_base_commit=self.base_commit,
                    current_base_tree=self.base_tree,
                    candidate_digest="2" * 64,
                    now_ns=self.now + 3,
                )
                self.assertEqual(invalid.state, "invalidated")
                self.assertEqual(invalid.reason, "candidate_drift")

    def test_terminal_requires_authenticated_observer_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                self.publish(store)
                reconcile_integration_item(
                    store,
                    "queue-a",
                    "package-a",
                    current_base_commit=self.base_commit,
                    current_base_tree=self.base_tree,
                    candidate_digest="1" * 64,
                    review_digest="2" * 64,
                    ci_digest="3" * 64,
                    now_ns=self.now + 2,
                )
                with self.assertRaisesRegex(
                    ValueError, "authenticated_terminal_receipt_required"
                ):
                    reconcile_integration_item(
                        store,
                        "queue-a",
                        "package-a",
                        current_base_commit=self.base_commit,
                        current_base_tree=self.base_tree,
                        terminal_outcome="merged_observed",
                        now_ns=self.now + 3,
                    )

    def test_terminal_outcome_cannot_skip_review_or_ci(self):
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                self.publish(store)
                with self.assertRaisesRegex(
                    ValueError, "integration_terminal_before_ready"
                ):
                    reconcile_integration_item(
                        store,
                        "queue-a",
                        "package-a",
                        current_base_commit=self.base_commit,
                        current_base_tree=self.base_tree,
                        candidate_digest="1" * 64,
                        terminal_outcome="merged_observed",
                        terminal_receipt=self.terminal_receipt(),
                        trust_store=self.trust,
                        now_ns=self.now + 2,
                    )

    def test_identical_observation_retry_is_revision_stable_noop(self):
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                self.publish(store)
                first = reconcile_integration_item(
                    store,
                    "queue-a",
                    "package-a",
                    current_base_commit=self.base_commit,
                    current_base_tree=self.base_tree,
                    candidate_digest="1" * 64,
                    now_ns=self.now + 2,
                )
                generation = integration_queue_generation(store, "queue-a")
                anchor = store.audit_anchor()
                replay = reconcile_integration_item(
                    store,
                    "queue-a",
                    "package-a",
                    current_base_commit=self.base_commit,
                    current_base_tree=self.base_tree,
                    candidate_digest="1" * 64,
                    now_ns=self.now + 3,
                )
                self.assertEqual(replay, first)
                self.assertEqual(
                    integration_queue_generation(store, "queue-a").revision,
                    generation.revision,
                )
                self.assertEqual(store.audit_anchor(), anchor)

    def test_repeated_base_drift_is_revision_stable_noop(self):
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                self.publish(store)
                first = reconcile_integration_item(
                    store,
                    "queue-a",
                    "package-a",
                    current_base_commit="9" * 40,
                    current_base_tree="8" * 40,
                    now_ns=self.now + 2,
                )
                generation = integration_queue_generation(store, "queue-a")
                anchor = store.audit_anchor()
                replay = reconcile_integration_item(
                    store,
                    "queue-a",
                    "package-a",
                    current_base_commit="9" * 40,
                    current_base_tree="8" * 40,
                    now_ns=self.now + 3,
                )
                self.assertEqual(replay, first)
                self.assertEqual(
                    integration_queue_generation(store, "queue-a").revision,
                    generation.revision,
                )
                self.assertEqual(store.audit_anchor(), anchor)

    def test_review_and_ci_cannot_precede_candidate_binding(self):
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                self.publish(store)
                with self.assertRaisesRegex(
                    ValueError, "integration_review_before_candidate"
                ):
                    reconcile_integration_item(
                        store,
                        "queue-a",
                        "package-a",
                        current_base_commit=self.base_commit,
                        current_base_tree=self.base_tree,
                        review_digest="2" * 64,
                        now_ns=self.now + 2,
                    )
                with self.assertRaisesRegex(ValueError, "integration_ci_before_review"):
                    reconcile_integration_item(
                        store,
                        "queue-a",
                        "package-a",
                        current_base_commit=self.base_commit,
                        current_base_tree=self.base_tree,
                        candidate_digest="1" * 64,
                        ci_digest="3" * 64,
                        now_ns=self.now + 3,
                    )

    def test_terminal_retry_is_idempotent_but_conflicting_terminal_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            with EngineeringStore(Path(temporary) / "engineering.sqlite3") as store:
                self.publish(store)
                ready = reconcile_integration_item(
                    store,
                    "queue-a",
                    "package-a",
                    current_base_commit=self.base_commit,
                    current_base_tree=self.base_tree,
                    candidate_digest="1" * 64,
                    review_digest="2" * 64,
                    ci_digest="3" * 64,
                    now_ns=self.now + 2,
                )
                self.assertEqual(ready.state, "ready_external_merge")
                terminal = reconcile_integration_item(
                    store,
                    "queue-a",
                    "package-a",
                    current_base_commit=self.base_commit,
                    current_base_tree=self.base_tree,
                    terminal_outcome="merged_observed",
                    terminal_receipt=self.terminal_receipt(),
                    trust_store=self.trust,
                    now_ns=self.now + 3,
                )
                generation = integration_queue_generation(store, "queue-a")
                anchor = store.audit_anchor()
                replay = reconcile_integration_item(
                    store,
                    "queue-a",
                    "package-a",
                    current_base_commit="9" * 40,
                    current_base_tree="8" * 40,
                    terminal_outcome="merged_observed",
                    terminal_receipt=self.terminal_receipt(),
                    trust_store=self.trust,
                    now_ns=self.now + 4,
                )
                self.assertEqual(replay, terminal)
                self.assertEqual(
                    integration_queue_generation(store, "queue-a").revision,
                    generation.revision,
                )
                self.assertEqual(store.audit_anchor(), anchor)
                with self.assertRaisesRegex(ValueError, "integration_item_terminal"):
                    reconcile_integration_item(
                        store,
                        "queue-a",
                        "package-a",
                        current_base_commit=self.base_commit,
                        current_base_tree=self.base_tree,
                        terminal_outcome="terminal_failure",
                        terminal_receipt=self.terminal_receipt(
                            outcome="terminal_failure", observed=self.now + 5
                        ),
                        trust_store=self.trust,
                        now_ns=self.now + 5,
                    )


if __name__ == "__main__":
    unittest.main()
