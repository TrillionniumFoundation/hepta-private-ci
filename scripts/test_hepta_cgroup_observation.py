"""Boundary controls for read-only cgroup accounting; no hardware emulation claim."""

import unittest
from unittest.mock import patch

from hepta_cells import cgroup_observation as observation


class CgroupObservationTests(unittest.TestCase):
    def setUp(self):
        self.membership = "0::/user.slice/job\n"
        self.mounts = "1 2 0:30 /user.slice /sys/fs/cgroup rw - cgroup2 cgroup rw\n"
        self.files = {
            "/proc/self/cgroup": self.membership,
            "/proc/self/mountinfo": self.mounts,
            "/sys/fs/cgroup/job/memory.current": "4096\n",
            "/sys/fs/cgroup/job/memory.peak": "8192\n",
            "/sys/fs/cgroup/job/memory.stat": "anon 2048\nfile 1024\n",
            "/sys/fs/cgroup/job/memory.events": "oom 0\noom_kill 0\n",
            "/sys/fs/cgroup/job/cpu.stat": "usage_usec 12\nuser_usec 8\n",
            "/sys/fs/cgroup/job/pids.current": "2\n",
            "/sys/fs/cgroup/job/pids.max": "max\n",
            "/sys/fs/cgroup/job/cgroup.events": "populated 1\nfrozen 0\n",
        }

    def read(self, path):
        value = self.files[str(path)]
        if isinstance(value, Exception):
            raise value
        return value

    def observe(self, reader=None):
        with (
            patch.object(observation.sys, "platform", "linux"),
            patch.object(observation, "_read_text", side_effect=reader or self.read),
            patch.object(
                observation,
                "_directory_identity",
                return_value={"device": 30, "inode": 9},
            ),
        ):
            return observation.observe_current_cgroup()

    def test_maps_subtree_mount_and_keeps_accounting_scope(self):
        result = self.observe()
        self.assertEqual(result["status"], "OBSERVED")
        self.assertEqual(result["identity"]["directory"], "/sys/fs/cgroup/job")
        self.assertEqual(result["metrics"]["memory.peak"]["value"], 8192)
        self.assertEqual(
            result["metrics"]["memory.stat"]["value"], {"anon": 2048, "file": 1024}
        )
        self.assertEqual(result["metrics"]["pids.max"]["value"], "max")
        self.assertFalse(result["campaign_coverage_verified"])
        self.assertIsNone(result["campaign_process_tree_peak_rss_bytes"])
        self.assertIsNone(result["physical_energy_joules"])

    def test_permission_failure_is_unknown_not_zero(self):
        self.files["/sys/fs/cgroup/job/memory.peak"] = PermissionError("denied")
        result = self.observe()
        self.assertEqual(result["status"], "PARTIAL")
        self.assertIsNone(result["metrics"]["memory.peak"]["value"])
        self.assertEqual(
            result["metrics"]["memory.peak"]["error_type"], "PermissionError"
        )

    def test_malformed_counter_keeps_raw_without_admitting_value(self):
        self.files["/sys/fs/cgroup/job/cpu.stat"] = "usage_usec 1\nusage_usec 2\n"
        result = self.observe()
        self.assertEqual(result["status"], "PARTIAL")
        self.assertIsNone(result["metrics"]["cpu.stat"]["value"])
        self.assertEqual(
            result["metrics"]["cpu.stat"]["raw"], "usage_usec 1\nusage_usec 2\n"
        )

    def test_membership_change_invalidates_collected_values(self):
        count = 0

        def moving(path):
            nonlocal count
            if str(path) == "/proc/self/cgroup":
                count += 1
                return self.membership if count == 1 else "0::/user.slice/other\n"
            return self.read(path)

        result = self.observe(moving)
        self.assertEqual(result["status"], "UNSTABLE_IDENTITY")
        self.assertFalse(result["identity_stable"])
        self.assertTrue(all(row["value"] is None for row in result["metrics"].values()))
        self.assertEqual(result["metrics"]["memory.peak"]["raw"], "8192\n")

    def test_ambiguous_or_traversing_membership_is_unavailable(self):
        for value in ("0::/user.slice/job\n0::/other\n", "0::/user.slice/../other\n"):
            with self.subTest(value=value):
                self.files["/proc/self/cgroup"] = value
                self.assertEqual(self.observe()["status"], "UNAVAILABLE")

    def test_missing_mount_never_falls_back_to_host_cgroup(self):
        self.files["/proc/self/mountinfo"] = "1 2 0:30 / /sys rw - sysfs sysfs rw\n"
        result = self.observe()
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertIsNone(result["identity"])


if __name__ == "__main__":
    unittest.main()
