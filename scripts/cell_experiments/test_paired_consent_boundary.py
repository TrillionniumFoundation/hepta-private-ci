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
from . import paired_observation, paired_router_source, paired_source_dispatch
from . import paired_source_gate, paired_source_train


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

    def test_relabelled_settings_cannot_republish_stored_owner_admissions(self):
        for state in ("ready", "publishing", "released"):
            with self.subTest(state=state):
                home = self.root / state
                home.mkdir(mode=0o700)
                request = {"fixture": "historical owner request"}
                binding = {
                    "release": {
                        "scope": "owner_intake",
                        "request_sha256": data.digest(request),
                    },
                    "enrollment": {"fixture": "unverified retained metadata"},
                }
                admission = data.digest(binding)
                database = home / "intake.sqlite"
                with sqlite3.connect(database) as db:
                    db.execute("CREATE TABLE settings(value TEXT NOT NULL)")
                    db.execute(
                        "INSERT INTO settings VALUES (?)",
                        (json.dumps({"scope": "engineering_fixture"}),),
                    )
                    db.execute(
                        "CREATE TABLE admissions(id TEXT PRIMARY KEY, request_sha TEXT, "
                        "request_json BLOB, binding BLOB, state TEXT)"
                    )
                    db.execute(
                        "INSERT INTO admissions VALUES (?,?,?,?,?)",
                        (
                            admission,
                            data.digest(request),
                            data.canonical(request),
                            data.canonical(binding),
                            state,
                        ),
                    )
                database.chmod(0o600)
                if state == "released":
                    dest = home / admission
                    dest.mkdir(mode=0o700)
                    (dest / "release.json").write_bytes(b"original owner delivery")
                before = {
                    str(p.relative_to(home)): p.read_bytes()
                    for p in home.rglob("*")
                    if p.is_file()
                }
                with self.assertRaisesRegex(
                    ValueError, "ORIGINAL_TURN_VERIFIER_REQUIRED"
                ):
                    paired_intake.release(home, admission)
                status = paired_intake.people_status(home, admission)
                self.assertTrue(status["retained_enrollment_binding_present"])
                for key in (
                    "original_enrollment_bindings_checked",
                    "site_attested_distinct_people",
                    "original_turn_consent_verified",
                    "production_authorization_available",
                ):
                    self.assertIs(status[key], False)
                self.assertEqual(
                    {
                        str(p.relative_to(home)): p.read_bytes()
                        for p in home.rglob("*")
                        if p.is_file()
                    },
                    before,
                )

    def test_owner_source_score_refuses_before_reading_training_materials(self):
        operation = self.root / "operation"
        operation.mkdir()
        completed = operation / "COMPLETED.json"
        completed.write_bytes(data.canonical({"scope": "owner_intake"}))
        before = completed.read_bytes()
        with self.assertRaisesRegex(ValueError, "ORIGINAL_TURN_VERIFIER_REQUIRED"):
            paired_source_gate.gate(self.root / "unprovided-private-A", operation)
        self.assertEqual(list(operation.iterdir()), [completed])
        self.assertEqual(completed.read_bytes(), before)

    def test_owner_retention_cannot_authorize_or_publish_a_new_freeze_witness(self):
        report = self.root / "RETENTION.json"
        report.write_bytes(data.canonical({"scope": "owner_intake"}))
        inbox = self.root / "inbox"
        inbox.mkdir(mode=0o700)
        study, freeze = data.digest("fixture study"), data.digest("fixture freeze")
        actions = (
            lambda: paired_source_dispatch.authorize({}, {}, report),
            lambda: paired_source_dispatch.verify_originals(report, study, freeze),
            lambda: paired_observation.observe(
                inbox, study, freeze, 2, source_retention=report
            ),
        )
        before = report.read_bytes()
        for index, action in enumerate(actions):
            with self.subTest(entry=index):
                with self.assertRaisesRegex(
                    ValueError, "ORIGINAL_TURN_VERIFIER_REQUIRED"
                ):
                    action()
        self.assertEqual(list(inbox.iterdir()), [])
        self.assertEqual(report.read_bytes(), before)

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
