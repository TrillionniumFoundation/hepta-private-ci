from pathlib import Path
import subprocess
import tempfile
import unittest

from control_engineering_v2 import (
    EngineeringCapacity,
    EngineeringControlProduct,
    EngineeringWorkPackage,
    HmacTrustStore,
    ReviewCapacity,
    WorkerProfile,
    WorkEnvelope,
)
from control_engineering_v2.control_plane import DENIED_AUTHORITIES


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class EngineeringControlProductTests(unittest.TestCase):
    def test_named_product_owner_composes_repository_store_and_plan(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            git(root, "init")
            git(root, "config", "user.email", "test@example.invalid")
            git(root, "config", "user.name", "Engineering Product")
            git(root, "remote", "add", "origin", "https://github.com/TrillionniumFoundation/hepta-private-ci.git")
            (root / "src").mkdir()
            (root / "src" / "a.txt").write_text("a\n", encoding="utf-8")
            git(root, "add", ".")
            git(root, "commit", "-m", "base")
            head = git(root, "rev-parse", "HEAD")
            tree = git(root, "rev-parse", "HEAD^{tree}")
            now = 1_000_000
            envelope = WorkEnvelope(
                "env",
                head,
                tree,
                "c" * 64,
                "d" * 64,
                "developer-productivity",
                ("src",),
                tuple(sorted(DENIED_AUTHORITIES)),
                1,
                now + 1_000_000,
            )
            database = Path(temporary) / "engineering.sqlite3"
            with EngineeringControlProduct(
                database,
                root,
                expected_repository="TrillionniumFoundation/hepta-private-ci",
                trust_store=HmacTrustStore({}),
            ) as product:
                product.admit_repository_envelope(envelope, now_ns=now)
                plan = product.plan_work(
                    envelope,
                    (
                        EngineeringWorkPackage(
                            0,
                            "package-a",
                            (),
                            ("src/a.txt",),
                            required_skills=("engineering",),
                            review_roles=("architecture",),
                        ),
                    ),
                    (WorkerProfile("worker-a", ("engineering",), 1, ("src",)),),
                    (),
                    EngineeringCapacity(1, (ReviewCapacity("architecture", 1),)),
                    generation_id="generation-a",
                    now_ns=now,
                )
                self.assertEqual(plan.assignments[0].worker_id, "worker-a")
                self.assertEqual(
                    product.store.connection.execute("PRAGMA user_version").fetchone()[0],
                    7,
                )
            self.assertTrue(database.exists())


if __name__ == "__main__":
    unittest.main()
