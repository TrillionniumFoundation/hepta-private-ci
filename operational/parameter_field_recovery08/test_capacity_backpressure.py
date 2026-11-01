"""Real file/lock/constructor boundaries for the explicit execution08 capacity."""

from copy import deepcopy
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from . import capacity_amendment as amendment
from . import capacity_backpressure as current
from . import common as c

old = current.BACKPRESSURE


def memory(allowed=True):
    used = 0 if allowed else 8 * old.GiB
    return {
        "current": used,
        "limit": 8 * old.GiB,
        "effective_current": used,
        "inactive_file": 0,
        "file_dirty": 0,
        "file_writeback": 0,
        "clean_inactive_file": 0,
        "oom": 0,
        "oom_kill": 0,
    }


class CapacityBackpressureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix="execution08-capacity-fixture-"
        )
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.raw = self.base / "raw"
        self.raw.mkdir()
        pin = c.descriptor(c.OWN / "OPS_EXECUTION08.json")
        self.actual_registration = amendment.load_registration(
            pin["path"], pin["sha256"]
        )
        self.registration = deepcopy(self.actual_registration)
        # Only fixture roots are projected into temporary storage. There is no
        # production relocation option. The actual committed profile is checked
        # above; the constructor and all transaction/file/lock methods are real.
        self.registration["raw_root"] = str(self.raw)
        self.registration["content_addressed_store"] = str(
            self.raw.with_name("raw_cas")
        )
        pins = {
            name: c.descriptor(c.SOURCE / name)["sha256"]
            for name in old.REQUIRED_SOURCES
        }
        pins[current.RELATIVE] = c.descriptor(c.SOURCE / current.RELATIVE)["sha256"]
        self.config = {"descriptors": {"amendment": pin}, "source_files": pins}
        self.sequence = 0

    def policy(self, reader=None):
        self.sequence += 1
        return old.BackpressurePolicy(
            root=self.raw,
            journal_directory=self.base / ("events-" + str(self.sequence)),
            source_root=c.SOURCE,
            expected_sources=self.config["source_files"],
            deadline_monotonic=time.monotonic() + 10,
            oom_baseline={"oom": 0, "oom_kill": 0},
            health_check=lambda: None,
            max_wait_seconds=1,
            poll_seconds=0.001,
            test_profile_reader=reader or memory,
        )

    def admitted(self):
        return patch.object(
            amendment, "load_registration", return_value=self.registration
        )

    def test_old_real_constructor_rejects_six_gib_new_exact_constructor_accepts(self):
        policy = self.policy()
        self.assertEqual(
            self.actual_registration["proposed_resource_contract"][
                "global_raw_logical_bytes"
            ],
            6 * old.GiB,
        )
        with self.assertRaisesRegex(ValueError, "Registered resource limits changed"):
            current.ORIGINAL_PRESSURE_BUDGET(self.raw, self.registration, policy)
        with (
            self.admitted(),
            current.installed(
                self.config, policy, allow_test_policy=True
            ) as installation,
        ):
            storage = installation["budget_type"](self.raw, self.registration)
            self.assertEqual(
                (storage.cap, storage.reserve, storage.c_cap, storage.margin),
                (6 * old.GiB, 256 * old.MiB, 350 * old.MiB, old.GiB),
            )
            with storage.writer_lock():
                self.assertEqual(storage._local.depth, 1)
            self.assertTrue(storage.cas_root.is_dir())
            with old.IO.guarded_writes(storage):
                with (self.raw / "actual.bin").open("xb") as stream:
                    stream.write(b"synthetic literal payload\n")
            self.assertEqual(
                (self.raw / "actual.bin").read_bytes(), b"synthetic literal payload\n"
            )
        self.assertIs(old.BackpressureBudget, current.ORIGINAL_PRESSURE_BUDGET)
        self.assertIs(old.RESOURCE.StorageBudget, old.ORIGINAL_BUDGET)

    def test_only_exact_registered_identity_is_admitted_and_source_pin_is_required(
        self,
    ):
        with self.admitted():
            budget = current.registered_budget_type(self.config)
            for section, key, value in (
                ("proposed_resource_contract", "global_raw_logical_bytes", 7 * old.GiB),
                ("proposed_resource_contract", "minimum_private_allocatable_bytes", 0),
                (
                    "proposed_resource_contract",
                    "C_training_evidence_bytes",
                    351 * old.MiB,
                ),
                ("concurrency", "memory_margin_bytes", 0),
                ("concurrency", "max_workers", 3),
                ("concurrency", "worker_reservation_bytes", 0),
            ):
                with self.subTest(section=section, key=key):
                    changed = deepcopy(self.registration)
                    changed[section][key] = value
                    with self.assertRaisesRegex(ValueError, "exact committed"):
                        budget(self.raw, changed, self.policy())
            changed = deepcopy(self.registration)
            changed["_sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "exact committed"):
                budget(self.raw, changed, self.policy())
            with self.assertRaisesRegex(ValueError, "root differs"):
                budget(self.base / "another", self.registration, self.policy())
            bad = deepcopy(self.config)
            bad["source_files"][current.RELATIVE] = "0" * 64
            with self.assertRaisesRegex(ValueError, "constructor source"):
                current.registered_budget_type(bad)

    def test_six_gib_logical_limit_preserves_physical_reserve_and_c_training_limit(
        self,
    ):
        policy = self.policy()
        with (
            self.admitted(),
            current.installed(
                self.config, policy, allow_test_policy=True
            ) as installation,
        ):
            storage = installation["budget_type"](self.raw, self.registration)
            # Sparse fixture bytes establish a logical population above the old
            # cap without allocating multi-gigabyte physical test payloads.
            with old.RAW_OPEN(self.raw / "logical-fixture", "xb") as stream:
                stream.truncate(5 * old.GiB // 2)
            inventory = storage.check(check_memory=False)
            self.assertGreater(inventory["logical_bytes"], 2 * old.GiB)
            with self.assertRaisesRegex(RuntimeError, "logical raw cap exhausted"):
                storage.check(additional=6 * old.GiB, check_memory=False)
            stage = self.raw / "stage_C"
            stage.mkdir()
            with old.RAW_OPEN(stage / "training-fixture", "xb") as stream:
                stream.truncate(350 * old.MiB)
            with self.assertRaisesRegex(RuntimeError, "C training evidence cap"):
                storage.check(additional=1, c_training=True, check_memory=False)
            space = SimpleNamespace(f_frsize=4096, f_bavail=0, f_favail=10000)
            with (
                patch.object(old.os, "statvfs", return_value=space),
                self.assertRaisesRegex(RuntimeError, "physical reserve"),
            ):
                storage.check(check_memory=False)

    def test_original_wait_is_precommit_and_failed_physical_write_is_never_retried(
        self,
    ):
        checks = 0

        def reader():
            nonlocal checks
            checks += 1
            return memory(checks >= 4)

        policy = self.policy(reader)
        with (
            self.admitted(),
            current.installed(
                self.config, policy, allow_test_policy=True
            ) as installation,
        ):
            storage = installation["budget_type"](self.raw, self.registration)
            calls = []
            storage.atomic(
                lambda: ({"additional": 1}, "stable"),
                lambda _: calls.append("committed"),
                context={"fixture": True},
            )
            self.assertEqual(calls, ["committed"])
            self.assertEqual(policy.wait_count, 1)

            def failed_write(_):
                calls.append("failed physical attempt")
                raise OSError("synthetic physical failure")

            with self.assertRaisesRegex(OSError, "synthetic physical failure"):
                storage.atomic(
                    lambda: ({"additional": 1}, "stable"),
                    failed_write,
                    context={"fixture": True},
                )
            self.assertEqual(calls, ["committed", "failed physical attempt"])

    def test_aliases_restore_after_failure_and_test_policy_cannot_enter_production(
        self,
    ):
        policy = self.policy()
        with (
            self.admitted(),
            self.assertRaisesRegex(ValueError, "Synthetic capacity policy"),
        ):
            with current.installed(self.config, policy):
                pass
        self.assertIs(old.BackpressureBudget, current.ORIGINAL_PRESSURE_BUDGET)
        with self.admitted(), self.assertRaisesRegex(RuntimeError, "synthetic stop"):
            with current.installed(self.config, policy, allow_test_policy=True):
                with self.assertRaisesRegex(ValueError, "original alias"):
                    current.registered_budget_type(self.config)
                raise RuntimeError("synthetic stop")
        self.assertIs(old.BackpressureBudget, current.ORIGINAL_PRESSURE_BUDGET)
        self.assertIs(old.RESOURCE.StorageBudget, old.ORIGINAL_BUDGET)
        self.assertIs(old.IO.CheckedFile, old.ORIGINAL_CHECKED_FILE)


if __name__ == "__main__":
    unittest.main()
