"""Historical native pins and stored owner labels cannot recover production authority."""

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

from . import data, paired_consumer, paired_intake, paired_loop
from . import paired_router_source, paired_source_train


class OriginalTurnBoundaryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_owner_install_refuses_before_opening_unprovided_private_materials(self):
        with self.assertRaisesRegex(ValueError, "ORIGINAL_TURN_VERIFIER_REQUIRED"):
            paired_intake.install(SimpleNamespace(scope="owner_intake"))
        self.assertEqual(list(self.root.iterdir()), [])

    @unittest.skipUnless(
        sys.platform == "linux", "uses inherited Linux descriptor slots"
    )
    def test_historical_owner_store_cannot_admit_release_or_consume(self):
        home = self.root / "old-owner-store"
        home.mkdir(mode=0o700)
        database = home / "intake.sqlite"
        with sqlite3.connect(database) as db:
            db.execute("CREATE TABLE settings(value TEXT NOT NULL)")
            db.execute(
                "INSERT INTO settings VALUES (?)",
                (json.dumps({"scope": "owner_intake"}),),
            )
        database.chmod(0o600)
        before = database.read_bytes()
        digest = data.digest("explicit historical negative fixture")
        run = subprocess.run(
            [
                "/bin/sh",
                "-c",
                'exec 3</dev/null 4</dev/null; exec "$@"',
                "fixture",
                sys.executable,
                "-m",
                "cell_experiments.paired_intake",
                str(home),
                "admit",
                digest,
                "missing-snapshot",
                "missing-models",
                "missing-private-task",
                "1",
                "missing-evidence",
                "missing-route",
            ],
            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("ORIGINAL_TURN_VERIFIER_REQUIRED", run.stderr)
        self.assertEqual(run.stdout, "")
        for operation in (paired_intake.release, paired_consumer.context):
            with self.subTest(operation=operation.__name__):
                with self.assertRaisesRegex(
                    ValueError, "ORIGINAL_TURN_VERIFIER_REQUIRED"
                ):
                    operation(home, digest)
        self.assertEqual(database.read_bytes(), before)
        self.assertEqual({p.name for p in home.iterdir()}, {"intake.sqlite"})

    def test_native_v1_receipt_cannot_enable_training_or_consumer_use(self):
        old_owner = {"schema": "hepta.paired-learning.consent-readback.v1"}
        actions = (
            lambda: paired_intake.verify_live(
                "old-elf", "11" * 32, "22" * 32, "33" * 32, {"use": "train"}, []
            ),
            lambda: paired_consumer.native(
                {"scope": "owner_intake"}, {}, {}, "44" * 32, []
            ),
            lambda: paired_source_train._fit_after_verification(
                self.root, {}, old_owner
            ),
            lambda: paired_router_source._fit(self.root, {}, old_owner),
        )
        for index, action in enumerate(actions):
            with self.subTest(entry=index):
                with self.assertRaisesRegex(
                    ValueError, "ORIGINAL_TURN_VERIFIER_REQUIRED"
                ):
                    action()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_retained_owner_readback_cannot_count_an_adopted_improvement(self):
        manifest = {"release": {"scope": "owner_intake"}}
        identity = self.root / "IDENTITY.json"
        identity.write_bytes(data.canonical(manifest))
        before = identity.read_bytes()
        for retained in (False, True):
            with self.subTest(retained=retained):
                with self.assertRaisesRegex(
                    ValueError, "ORIGINAL_TURN_VERIFIER_REQUIRED"
                ):
                    paired_loop.readback(
                        self.root,
                        data.digest(manifest),
                        "55" * 32,
                        {"enrollment": {}},
                        {},
                        retained=retained,
                    )
        self.assertEqual(identity.read_bytes(), before)
        self.assertEqual(list(self.root.iterdir()), [identity])


if __name__ == "__main__":
    unittest.main(verbosity=2)
