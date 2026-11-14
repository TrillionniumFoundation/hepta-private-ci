"""Actual tiny decoder lifecycle tests, not pretrained memory capability claims."""

from functools import partial
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from memory_service import MemoryService, read_local
import test_parametric_model as tiny
from service_types import LeaseLost, ReadStatus
from training_backend import train_candidate, verify_candidate


class SimulatedCrash(BaseException):
    pass


class MemoryServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tiny.SourceMemoryCellTests.setUpClass()
        cls.base = tiny.SourceMemoryCellTests.base

    @classmethod
    def tearDownClass(cls):
        tiny.SourceMemoryCellTests.tearDownClass()

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.service = MemoryService(self.root, "alpha")

    def train(self):
        return self.service.work_once(
            self.base, steps=4, rank=2, templates=tiny.TEMPLATES
        )

    def query(self, reader):
        return self.service.invoke_parameter(
            "one", "color", "What is the color of one?", reader
        )

    def test_overlay_and_actual_cold_parameter_read_keep_separate_origins(self):
        source = self.service.write("s1", "one", "color", "red")
        self.assertEqual(self.service.read("one", "color").origin, "source_overlay")
        reader = Mock()
        self.assertEqual(self.query(reader)["status"], "unavailable")
        reader.assert_not_called()
        result = self.train()
        self.assertEqual(result["status"], "published")
        self.assertGreater(result["training"]["adapter_delta_squared_norm"], 0)
        self.assertEqual(result["training"]["roots"], [source.source_digest])
        binding = self.service.parameter_binding()
        self.assertEqual(binding["role"], "semantic")
        self.service = MemoryService(self.root, "alpha")
        self.assertEqual(self.service.parameter_binding(), binding)
        response = self.query(partial(read_local, base_dir=self.base))
        self.assertEqual(
            (response["status"], response["origin"], response["correctness_verified"]),
            ("generated", "parameters", False),
        )
        self.assertEqual(response["response"]["evidence"], [])
        self.assertIn("token_ids", response["response"])
        self.assertEqual(self.train(), {"status": "idle"})

    def test_unknown_conflict_and_revoked_never_call_decoder(self):
        reader = Mock()
        self.assertEqual(self.query(reader)["status"], "unknown")
        self.service.write("s1", "one", "color", "red")
        self.train()
        self.service.write("s2", "one", "color", "blue")
        self.assertEqual(self.query(reader)["status"], "conflict")
        self.service.revoke("s1", 0)
        self.service.revoke("s2", 0)
        self.assertEqual(self.query(reader)["status"], "revoked")
        reader.assert_not_called()
        # An empty live dataset needs neither a model nor another checkpoint.
        self.assertEqual(self.service.work_once("missing-base")["status"], "empty")
        self.assertIsNone(self.service.parameter_binding())

    def test_correction_invalidates_old_epoch_then_clean_replays(self):
        first = self.service.write("s1", "one", "color", "red")
        previous = self.train()
        corrected = self.service.correct("s1", "blue", 0)
        reader = Mock()
        self.assertEqual(self.query(reader)["status"], "unavailable")
        reader.assert_not_called()
        self.assertEqual(self.service.read("one", "color").answer, "blue")
        result = self.train()
        self.assertEqual(
            (result["epoch"], result["generation"]), (corrected.source_epoch, 1)
        )
        self.assertNotEqual(result["manifest_sha256"], previous["manifest_sha256"])
        self.assertEqual(result["training"]["roots"], [corrected.source_digest])
        self.assertEqual(result["training"]["initialization"], "frozen_base")
        self.assertEqual(result["training"]["inherited_roots"], [])
        self.assertIn(first.source_digest, self.service.authority_view().revoked)
        raw = {"text": "deliberately incorrect", "token_ids": [9], "evidence": []}
        response = self.query(lambda active, question: raw)
        self.assertEqual(response["response"], raw)
        self.assertIs(response["correctness_verified"], False)

    def test_inflight_correction_and_revocation_suppress_generated_bytes(self):
        self.service.write("s1", "one", "color", "red")
        for action in (
            lambda: self.service.correct("s1", "blue", 0),
            lambda: self.service.revoke("s1", 1),
        ):
            self.train()
            calls = []

            def reader(active, question):
                calls.append(active.manifest_sha256)
                action()
                return {"text": "old value must not escape"}

            result = self.query(reader)
            self.assertEqual(len(calls), 1)
            self.assertEqual(
                (result["status"], result["response"]), ("indeterminate", None)
            )

    def test_source_change_while_training_cannot_publish_stale_candidate(self):
        receipt = self.service.write("s1", "one", "color", "red")

        def changed(*args, **kwargs):
            candidate = train_candidate(*args, **kwargs)
            self.service.correct("s1", "blue", 0)
            return candidate

        with patch("memory_service.train_candidate", side_effect=changed):
            result = self.train()
        self.assertEqual(result["status"], "superseded")
        self.assertEqual(
            self.service.queue.status(receipt.training_job_id)["state"], "superseded"
        )
        self.assertIsNone(self.service.owner.current("memory", "alpha"))
        self.assertEqual(self.train()["status"], "published")

    def test_restart_reconciles_owner_commit_before_source_binding_without_retrain(
        self,
    ):
        self.service.write("s1", "one", "color", "red")
        activate = self.service.owner.activate

        def crashed(*args, **kwargs):
            activate(*args, **kwargs)
            raise SimulatedCrash()

        with patch.object(self.service.owner, "activate", side_effect=crashed):
            with self.assertRaises(SimulatedCrash):
                self.train()
        committed = self.service.owner.current("memory", "alpha")
        self.assertIsNotNone(committed)
        self.assertIsNone(self.service.parameter_binding())
        with self.service.store.transaction() as db:
            db.execute(
                "UPDATE jobs SET deadline=? WHERE state='running'", (time.time() - 1,)
            )
        self.service = MemoryService(self.root, "alpha")
        with patch(
            "memory_service.train_candidate",
            side_effect=AssertionError("must recover staged bytes"),
        ):
            result = self.service.work_once("missing-base")
        self.assertEqual(
            (result["status"], result["manifest_sha256"], result["generation"]),
            ("published", committed.manifest_sha256, 0),
        )
        self.assertEqual(self.service.parameter_binding()["active"], committed)

    def test_checkpoint_mutation_fails_closed_before_callback(self):
        self.service.write("s1", "one", "color", "red")
        result = self.train()
        (Path(result["directory"]) / "lineage.json").write_text("{}")
        reader = Mock()
        response = self.query(reader)
        self.assertEqual(
            (response["status"], response["response"]), ("indeterminate", None)
        )
        reader.assert_not_called()

    def test_staged_candidate_recovers_after_ordinary_publication_exception(self):
        receipt = self.service.write("s1", "one", "color", "red")
        activate = self.service.owner.activate

        def interrupted(*args, **kwargs):
            activate(*args, **kwargs)
            raise OSError("source binding commit interrupted")

        with patch.object(self.service.owner, "activate", side_effect=interrupted):
            with self.assertRaisesRegex(OSError, "commit interrupted"):
                self.train()
        committed = self.service.owner.current("memory", "alpha")
        self.assertIsNone(self.service.parameter_binding())
        staged = self.service.queue.status(receipt.training_job_id)
        self.assertEqual(staged["state"], "queued")
        with patch(
            "memory_service.train_candidate",
            side_effect=AssertionError("must reconcile same candidate"),
        ):
            result = self.service.work_once("missing-base")
        self.assertEqual(
            (result["status"], result["generation"], result["manifest_sha256"]),
            ("published", 0, committed.manifest_sha256),
        )
        completed = self.service.queue.status(receipt.training_job_id)
        self.assertEqual(
            (completed["state"], completed["attempt"], completed["candidate"]),
            ("completed", 2, staged["candidate"]),
        )

    def test_lease_expiration_before_or_after_owner_activation_never_binds(self):
        for stage in ("before_activation", "after_activation"):
            with self.subTest(stage=stage):
                self.service = MemoryService(self.root / stage, "alpha")
                receipt = self.service.write("s1", "one", "color", "red")
                activate = self.service.owner.activate
                expired = [False]

                def validated(*args, **kwargs):
                    training = verify_candidate(*args, **kwargs)
                    if stage == "before_activation":
                        expired[0] = True
                    return training

                def activated(*args, **kwargs):
                    active = activate(*args, **kwargs)
                    expired[0] = True
                    return active

                def now(value=None):
                    return (
                        time.time() + (4000 if expired[0] else 0)
                        if value is None
                        else value
                    )

                with patch("training_queue.clock", side_effect=now):
                    with patch(
                        "parameter_publication.verify_candidate", side_effect=validated
                    ):
                        with patch.object(
                            self.service.owner, "activate", side_effect=activated
                        ):
                            with self.assertRaises(LeaseLost):
                                self.train()
                    self.assertIsNone(self.service.parameter_binding())
                    current = self.service.owner.current("memory", "alpha")
                    self.assertEqual(current is None, stage == "before_activation")
                    self.assertEqual(
                        self.service.queue.status(receipt.training_job_id)["state"],
                        "running",
                    )
                    with patch(
                        "memory_service.train_candidate",
                        side_effect=AssertionError("must recover staged bytes"),
                    ):
                        result = self.service.work_once("missing-base")
                self.assertEqual(
                    (result["status"], result["generation"]), ("published", 0)
                )

    def test_role_and_source_authority_scope_are_bound(self):
        self.service = MemoryService(
            self.root / "procedure", "alpha", role="procedural"
        )
        receipt = self.service.write("ci/retained-evidence", "one", "color", "red")
        self.train()
        self.assertEqual(self.service.parameter_binding()["role"], "procedural")
        self.assertEqual(self.service.snapshot()["sources"][0]["role"], "procedural")
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            MemoryService(self.root / "procedure", "alpha", role="semantic")
        with self.assertRaisesRegex(ValueError, "scope mismatch"):
            self.service.authority_view("other")
        self.service.revoke("ci/retained-evidence", 0)
        self.assertEqual(self.service.read("one", "color").status, ReadStatus.REVOKED)
        self.assertIn(receipt.source_digest, self.service.authority_view().revoked)

    def test_independent_background_process_claims_persistent_source_queue(self):
        self.service.write("s1", "one", "color", "red")
        run = subprocess.run(
            [
                sys.executable,
                "-B",
                str(Path(__file__).with_name("training_worker.py")),
                "--root",
                str(self.root),
                "--scope",
                "alpha",
                "--base",
                str(self.base),
                "--steps",
                "4",
                "--rank",
                "2",
                "--once",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        result = json.loads(run.stdout)
        self.assertEqual(result["status"], "published")
        reopened = MemoryService(self.root, "alpha")
        self.assertEqual(
            reopened.parameter_binding()["active"].manifest_sha256,
            result["manifest_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
