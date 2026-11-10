"""Behavioral rejection tests against real continuation and destination files."""

import argparse
import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import run
import models
import sqlite_destination
import continuation
from continuation import Continuation, RecoveryError, canonical, digest


class ContinuationTests(unittest.TestCase):
    model_path = None

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.task = next(t for t in run.tasks("confirm") if t["fault"] == "normal")
        self.root = Path(self.temp.name) / "owner"
        self.owner = Continuation.start(self.task, self.model_path, self.root)
        self.addCleanup(self.owner.destination.db.close)

    def reject(self, task=None, snapshot=None):
        with self.assertRaises(RecoveryError):
            Continuation.restore(
                self.task if task is None else task,
                self.model_path,
                self.root,
                snapshot,
            )

    def test_checksum_hidden_and_unknown_fields_reject_before_any_effect(self):
        before = self.owner.destination.db.execute(
            "SELECT COUNT(*) FROM act3_calls"
        ).fetchone()
        damaged = bytearray(self.owner.snapshot())
        damaged[-5] ^= 1
        self.reject(snapshot=bytes(damaged))
        for key, value in (
            ("hidden", "00"),
            ("hidden", "000000000000f87f" * 12),
            ("sequence", True),
            ("unexpected", 1),
        ):
            envelope = json.loads(self.owner.snapshot())
            envelope["state"][key] = value
            envelope["sha256"] = digest(canonical(envelope["state"]))
            self.reject(snapshot=canonical(envelope))
        self.assertEqual(
            before,
            self.owner.destination.db.execute(
                "SELECT COUNT(*) FROM act3_calls"
            ).fetchone(),
        )

    def test_task_model_feature_and_contract_bindings(self):
        task = copy.deepcopy(self.task)
        task["goals"][0] = "different"
        self.reject(task=task)
        for key in (
            "model",
            "features",
            "model_code",
            "provider_code",
            "contract",
            "purpose",
        ):
            envelope = json.loads(self.owner.snapshot())
            envelope["state"]["binding"][key] = "different"
            envelope["sha256"] = digest(canonical(envelope["state"]))
            self.reject(snapshot=canonical(envelope))

    def test_checkpoint_and_budget_rewind_rejected(self):
        earlier = self.owner.snapshot()
        self.owner.step()
        self.reject(snapshot=earlier)
        with self.owner.destination.db:
            self.owner.destination.db.execute("DELETE FROM act3_calls")
        self.reject()

    def test_actual_copied_provider_source_drift_rejects_in_new_process(self):
        copied = Path(self.temp.name) / "changed-provider"
        copied.mkdir()
        for module in (run, models, sqlite_destination, continuation):
            shutil.copy2(module.__file__, copied / Path(module.__file__).name)
        provider = copied / "sqlite_destination.py"
        provider.write_text(
            provider.read_text() + "\n# Different provider source version.\n"
        )
        probe = "import json,sys\nfrom continuation import Continuation,RecoveryError\ntry:\n Continuation.restore(json.loads(sys.argv[1]),sys.argv[2],sys.argv[3])\nexcept RecoveryError as error:\n assert 'binding' in str(error)\nelse:\n raise AssertionError('provider drift accepted')\n"
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                probe,
                json.dumps(self.task),
                str(self.model_path.resolve()),
                str(self.root),
            ],
            cwd=copied,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_missing_and_mismatched_effect_owner_rejected(self):
        self.owner.step()
        self.owner.step()
        with self.owner.destination.db:
            self.owner.destination.db.execute("UPDATE applied SET payload='wrong'")
        self.reject()
        with self.owner.destination.db:
            self.owner.destination.db.execute("DROP TABLE act3_owner")
        self.reject()

    def test_unavailable_owner_does_not_recover_effects_or_claim_success(self):
        task = {**self.task, "fault": "opaque_after_apply"}
        owner = Continuation.start(
            task, self.model_path, Path(self.temp.name) / "opaque"
        )
        self.addCleanup(owner.destination.db.close)
        owner.step()
        owner.step()
        with self.assertRaisesRegex(RecoveryError, "observation unavailable"):
            Continuation.restore(task, self.model_path, owner.directory)
        self.assertFalse(owner.state["claimed"])
        self.assertEqual(
            1,
            owner.destination.db.execute("SELECT COUNT(*) FROM effects").fetchone()[0],
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, type=Path)
    args, remaining = parser.parse_known_args()
    ContinuationTests.model_path = args.model
    unittest.main(argv=[__file__] + remaining)
