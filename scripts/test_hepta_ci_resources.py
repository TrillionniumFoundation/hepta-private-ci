"""Exercise bounded observations alongside actual child processes and Git receipts."""

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import hepta_ci_exec as executor
from scripts import hepta_ci_resources as resources
from scripts.test_hepta_ci_exec import GitExecutionFixture


class ResourceObservationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="hepta-resources-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def command(self, stem, resource_log=None):
        log = self.root / (stem + ".log")
        with contextlib.redirect_stdout(io.StringIO()):
            result = executor.execute_logged(
                [sys.executable, "-c", "import os; os.write(1, b'owned\\x00\\xff\\n')"],
                log,
                timeout_seconds=5,
                resource_log=resource_log,
            )
        return result, log.read_bytes()

    def test_unknown_resources_do_not_change_command_output_or_result(self):
        baseline, expected = self.command("baseline")
        collector = resources.collect_resources
        with patch.object(
            resources,
            "collect_resources",
            side_effect=lambda directory, pid: collector(
                directory, pid, self.root / "missing-proc"
            ),
        ):
            actual, raw = self.command("observed", self.root / "resources.jsonl")
        summary = actual.pop("resource_observations")
        self.assertEqual((actual, raw), (baseline, expected))
        data = (self.root / summary["file"]).read_bytes()
        self.assertEqual(
            (summary["bytes"], summary["sha256"]),
            (len(data), hashlib.sha256(data).hexdigest()),
        )
        rows = [json.loads(line) for line in data.splitlines()]
        self.assertEqual([row["event"] for row in rows], ["sample", "final"])
        for row in rows:
            self.assertEqual(row["cgroup_v2"]["status"], "unknown")
            self.assertEqual(
                set(value["status"] for value in row["proc"].values()), {"unknown"}
            )

    def test_total_byte_bound_records_the_gap_without_truncating_command_output(self):
        baseline, expected = self.command("baseline")
        observer = resources.ResourceObserver
        with patch.object(
            resources,
            "ResourceObserver",
            side_effect=lambda path: observer(path, maximum_bytes=256),
        ):
            actual, raw = self.command("bounded", self.root / "resources.jsonl")
        summary = actual.pop("resource_observations")
        self.assertEqual((actual, raw), (baseline, expected))
        data = (self.root / summary["file"]).read_bytes()
        self.assertLessEqual(len(data), 256)
        self.assertEqual(
            [json.loads(line) for line in data.splitlines()],
            [
                {
                    "event": "observation_limit_reached",
                    "remaining_observations": "unknown",
                }
            ],
        )
        self.assertTrue(summary["limit_reached"])

    def test_observed_silent_child_keeps_the_existing_deadline(self):
        result = executor.execute_logged(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            self.root / "deadline.log",
            timeout_seconds=0.2,
            resource_log=self.root / "resources.jsonl",
        )
        self.assertEqual(
            (
                result["returncode"],
                result["timed_out"],
                result["output_limit_exceeded"],
                result["observed_passed_tests"],
                result["observed_failed_tests"],
            ),
            (-signal.SIGKILL, True, False, 0, 0),
        )
        self.assertEqual((self.root / "deadline.log").read_bytes(), b"")
        self.assertEqual(result["resource_observations"]["status"], "recorded")

    def test_observer_cannot_replace_existing_evidence(self):
        target = self.root / "resources.jsonl"
        target.write_bytes(b"prior evidence\n")
        baseline, expected = self.command("baseline")
        actual, raw = self.command("collision", target)
        summary = actual.pop("resource_observations")
        self.assertEqual((actual, raw), (baseline, expected))
        self.assertEqual(target.read_bytes(), b"prior evidence\n")
        self.assertEqual(
            (summary["status"], summary["sha256"], summary["samples"]),
            ("unknown", None, 0),
        )

    def cgroup_fixture(self, membership):
        proc = self.root / "proc"
        (proc / "self").mkdir(parents=True)
        mount = self.root / "cgroup mount"
        mount.mkdir()
        (proc / "self/cgroup").write_text("0::" + membership + "\n")
        mount_field = str(mount).replace(" ", r"\040")
        (proc / "self/mountinfo").write_text(
            f"40 39 0:28 / {mount_field} rw - cgroup2 cgroup rw\n"
        )
        return proc, mount

    def test_observations_preserve_ancestor_capacity_and_unknown_counters(self):
        proc, mount = self.cgroup_fixture("/job")
        (mount / "job").mkdir()
        for folder, maximum in [(mount, "8192\n"), (mount / "job", "max\n")]:
            (folder / "memory.max").write_text(maximum)
            (folder / "memory.peak").write_text("2048\n")
        observed = resources.cgroup_observations(proc)
        self.assertTrue(observed["visible_ancestors_complete"])
        self.assertEqual(
            [
                (
                    entry["path"],
                    entry["files"]["memory.max"],
                    entry["files"]["memory.peak"],
                )
                for entry in observed["ancestors"]
            ],
            [
                (
                    str(mount / "job"),
                    {"status": "observed", "text": "max\n"},
                    {"status": "observed", "text": "2048\n"},
                ),
                (
                    str(mount),
                    {"status": "observed", "text": "8192\n"},
                    {"status": "observed", "text": "2048\n"},
                ),
            ],
        )
        for entry in observed["ancestors"]:
            self.assertEqual(entry["files"]["memory.events"]["status"], "unknown")

    def test_truncated_ancestry_cannot_claim_the_unobserved_parent_limit(self):
        proc, mount = self.cgroup_fixture("/a/b/c/d/e/f/g/h")
        (mount / "a/b/c/d/e/f/g/h").mkdir(parents=True)
        (mount / "memory.max").write_text("8192\n")
        observed = resources.cgroup_observations(proc)
        self.assertFalse(observed["visible_ancestors_complete"])
        self.assertNotIn(str(mount), [entry["path"] for entry in observed["ancestors"]])


class ResourceReceiptTests(GitExecutionFixture):
    def test_real_success_and_failure_keep_original_exit_and_source_identity(self):
        for code in [0, 7]:
            with self.subTest(code=code):
                output = self.root / f"command-{code}.json"
                result = subprocess.run(
                    [
                        sys.executable,
                        str(Path(executor.__file__).resolve()),
                        "--observe-resources",
                        "--output",
                        str(output),
                        "--",
                        sys.executable,
                        "-c",
                        f"print('owned command'); raise SystemExit({code})",
                    ],
                    cwd=self.repo,
                    capture_output=True,
                    timeout=10,
                    env={
                        **os.environ,
                        "SOURCE_SHA": self.source,
                        "TESTED_SHA": self.source,
                        "BASE_SHA": "0" * 40,
                        "HEPTA_CI_LANE": "source-head",
                    },
                )
                receipt = json.loads(output.read_bytes())
                self.assertEqual(
                    (
                        result.returncode,
                        receipt["command_exit_code"],
                        receipt["exit_code"],
                        receipt["status"],
                    ),
                    (code, code, code, "failed" if code else "passed"),
                )
                self.assertEqual(receipt["before"], receipt["after"])
                self.assertTrue(receipt["resource_observations_requested"])
                resource = receipt["resource_observations"]
                raw = (self.root / resource["file"]).read_bytes()
                self.assertEqual(
                    (resource["bytes"], resource["sha256"]),
                    (len(raw), hashlib.sha256(raw).hexdigest()),
                )
                self.assertTrue(resource["file"].startswith(output.name + "."))
                self.assertEqual(
                    (
                        receipt["observed_passed_tests"],
                        receipt["observed_failed_tests"],
                    ),
                    (0, 0),
                )


if __name__ == "__main__":
    unittest.main()
