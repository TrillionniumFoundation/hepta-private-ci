from dataclasses import replace
from pathlib import Path
import subprocess
import tempfile
import unittest

from control_engineering_v2 import (
    EngineeringStore,
    HmacTrustStore,
    WorkEnvelope,
    WorkPackage,
)
from control_engineering_v2.control_plane import DENIED_AUTHORITIES
from control_engineering_v2.orchestration import (
    CompletionReceipt,
    EngineeringCapacity,
    EngineeringWorkPackage,
    ReviewCapacity,
    WorkerProfile,
    issue_repository_work_envelope,
    plan_engineering_work,
)


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class OrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.now = 5_000_000
        self.trust = HmacTrustStore({("ci_executor", "ci"): b"secret"})
        self.envelope = WorkEnvelope(
            "env",
            "a" * 40,
            "b" * 40,
            "c" * 64,
            "d" * 64,
            "developer-productivity",
            ("src",),
            tuple(sorted(DENIED_AUTHORITIES)),
            8,
            self.now + 1_000_000,
        )

    def completion(
        self,
        store: EngineeringStore,
        package_id: str,
        write_path: str,
    ) -> CompletionReceipt:
        generation_id = f"completed-{package_id}"
        store.schedule_ready_packages(
            self.envelope.envelope_id,
            (WorkPackage(0, package_id, (), (write_path,)),),
            (),
            generation_id=generation_id,
            now_ns=self.now,
        )
        row = store.connection.execute(
            "SELECT semantic_digest FROM assignment_generations WHERE generation_id=?",
            (generation_id,),
        ).fetchone()
        self.assertIsNotNone(row)
        value = CompletionReceipt(
            package_id,
            self.envelope.source_commit,
            self.envelope.source_tree,
            generation_id,
            str(row[0]),
            "e" * 64,
            "ci_executor",
            "ci",
            self.now - 100,
            self.now + 100,
        )
        return replace(
            value,
            signature=self.trust.sign(value, value.issuer, value.signing_identity),
        )

    def test_authenticated_completion_and_multidimensional_capacity(self):
        with tempfile.TemporaryDirectory() as temp:
            with EngineeringStore(Path(temp) / "store.db") as store:
                store.issue_work_envelope(self.envelope, now_ns=self.now)
                plan = plan_engineering_work(
                    store,
                    self.envelope,
                    (
                        EngineeringWorkPackage(
                            0,
                            "foundation",
                            (),
                            ("src/foundation",),
                            required_skills=("rust",),
                            capacity_units=2,
                            ci_units=1,
                            review_roles=("architecture",),
                            expected_value_q32=100,
                            architecture_debt_q32=10,
                            rollback_cost_q32=5,
                        ),
                        EngineeringWorkPackage(
                            1,
                            "feature",
                            ("foundation",),
                            ("src/feature",),
                            required_skills=("python",),
                            capacity_units=1,
                            ci_units=1,
                            review_roles=("security",),
                            expected_value_q32=90,
                        ),
                    ),
                    (
                        WorkerProfile("worker-rust", ("rust",), 4, ("src",)),
                        WorkerProfile("worker-python", ("python",), 2, ("src",)),
                    ),
                    (self.completion(store, "foundation", "src/foundation"),),
                    self.trust,
                    EngineeringCapacity(
                        2,
                        (
                            ReviewCapacity("architecture", 1),
                            ReviewCapacity("security", 1),
                        ),
                    ),
                    generation_id="g",
                    now_ns=self.now,
                )
        self.assertEqual([row.package_id for row in plan.assignments], ["feature"])
        self.assertEqual(plan.assignments[0].worker_id, "worker-python")
        self.assertEqual(plan.integration_order, ("feature",))
        self.assertIn(("foundation", "already_completed"), plan.blocked)
        self.assertEqual(plan.merge_queue[0].state, "awaiting_candidate_evidence")
        self.assertFalse(plan.merge_queue[0].merge_authority)

    def test_unsigned_completion_cannot_satisfy_predecessor(self):
        with tempfile.TemporaryDirectory() as temp:
            with EngineeringStore(Path(temp) / "store.db") as store:
                store.issue_work_envelope(self.envelope, now_ns=self.now)
                receipt = replace(
                    self.completion(store, "foundation", "src/foundation"),
                    signature="0" * 64,
                )
                with self.assertRaisesRegex(ValueError, "completion_receipt_signature"):
                    plan_engineering_work(
                        store,
                        self.envelope,
                        (
                            EngineeringWorkPackage(
                                0, "feature", ("foundation",), ("src/feature",)
                            ),
                        ),
                        (WorkerProfile("worker", (), 1, ("src",)),),
                        (receipt,),
                        self.trust,
                        EngineeringCapacity(1, ()),
                        generation_id="g",
                        now_ns=self.now,
                    )

    def test_signed_completion_requires_real_durable_assignment_generation(self):
        with tempfile.TemporaryDirectory() as temp:
            with EngineeringStore(Path(temp) / "store.db") as store:
                store.issue_work_envelope(self.envelope, now_ns=self.now)
                valid = self.completion(store, "foundation", "src/foundation")
                forged = replace(
                    valid,
                    generation_id="missing-generation",
                    generation_digest="f" * 64,
                    signature="",
                )
                forged = replace(
                    forged,
                    signature=self.trust.sign(
                        forged, forged.issuer, forged.signing_identity
                    ),
                )
                with self.assertRaisesRegex(ValueError, "completion_generation_unknown"):
                    plan_engineering_work(
                        store,
                        self.envelope,
                        (
                            EngineeringWorkPackage(
                                0, "feature", ("foundation",), ("src/feature",)
                            ),
                        ),
                        (WorkerProfile("worker", (), 1, ("src",)),),
                        (forged,),
                        self.trust,
                        EngineeringCapacity(1, ()),
                        generation_id="g",
                        now_ns=self.now,
                    )

    def test_plan_rejects_envelope_not_identical_to_admitted_owner_state(self):
        with tempfile.TemporaryDirectory() as temp:
            with EngineeringStore(Path(temp) / "store.db") as store:
                store.issue_work_envelope(self.envelope, now_ns=self.now)
                forged = replace(
                    self.envelope,
                    allowed_paths=("src", "other"),
                    maximum_assignments=7,
                )
                with self.assertRaisesRegex(
                    ValueError, "orchestration_envelope_binding_mismatch"
                ):
                    plan_engineering_work(
                        store,
                        forged,
                        (EngineeringWorkPackage(0, "feature", (), ("src/feature",)),),
                        (WorkerProfile("worker", (), 1, ("src",)),),
                        (),
                        self.trust,
                        EngineeringCapacity(1, ()),
                        generation_id="g-envelope-mismatch",
                        now_ns=self.now,
                    )

    def test_plan_rejects_duplicate_and_unbounded_capacity_dimensions(self):
        bad_packages = (
            EngineeringWorkPackage(
                0,
                "duplicate-skills",
                (),
                ("src/a",),
                required_skills=("rust", "rust"),
            ),
            EngineeringWorkPackage(
                0,
                "duplicate-review",
                (),
                ("src/b",),
                review_roles=("architecture", "architecture"),
            ),
            EngineeringWorkPackage(
                0,
                "huge-capacity",
                (),
                ("src/c",),
                capacity_units=1_000_001,
            ),
            EngineeringWorkPackage(
                0,
                "huge-ci",
                (),
                ("src/d",),
                ci_units=1_000_001,
            ),
        )
        with tempfile.TemporaryDirectory() as temp:
            for index, package in enumerate(bad_packages):
                with self.subTest(package=package.package_id):
                    database = Path(temp) / f"store-{index}.db"
                    with EngineeringStore(database) as store:
                        store.issue_work_envelope(self.envelope, now_ns=self.now)
                        with self.assertRaisesRegex(
                            ValueError, "invalid_package_capacity"
                        ):
                            plan_engineering_work(
                                store,
                                self.envelope,
                                (package,),
                                (WorkerProfile("worker", ("rust",), 1, ("src",)),),
                                (),
                                self.trust,
                                EngineeringCapacity(
                                    1, (ReviewCapacity("architecture", 1),)
                                ),
                                generation_id=f"g-bad-{index}",
                                now_ns=self.now,
                            )

    def test_worker_scope_is_canonicalized_before_matching(self):
        with tempfile.TemporaryDirectory() as temp:
            with EngineeringStore(Path(temp) / "store.db") as store:
                store.issue_work_envelope(self.envelope, now_ns=self.now)
                with self.assertRaisesRegex(ValueError, "invalid_path"):
                    plan_engineering_work(
                        store,
                        self.envelope,
                        (EngineeringWorkPackage(0, "feature", (), ("src/feature",)),),
                        (WorkerProfile("worker", (), 1, ("src/../src",)),),
                        (),
                        self.trust,
                        EngineeringCapacity(1, ()),
                        generation_id="g-invalid-worker-scope",
                        now_ns=self.now,
                    )

    def test_repository_envelope_binds_real_head_tree_and_remote(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            root.mkdir()
            git(root, "init")
            git(root, "config", "user.email", "test@example.invalid")
            git(root, "config", "user.name", "test")
            git(root, "remote", "add", "origin", "https://github.com/acme/repo.git")
            (root / "src").mkdir()
            (root / "src/a").write_text("x", encoding="utf-8")
            git(root, "add", ".")
            git(root, "commit", "-m", "base")
            head = git(root, "rev-parse", "HEAD")
            tree = git(root, "rev-parse", "HEAD^{tree}")
            envelope = replace(self.envelope, source_commit=head, source_tree=tree)
            with EngineeringStore(Path(temp) / "store.db") as store:
                issued = issue_repository_work_envelope(
                    root,
                    store,
                    envelope,
                    expected_repository="acme/repo",
                    now_ns=self.now,
                )
                self.assertEqual(issued.source_commit, head)
                with self.assertRaisesRegex(ValueError, "source_identity_mismatch"):
                    issue_repository_work_envelope(
                        root,
                        store,
                        replace(envelope, source_tree="f" * 40),
                        expected_repository="acme/repo",
                        now_ns=self.now,
                    )


if __name__ == "__main__":
    unittest.main()
