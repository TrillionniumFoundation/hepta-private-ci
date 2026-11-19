"""Independent integrity/fault controls; these constructed weights prove no gain."""

from dataclasses import asdict
import io
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
import zipfile

import numpy as np

from durable_lifecycle import canonical, sha
from models import Model
from recurrent_lifecycle import RecurrentLifecycle
from skill_lifecycle import SkillContract, goals_digest


class RecurrentAdversarialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.task = {
            "id": "independent-original",
            "version": 1,
            "goals": ["original payload"],
            "fault": "normal",
        }
        self.contract = SkillContract(
            self.task["id"],
            1,
            goals_digest(self.task["goals"]),
            time.monotonic_ns() + 120_000_000_000,
            1,
        )
        self.model = self.root / "model.npz"
        self.weights = Model("gru", 41).p
        self.weights["V"][:] = 0
        self.weights["c"][:] = (0, 0, 10)
        np.savez(self.model, **self.weights)
        self.session = self.root / "session"

    def start(self):
        return RecurrentLifecycle.start(
            self.task, self.contract, self.model, self.session
        )

    def restore(self, session=None):
        return RecurrentLifecycle.restore(
            self.task, self.contract, self.model, session or self.session
        )

    def row(self):
        with sqlite3.connect(self.session / "control.db") as db:
            return db.execute("SELECT revision,digest,body FROM state").fetchone()

    def replace_raw(self, raw):
        with sqlite3.connect(self.session / "control.db") as db:
            db.execute("UPDATE state SET digest=?,body=?", (sha(raw), raw))

    def snapshot(self):
        return {
            str(p.relative_to(self.session)): p.read_bytes()
            for p in self.session.rglob("*")
            if p.is_file()
        }

    def test_invalid_private_state_never_mutates_rejected_owner(self):
        driver = self.start()
        driver.step()
        driver.close()
        original = json.loads(self.row()[2])
        for case in (
            "short_hidden",
            "nonfinite_hidden",
            "wrong_phase",
            "foreign_invocation",
        ):
            with self.subTest(case=case):
                saved = json.loads(canonical(original))
                policy = saved["fields"]["policy"]
                if case == "short_hidden":
                    policy["hidden"] = "00"
                elif case == "nonfinite_hidden":
                    policy["hidden"] = np.full(12, np.nan, dtype="<f8").tobytes().hex()
                elif case == "wrong_phase":
                    policy["phase"] = "adopted"
                else:
                    policy.update(
                        phase="prepared",
                        decisions=["ensure"],
                        sequence=1,
                        pending={
                            "action": "ensure",
                            "proposed": "ensure",
                            "key": 0,
                            "invocation": "foreign:0",
                            "goal_sha256": sha(self.task["goals"][0].encode()),
                        },
                    )
                self.replace_raw(canonical(saved))
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    self.restore()
                self.assertEqual(self.snapshot(), before)

    def test_duplicate_checkpoint_keys_are_rejected_without_write(self):
        driver = self.start()
        driver.close()
        raw = self.row()[2]
        saved = json.loads(raw)
        self.replace_raw(raw[:-1] + b',"fields":' + canonical(saved["fields"]) + b"}")
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "noncanonical"):
            self.restore()
        self.assertEqual(self.snapshot(), before)

    def test_synthetic_boot_uid_and_configuration_mismatch_do_not_write(self):
        driver = self.start()
        driver.close()
        original = json.loads(self.row()[2])
        for case in ("boot", "uid", "configuration"):
            with self.subTest(case=case):
                saved = json.loads(canonical(original))
                if case == "boot":
                    saved["binding"]["boot"] = "00000000-0000-0000-0000-000000000000"
                elif case == "uid":
                    saved["binding"]["controller"]["uid"] += 1
                else:
                    saved["binding"]["controller"]["configuration"]["hidden"] += 1
                self.replace_raw(canonical(saved))
                before = self.snapshot()
                with self.assertRaisesRegex(ValueError, "drift"):
                    self.restore()
                self.assertEqual(self.snapshot(), before)

    def test_live_configuration_change_cannot_rebind_existing_model(self):
        driver = self.start()
        original = json.loads(canonical(driver.expected["controller"]["configuration"]))
        before = self.snapshot()
        try:
            with mock.patch.dict("recurrent_lifecycle.CONFIG", {"hidden": 13}):
                try:
                    driver.pause()
                except ValueError:
                    self.assertEqual(self.snapshot(), before)
                else:
                    saved = json.loads(self.row()[2])
                    self.assertEqual(
                        saved["binding"]["controller"]["configuration"], original
                    )
        finally:
            driver.close()

    def test_foreign_model_or_simulated_boot_is_rejected_before_database_open(self):
        driver = self.start()
        driver.close()
        original_model = self.model.read_bytes()
        original_read = Path.read_text

        def foreign_boot(path, *args, **kwargs):
            if path == Path("/proc/sys/kernel/random/boot_id"):
                return "00000000-0000-0000-0000-000000000000\n"
            return original_read(path, *args, **kwargs)

        for case in ("changed_model", "simulated_boot"):
            with self.subTest(case=case):
                self.model.write_bytes(original_model)
                if case == "changed_model":
                    altered = {k: value.copy() for k, value in self.weights.items()}
                    altered["c"][:] = (10, 0, 0)
                    np.savez(self.model, **altered)
                before = self.snapshot()
                read = foreign_boot if case == "simulated_boot" else original_read
                with (
                    mock.patch.object(Path, "read_text", new=read),
                    mock.patch(
                        "durable_lifecycle.sqlite3.connect",
                        side_effect=AssertionError("foreign restore opened database"),
                    ) as connection,
                ):
                    with self.assertRaises(ValueError):
                        self.restore()
                    connection.assert_not_called()
                self.assertEqual(self.snapshot(), before)

    def test_copied_owner_and_symlink_alias_are_rejected(self):
        driver = self.start()
        driver.close()
        copied, alias = self.root / "copied", self.root / "alias"
        shutil.copytree(self.session, copied)
        alias.symlink_to(self.session, target_is_directory=True)
        original = self.snapshot()
        copied_db = (copied / "control.db").read_bytes()
        for candidate in (copied, alias):
            with self.subTest(path=candidate.name), self.assertRaises(ValueError):
                self.restore(candidate)
        self.assertEqual(self.snapshot(), original)
        self.assertEqual((copied / "control.db").read_bytes(), copied_db)

    def test_missing_original_lock_is_not_recreated_on_reject(self):
        driver = self.start()
        driver.close()
        lock = self.session / "writer.lock"
        lock.unlink()
        before = self.snapshot()
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.restore()
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(lock.exists())

    def test_symlinked_effect_directory_is_not_followed_on_restore(self):
        driver = self.start()
        driver.close()
        effects = self.session / "destination/effects"
        original = self.session / "original-effects"
        effects.rename(original)
        effects.symlink_to(original, target_is_directory=True)
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.restore()
        self.assertEqual(self.snapshot(), before)

    def test_terminal_success_is_checked_again_after_original_payload_disappears(self):
        driver = self.start()
        for _ in range(8):
            if not driver.step():
                break
        self.assertEqual(driver.policy["phase"], "terminal")
        self.assertTrue(driver.report()["claimed_success"])
        hidden = driver.policy["hidden"]
        driver.close()
        effects = self.session / "destination/effects"
        shutil.rmtree(next(effects.iterdir()))
        restored = self.restore()
        try:
            result = restored.report()
            self.assertEqual(
                (
                    result["claimed_success"],
                    result["complete"],
                    result["false_success"],
                    result["effect_count"],
                ),
                (False, False, False, 0),
            )
            self.assertEqual(restored.policy["hidden"], hidden)
        finally:
            restored.close()

    def test_model_hash_and_loaded_tensors_use_same_original_snapshot(self):
        raw = self.model.read_bytes()
        other = self.root / "other.npz"
        altered = {k: value.copy() for k, value in self.weights.items()}
        altered["c"][:] = (10, 0, 0)
        np.savez(other, **altered)
        original_zip = zipfile.ZipFile

        def replace_after_snapshot(*args, **kwargs):
            self.model.write_bytes(other.read_bytes())
            return original_zip(*args, **kwargs)

        with mock.patch(
            "recurrent_lifecycle.zipfile.ZipFile", side_effect=replace_after_snapshot
        ):
            driver = self.start()
        try:
            self.assertEqual(driver.expected["model"], sha(raw))
            for key, value in self.weights.items():
                np.testing.assert_array_equal(driver.model.p[key], value)
        finally:
            driver.close()
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "drift"):
            self.restore()
        self.assertEqual(self.snapshot(), before)

    def test_oversized_compressed_tensor_is_rejected_before_owner_creation(self):
        with zipfile.ZipFile(io.BytesIO(self.model.read_bytes())) as original:
            members = {name: original.read(name) for name in original.namelist()}
        members["Wz.npy"] = b"0" * 65537
        with zipfile.ZipFile(self.model, "w", zipfile.ZIP_DEFLATED) as oversized:
            for name, payload in members.items():
                oversized.writestr(name, payload)
        self.assertLess(self.model.stat().st_size, 1_000_000)
        with self.assertRaisesRegex(ValueError, "exceed contract"):
            self.start()
        self.assertFalse(self.session.exists())

    def test_changed_guard_source_in_fresh_interpreter_rejects_without_write(self):
        driver = self.start()
        driver.close()
        source = self.root / "source"
        source.mkdir()
        for path in Path(__file__).parent.glob("*.py"):
            shutil.copy2(path, source / path.name)
        guard = source / "diagnose.py"
        guard.write_bytes(
            guard.read_bytes() + b"\n# independently changed guard source\n"
        )
        inputs = self.root / "input.json"
        inputs.write_text(
            json.dumps({"task": self.task, "contract": asdict(self.contract)})
        )
        before = self.snapshot()
        script = """
import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from recurrent_lifecycle import RecurrentLifecycle
from skill_lifecycle import SkillContract
root=Path(sys.argv[2]); inputs=json.loads((root/'input.json').read_text())
try:
    value=RecurrentLifecycle.restore(inputs['task'],SkillContract(**inputs['contract']),root/'model.npz',root/'session')
except ValueError as error:
    assert 'drift' in str(error), str(error)
else:
    value.close(); raise AssertionError('changed guard source accepted')
"""
        result = subprocess.run(
            [sys.executable, "-c", script, str(source), str(self.root)],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
