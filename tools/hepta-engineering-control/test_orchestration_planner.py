import unittest

from control_engineering_v2 import (
    CiCapacity,
    EngineeringError,
    EngineeringWorkItem,
    ReviewCapacity,
    WorkerProfile,
    plan_engineering_work,
)


class OrchestrationPlannerTests(unittest.TestCase):
    def test_skills_capacity_value_debt_cost_and_merge_order(self):
        items = (
            EngineeringWorkItem(
                "api",
                0,
                (),
                ("src/api",),
                ("python",),
                effort_units=2,
                ci_units=1,
                review_roles=("architecture",),
                expected_value=50,
                architecture_debt_reduction=20,
                rollback_cost=5,
            ),
            EngineeringWorkItem(
                "docs",
                1,
                (),
                ("docs/guide",),
                ("docs",),
                effort_units=1,
                ci_units=1,
                review_roles=("architecture",),
                expected_value=10,
                architecture_debt_reduction=1,
                rollback_cost=1,
            ),
        )
        plan = plan_engineering_work(
            items,
            (),
            (
                WorkerProfile("alice", ("python", "docs"), 3, 2),
                WorkerProfile("bob", ("docs",), 2, 1),
            ),
            (ReviewCapacity("architecture", 2),),
            (CiCapacity("linux", 2),),
        )
        self.assertEqual([row.package_id for row in plan.assignments], ["api", "docs"])
        self.assertEqual(plan.assignments[0].worker_id, "alice")
        self.assertEqual(plan.merge_queue, ("api", "docs"))
        self.assertEqual([row.integration_rank for row in plan.integration_order], [1, 2])
        self.assertFalse(plan.merge_authority)

    def test_missing_skill_review_ci_and_path_conflict_fail_closed(self):
        items = (
            EngineeringWorkItem("a", 0, (), ("src/a",), ("rust",), review_roles=("security",)),
            EngineeringWorkItem("b", 1, (), ("src/b",), ("python",), ci_units=2),
            EngineeringWorkItem("c", 2, (), ("src/locked",), ("python",)),
        )
        plan = plan_engineering_work(
            items,
            (),
            (WorkerProfile("worker", ("python",), 10, 3),),
            (ReviewCapacity("security", 0),),
            (CiCapacity("linux", 1),),
            ("src/locked",),
        )
        self.assertEqual(plan.assignments, ())
        reasons = dict(plan.blocked)
        self.assertEqual(reasons["a"], "worker_capacity_or_skill")
        self.assertEqual(reasons["b"], "ci_capacity")
        self.assertEqual(reasons["c"], "active_path_lease")

    def test_predecessor_and_batch_path_conflicts(self):
        items = (
            EngineeringWorkItem("base", 0, (), ("src/shared",), ("python",)),
            EngineeringWorkItem(
                "child",
                1,
                ("base",),
                ("src/child",),
                ("python",),
            ),
            EngineeringWorkItem("other", 2, (), ("src/shared/x",), ("python",)),
        )
        plan = plan_engineering_work(
            items,
            (),
            (WorkerProfile("worker", ("python",), 10, 3),),
            (),
            (CiCapacity("linux", 3),),
        )
        self.assertEqual(plan.merge_queue, ("base",))
        self.assertEqual(dict(plan.blocked)["child"], "missing_predecessor:base")
        self.assertEqual(dict(plan.blocked)["other"], "batch_path_conflict")

    def test_cycle_rejects(self):
        with self.assertRaisesRegex(EngineeringError, "dependency_cycle"):
            plan_engineering_work(
                (
                    EngineeringWorkItem("a", 0, ("b",), ("a",)),
                    EngineeringWorkItem("b", 0, ("a",), ("b",)),
                ),
                (),
                (),
                (),
                (),
            )


if __name__ == "__main__":
    unittest.main()
