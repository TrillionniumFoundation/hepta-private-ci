"""Persisted engineering recovery controls; no participant or model execution."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import data, paired_consumer as owner


class ConsumerJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.selection = data.digest("engineering selection")
        self.req = {"candidate": {"engineering_model": True}}
        self.task = {"input": "synthetic subsequent task"}
        self.scope = owner.request_scope(
            data.digest("engineering admission"),
            {
                "request_sha256": data.digest("engineering pair"),
                "candidate_sha256": data.digest(self.req["candidate"]),
            },
            data.digest(self.task),
            self.selection,
        )
        self.path = self.root / self.scope["operation"]
        self.path.mkdir(mode=0o700)
        self.tokens = [1, 8, 4]
        self.answer = b"synthetic output"
        self.grant = {"delivery_id": data.digest("engineering delivery")}
        self.started = {
            "request": self.scope,
            "nonce": data.digest("engineering nonce"),
            "grant": self.grant,
            "local_selection_sha256": self.selection,
        }
        self.payload = {
            "task": self.task,
            "nonce": self.started["nonce"],
            "candidate": self.scope["candidate"],
            "model": self.req["candidate"],
        }
        self.wire = {
            "nonce": self.started["nonce"],
            "prediction": {"pid": 314, "fixture": "not model evidence"},
        }
        self.run = {
            "schema": "hepta.paired-learning.consumer-run.v1",
            "request": self.scope,
            "nonce": self.started["nonce"],
            "selection_sha256": self.selection,
            "grant_sha256": data.digest(self.grant),
            "prediction_sha256": data.digest(self.wire),
            "local_child_pid": self.wire["prediction"]["pid"],
            "output_sha256": owner.intake.sha(self.answer),
        }
        for name, value in (
            ("STARTED.json", self.started),
            ("worker-input.json", self.payload),
            ("worker-output.json", self.wire),
            ("RUN.json", self.run),
        ):
            owner.put(self.path / name, value)
        (self.path / "answer.utf8").write_bytes(self.answer)
        self.reservations = (
            self.root / ("request-delivery-" + self.grant["delivery_id"] + ".json"),
            self.root / ("tokens-" + data.digest(self.tokens) + ".json"),
        )
        for path in self.reservations:
            owner.put(path, {"operation": self.scope["operation"]})

    def read_run(self):
        # Only numerical model work is isolated. Real consumer readback reads
        # the retained files and the same exclusive markers written by execute.
        with patch.object(
            owner.cold,
            "_inspect_with_encoding",
            return_value=(self.answer, tuple(self.tokens)),
        ):
            return owner.read_run(
                self.path, self.scope, self.selection, self.req, self.root
            )

    def snapshot(self):
        return {
            str(path.relative_to(self.root)): ("symlink", str(path.readlink()))
            if path.is_symlink()
            else path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file() or path.is_symlink()
        }

    def test_complete_run_reads_the_original_reservations_without_writes(self):
        before = self.snapshot()
        self.assertEqual(self.read_run(), self.run)
        self.assertEqual(self.snapshot(), before)

    def test_missing_or_rebound_reservation_refuses_and_never_repairs(self):
        for path in self.reservations:
            original = path.read_bytes()
            for damage in ("missing", "rebound"):
                with self.subTest(path=path.name, damage=damage):
                    path.unlink()
                    if damage == "rebound":
                        owner.put(path, {"operation": data.digest("another operation")})
                    before = self.snapshot()
                    with self.assertRaisesRegex(ValueError, "single-use reservation"):
                        self.read_run()
                    self.assertEqual(self.snapshot(), before)
                path.unlink(missing_ok=True)
                path.write_bytes(original)
                path.chmod(0o600)

    def test_reservation_rejects_symlink_public_file_fifo_and_directory_without_reading(
        self,
    ):
        path = self.reservations[0]
        original = path.read_bytes()
        target = self.root / "substitute.json"
        target.write_bytes(original)
        target.chmod(0o600)
        for damage in ("symlink", "public", "fifo", "directory"):
            with self.subTest(damage=damage):
                path.unlink()
                if damage == "symlink":
                    path.symlink_to(target)
                elif damage == "public":
                    path.write_bytes(original)
                    path.chmod(0o644)
                elif damage == "fifo":
                    os.mkfifo(path, 0o600)
                else:
                    path.mkdir(mode=0o700)
                with (
                    patch.object(owner.cold, "encoding") as encode,
                    patch.object(owner.cold, "_inspect_with_encoding") as inspect,
                ):
                    with self.assertRaisesRegex(ValueError, "single-use reservation"):
                        owner.read_run(
                            self.path, self.scope, self.selection, self.req, self.root
                        )
                encode.assert_not_called()
                inspect.assert_not_called()
                if path.is_dir():
                    path.rmdir()
                else:
                    path.unlink()
                path.write_bytes(original)
                path.chmod(0o600)

    def test_completed_execution_cannot_reenter_after_its_delivery_fence_is_lost(self):
        self.reservations[0].unlink()
        before = self.snapshot()
        with (
            patch.object(owner, "private_material") as private_read,
            patch.object(owner.subprocess, "Popen") as spawn,
        ):
            with self.assertRaisesRegex(ValueError, "single-use reservation"):
                owner.execute(
                    self.path,
                    {},
                    self.req,
                    self.scope,
                    self.selection,
                    self.grant,
                    self.root,
                )
        private_read.assert_not_called()
        spawn.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_rebound_worker_candidate_refuses_before_inspecting_materials(self):
        payload = dict(self.payload, candidate=data.digest("different candidate"))
        (self.path / "worker-input.json").write_bytes(data.canonical(payload))
        with (
            patch.object(owner.cold, "encoding") as encode,
            patch.object(owner.cold, "_inspect_with_encoding") as inspect,
        ):
            with self.assertRaisesRegex(ValueError, "retained worker input"):
                owner.read_run(
                    self.path, self.scope, self.selection, self.req, self.root
                )
        encode.assert_not_called()
        inspect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
