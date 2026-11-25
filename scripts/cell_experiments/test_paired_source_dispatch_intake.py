"""A source-retention commitment cannot repair the legacy native consent boundary."""

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from . import data, paired_intake, paired_observation, paired_source_gate
from .test_prospective_exposure import SNAPSHOT, artificial


class SourceDispatchPublicationTests(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.root = Path(d.name)
        self.inbox = self.root / "fixture-source-owner"
        self.inbox.mkdir(mode=0o700)
        self.home = self.root / "journal"
        # The archived pair passed its old item. Add synthetic source provenance
        # only to exercise the new-candidate shape without another model fit.
        self.snapshot = json.loads(SNAPSHOT.read_bytes())
        self.snapshot["candidate"]["paired_source_exposure"] = dict(
            registered_catalogs=[],
            known_prompt_hashes=[],
            input_ids_sha256=[],
            source_keys=[],
        )
        self.freeze = data.digest(self.snapshot)
        self.study = data.digest("fictional source intake, no human participants")
        self.snapshot_path = self.root / "FROZEN.json"
        self.snapshot_path.write_bytes(data.canonical(self.snapshot))
        self.report = dict(
            schema="hepta.paired-learning.source-retention.v1",
            policy=paired_source_gate.POLICY,
            freeze_sha256=self.freeze,
            parent_sha256=data.digest(self.snapshot["parent"]),
            candidate_sha256=data.digest(self.snapshot["candidate"]),
            prospective_records_read=0,
            scope="owner_intake",
            decision="eligible_for_prospective_evaluation",
            comparisons=[
                dict(
                    panel="retention",
                    record_sha256=data.record_digest(row),
                    parent=True,
                    candidate=True,
                )
                for row in self.snapshot["retention"]
            ],
        )
        self.report_path = self.root / "RETENTION.json"
        self.report_path.write_bytes(data.canonical(self.report))
        self.gate = data.digest(self.report)
        self.native = Path(sys.executable).resolve()
        with self.native.open("rb") as f:
            native_sha = hashlib.file_digest(f, "sha256").hexdigest()
        self.opts = SimpleNamespace(
            home=self.home,
            snapshot=self.snapshot_path,
            study=self.study,
            freeze=self.freeze,
            native=self.native,
            native_sha256=native_sha,
            inbox=self.inbox,
            scope="owner_intake",
            source_retention=self.report_path,
        )

    def anchor(self):
        argv = [
            "paired_observation",
            str(self.inbox),
            self.study,
            self.freeze,
            "2",
            "freeze",
            "--source-retention",
            str(self.report_path),
        ]
        with (
            patch.object(sys, "argv", argv),
            patch(
                "cell_experiments.paired_source_dispatch.verify_originals",
                return_value=self.gate,
                create=True,
            ) as scorer,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            paired_observation.main()
        scorer.assert_called_once_with(self.report_path, self.study, self.freeze)
        return json.loads((self.inbox / "freeze.json").read_bytes())

    def test_normal_observer_requires_originals_before_freeze_is_published(self):
        with patch(
            "cell_experiments.paired_source_dispatch.verify_originals",
            side_effect=ValueError("original inputs differ"),
            create=True,
        ):
            with self.assertRaisesRegex(ValueError, "original inputs differ"):
                paired_observation.observe(
                    self.inbox,
                    self.study,
                    self.freeze,
                    2,
                    source_retention=self.report_path,
                )
        self.assertFalse((self.inbox / "freeze.json").exists())
        self.assertEqual(self.anchor()["source_retention_sha256"], self.gate)
        with self.assertRaisesRegex(ValueError, "ORIGINAL_TURN_VERIFIER_REQUIRED"):
            paired_intake.install(self.opts)
        self.assertFalse(self.home.exists())

    def test_qualified_source_digest_cannot_enable_the_legacy_owner_cli(self):
        self.anchor()
        run = subprocess.run(
            [
                sys.executable,
                "-m",
                "cell_experiments.paired_intake",
                str(self.home),
                "install",
                str(self.snapshot_path),
                self.study,
                self.freeze,
                str(self.inbox),
                str(self.native),
                self.opts.native_sha256,
                "--source-retention",
                str(self.report_path),
                "--scope",
                "owner_intake",
            ],
            capture_output=True,
            text=True,
            timeout=90,
            env={
                **os.environ,
                "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                "HF_HUB_OFFLINE": "1",
            },
        )
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("ORIGINAL_TURN_VERIFIER_REQUIRED", run.stderr)
        self.assertEqual(run.stdout, "")
        self.assertFalse(self.home.exists())

    def test_legacy_ready_publishing_and_released_stay_historical(self):
        self.anchor()
        # Reconstruct the shape of a historical owner store as an explicit
        # negative fixture; no native owner or person is enrolled by this test.
        self.opts.scope = "engineering_fixture"
        paired_intake.install(self.opts)
        with contextlib.closing(paired_intake.open_database(self.home)) as db:
            cfg = json.loads(db.execute("select value from settings").fetchone()[0])
            cfg["scope"] = "owner_intake"
            cfg["qualified_source_retention"] = self.gate
            db.execute("update settings set value=?", (json.dumps(cfg),))
            for i, state in enumerate(("ready", "publishing", "released")):
                request = {
                    **self.snapshot,
                    "schema": "hepta.paired-cold.request.v1",
                    "future": [artificial(14200 + i)],
                }
                request_sha = data.digest(request)
                # These are original pre-gate bindings. Some old observers already pinned
                # a hash in their own anchor, without binding it in the outgoing release.
                binding = dict(
                    anchor=cfg["anchor"],
                    release=dict(scope="owner_intake", request_sha256=request_sha),
                )
                prior = data.digest(binding)
                db.execute(
                    "insert into admissions values (?,?,?,?,?,?,?)",
                    (
                        prior,
                        data.digest(i),
                        i + 3,
                        request_sha,
                        data.canonical(request),
                        data.canonical(binding),
                        state,
                    ),
                )
                dest = self.home / prior
                if state == "released":
                    dest.mkdir()
                    (dest / "release.json").write_bytes(b"original historical release")
                with self.assertRaisesRegex(
                    ValueError, "ORIGINAL_TURN_VERIFIER_REQUIRED"
                ):
                    paired_intake.release(self.home, prior)
                self.assertEqual(
                    db.execute(
                        "select state from admissions where id=?", (prior,)
                    ).fetchone()[0],
                    state,
                )
                if state == "released":
                    self.assertEqual(
                        (dest / "release.json").read_bytes(),
                        b"original historical release",
                    )
                else:
                    self.assertFalse(dest.exists())
