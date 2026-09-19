from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from control_engineering_v2 import (
    EngineeringError,
    EngineeringStore,
    WorkEnvelope,
    completed_packages,
    WorkPackage,
)

DENIED = (
    "runtime_authority",
    "merge_authority",
    "activation_authority",
    "promotion_authority",
    "release_authority",
    "external_effect_authority",
)


class AssignmentLifecycleTests(unittest.TestCase):
    def envelope(self) -> WorkEnvelope:
        return WorkEnvelope(
            "env-worker",
            "a" * 40,
            "b" * 40,
            "c" * 64,
            "d" * 64,
            "developer-productivity",
            ("src",),
            DENIED,
            4,
            10_000,
        )

    def prepare(self, store: EngineeringStore) -> None:
        store.issue_work_envelope(self.envelope(), now_ns=100)
        store.schedule_ready_packages(
            "env-worker",
            (
                WorkPackage(
                    0,
                    "pkg",
                    (),
                    ("src/pkg",),
                    ("python",),
                    2,
                ),
            ),
            (),
            generation_id="generation-worker",
            now_ns=101,
        )
        store.register_worker(
            "worker-1",
            "github-actions:engineering",
            "1" * 64,
            ("python", "git"),
            maximum_concurrency=1,
            authority_epoch=7,
            expires_unix_ns=9000,
            now_ns=102,
        )
        store.acquire_path_lease(
            "lease-worker",
            "env-worker",
            "worker-1",
            ("src/pkg",),
            authority_epoch=7,
            expires_unix_ns=8000,
            now_ns=103,
        )

    def test_claim_run_fail_requeue_retry_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with EngineeringStore(Path(temp) / "engineering.db") as store:
                self.prepare(store)
                claim = store.claim_assignment(
                    "claim-1",
                    "generation-worker",
                    "pkg",
                    "worker-1",
                    "lease-worker",
                    authority_epoch=7,
                    expires_unix_ns=7000,
                    now_ns=104,
                )
                self.assertEqual(claim.state, "claimed")
                self.assertEqual(claim.attempt, 1)
                self.assertFalse(claim.runtime_authority)

                # Exact replay returns the current durable claim rather than
                # creating another attempt.
                replay = store.claim_assignment(
                    "claim-1",
                    "generation-worker",
                    "pkg",
                    "worker-1",
                    "lease-worker",
                    authority_epoch=7,
                    expires_unix_ns=7000,
                    now_ns=105,
                )
                self.assertEqual(replay.claim_id, claim.claim_id)
                self.assertEqual(replay.fencing_token, claim.fencing_token)

                running = store.begin_assignment(
                    "claim-1",
                    expected_revision=claim.revision,
                    authority_epoch=7,
                    now_ns=106,
                )
                self.assertEqual(running.state, "running")
                failed = store.fail_assignment(
                    "claim-1",
                    "transient_infra",
                    retryable=True,
                    expected_revision=running.revision,
                    authority_epoch=7,
                    now_ns=107,
                )
                self.assertEqual(failed.state, "failed")

                with self.assertRaisesRegex(
                    EngineeringError, "assignment_requeue_required"
                ):
                    store.claim_assignment(
                        "claim-2",
                        "generation-worker",
                        "pkg",
                        "worker-1",
                        "lease-worker",
                        authority_epoch=7,
                        expires_unix_ns=7000,
                        now_ns=108,
                    )

                requeued = store.requeue_assignment(
                    "claim-1",
                    expected_revision=failed.revision,
                    authority_epoch=7,
                    now_ns=109,
                )
                self.assertEqual(requeued.state, "requeued")
                retry = store.claim_assignment(
                    "claim-2",
                    "generation-worker",
                    "pkg",
                    "worker-1",
                    "lease-worker",
                    authority_epoch=7,
                    expires_unix_ns=7000,
                    now_ns=110,
                )
                self.assertEqual(retry.attempt, 2)
                running = store.begin_assignment(
                    "claim-2",
                    expected_revision=retry.revision,
                    authority_epoch=7,
                    now_ns=111,
                )
                completed = store.complete_assignment(
                    "claim-2",
                    "2" * 64,
                    expected_revision=running.revision,
                    authority_epoch=7,
                    now_ns=112,
                )
                self.assertEqual(completed.state, "completed")
                with self.assertRaisesRegex(
                    EngineeringError, "assignment_already_completed"
                ):
                    store.claim_assignment(
                        "claim-3",
                        "generation-worker",
                        "pkg",
                        "worker-1",
                        "lease-worker",
                        authority_epoch=7,
                        expires_unix_ns=7000,
                        now_ns=113,
                    )

    def test_worker_capability_capacity_and_lease_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with EngineeringStore(Path(temp) / "engineering.db") as store:
                self.prepare(store)
                store.schedule_ready_packages(
                    "env-worker",
                    (
                        WorkPackage(0, "other", (), ("src/other",), ("rust",), 1),
                    ),
                    (),
                    generation_id="generation-other",
                    now_ns=104,
                )
                with self.assertRaisesRegex(
                    EngineeringError, "worker_capability_mismatch"
                ):
                    store.claim_assignment(
                        "claim-other",
                        "generation-other",
                        "other",
                        "worker-1",
                        "lease-worker",
                        authority_epoch=7,
                        expires_unix_ns=7000,
                        now_ns=105,
                    )

                claim = store.claim_assignment(
                    "claim-1",
                    "generation-worker",
                    "pkg",
                    "worker-1",
                    "lease-worker",
                    authority_epoch=7,
                    expires_unix_ns=7000,
                    now_ns=106,
                )
                self.assertEqual(claim.state, "claimed")
                # A second active package would exceed the registered worker
                # concurrency even if it otherwise had a compatible lease.
                store.schedule_ready_packages(
                    "env-worker",
                    (
                        WorkPackage(0, "pkg-2", (), ("src/pkg2",), ("python",), 1),
                    ),
                    (),
                    generation_id="generation-two",
                    now_ns=107,
                )
                store.acquire_path_lease(
                    "lease-worker-2",
                    "env-worker",
                    "worker-1",
                    ("src/pkg2",),
                    authority_epoch=7,
                    expires_unix_ns=8000,
                    now_ns=108,
                )
                with self.assertRaisesRegex(
                    EngineeringError, "worker_capacity_exceeded"
                ):
                    store.claim_assignment(
                        "claim-2",
                        "generation-two",
                        "pkg-2",
                        "worker-1",
                        "lease-worker-2",
                        authority_epoch=7,
                        expires_unix_ns=7000,
                        now_ns=109,
                    )

    def test_durable_completion_drives_next_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with EngineeringStore(Path(temp) / "engineering.db") as store:
                envelope = WorkEnvelope(
                    "env-deps",
                    "a" * 40,
                    "b" * 40,
                    "c" * 64,
                    "d" * 64,
                    "developer-productivity",
                    ("src",),
                    DENIED,
                    4,
                    10_000,
                )
                store.issue_work_envelope(envelope, now_ns=100)
                first = store.schedule_ready_packages(
                    "env-deps",
                    (WorkPackage(0, "A", (), ("src/a",), ("python",), 1),),
                    (),
                    generation_id="gen-a",
                    now_ns=101,
                )
                self.assertEqual(first.assigned, ("A",))
                store.register_worker(
                    "worker-a",
                    "worker-principal",
                    "3" * 64,
                    ("python",),
                    maximum_concurrency=1,
                    authority_epoch=2,
                    expires_unix_ns=9000,
                    now_ns=102,
                )
                store.acquire_path_lease(
                    "lease-a",
                    "env-deps",
                    "worker-a",
                    ("src/a",),
                    authority_epoch=2,
                    expires_unix_ns=8000,
                    now_ns=103,
                )
                claim = store.claim_assignment(
                    "claim-a",
                    "gen-a",
                    "A",
                    "worker-a",
                    "lease-a",
                    authority_epoch=2,
                    expires_unix_ns=7000,
                    now_ns=104,
                )
                running = store.begin_assignment(
                    "claim-a",
                    expected_revision=claim.revision,
                    authority_epoch=2,
                    now_ns=105,
                )
                store.complete_assignment(
                    "claim-a",
                    "4" * 64,
                    expected_revision=running.revision,
                    authority_epoch=2,
                    now_ns=106,
                )
                completed = completed_packages(
                    store,
                    "env-deps",
                    now_ns=107,
                )
                self.assertEqual(completed, ("A",))
                second = store.schedule_ready_packages(
                    "env-deps",
                    (
                        WorkPackage(0, "A", (), ("src/a",), ("python",), 1),
                        WorkPackage(1, "B", ("A",), ("src/b",), ("python",), 1),
                    ),
                    completed,
                    generation_id="gen-b",
                    now_ns=108,
                )
                self.assertEqual(second.assigned, ("B",))
                self.assertIn(("A", "already_completed"), second.blocked)

    def test_expiry_requires_explicit_requeue(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with EngineeringStore(Path(temp) / "engineering.db") as store:
                self.prepare(store)
                claim = store.claim_assignment(
                    "claim-expire",
                    "generation-worker",
                    "pkg",
                    "worker-1",
                    "lease-worker",
                    authority_epoch=7,
                    expires_unix_ns=200,
                    now_ns=104,
                )
                status = store.assignment_status(
                    "generation-worker",
                    package_id="pkg",
                    now_ns=201,
                )
                self.assertEqual(status[0].state, "expired")
                self.assertTrue(status[0].retryable)
                with self.assertRaisesRegex(
                    EngineeringError, "assignment_requeue_required"
                ):
                    store.claim_assignment(
                        "claim-after-expiry",
                        "generation-worker",
                        "pkg",
                        "worker-1",
                        "lease-worker",
                        authority_epoch=7,
                        expires_unix_ns=7000,
                        now_ns=202,
                    )
                store.requeue_assignment(
                    "claim-expire",
                    expected_revision=status[0].revision,
                    authority_epoch=7,
                    now_ns=203,
                )
                retried = store.claim_assignment(
                    "claim-after-expiry",
                    "generation-worker",
                    "pkg",
                    "worker-1",
                    "lease-worker",
                    authority_epoch=7,
                    expires_unix_ns=7000,
                    now_ns=204,
                )
                self.assertEqual(retried.attempt, 2)


if __name__ == "__main__":
    unittest.main()
