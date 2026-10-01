#!/usr/bin/env python3
"""Real Linux process and summary-harness regressions, not model measurements."""

import copy
import csv
from decimal import Decimal
import io
import json
import math
import os
from pathlib import Path
import re
import signal
import statistics
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

HELPER = Path(__file__).with_name("hepta-intelligence-measure-process.py")
WORKFLOW = (
    HELPER.parent.parent / ".github/workflows/hepta-intelligence-qualification-host.yml"
)
HEADER = [
    "sample",
    "elapsed_seconds",
    "user_cpu_seconds",
    "system_cpu_seconds",
    "max_rss_kib",
]


def process_identity(pid: int) -> dict | None:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    except FileNotFoundError:
        return None
    return {
        "pid": pid,
        "state": fields[0],
        "pgid": int(fields[2]),
        "session": int(fields[3]),
        "start": fields[19],
    }


class MeasurementFixture:
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory(prefix="intelligence-process-tests-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.log = self.root / "subject.log"
        self.timing = self.root / "subject.time"
        self.metadata = self.root / "subject-measurement.json"

    def measure(
        self, code: str, *, sample: int = 1, timeout: float = 2
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                str(HELPER),
                "--sample",
                str(sample),
                "--timeout",
                str(timeout),
                "--output",
                str(self.log),
                "--timing",
                str(self.timing),
                "--metadata",
                str(self.metadata),
                "--",
                sys.executable,
                "-c",
                code,
            ],
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
        )

    def successful_measurement(
        self, result: subprocess.CompletedProcess
    ) -> tuple[list[str], dict]:
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = list(csv.reader(io.StringIO(self.timing.read_text())))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(len(row), 5)
        for value in row[1:4]:
            self.assertRegex(value, r"^\d+\.\d{9}$")
            self.assertTrue(math.isfinite(float(value)))
        metadata = json.loads(self.metadata.read_text())
        self.assertGreater(Decimal(row[1]), 0)
        self.assertGreater(int(row[4]), 0)
        self.assertIs(type(metadata["elapsedNanoseconds"]), int)
        self.assertGreater(metadata["elapsedNanoseconds"], 0)
        self.assertLessEqual(
            abs(Decimal(row[1]) * 1_000_000_000 - metadata["elapsedNanoseconds"]),
            1,
        )
        return row, metadata


@unittest.skipUnless(sys.platform == "linux", "Linux resource and /proc accounting")
class ProcessMeasurementTests(MeasurementFixture, unittest.TestCase):
    def test_short_process_has_positive_nanosecond_wall_and_both_log_streams(
        self,
    ) -> None:
        started = time.perf_counter_ns()
        result = self.measure(
            "import os; os.write(1, b'stdout-marker\\n'); os.write(2, b'stderr-marker\\n')",
            sample=7,
        )
        outer_elapsed = time.perf_counter_ns() - started
        row, metadata = self.successful_measurement(result)
        self.assertEqual(row[0], "7")
        self.assertEqual(metadata["sample"], 7)
        self.assertLessEqual(metadata["elapsedNanoseconds"], outer_elapsed)
        self.assertEqual(
            set(self.log.read_text().splitlines()), {"stdout-marker", "stderr-marker"}
        )
        method = metadata["timingMethod"]
        self.assertGreater(method["clockResolutionSeconds"], 0)
        self.assertLessEqual(method["clockResolutionSeconds"], float(row[1]))

    def test_busy_child_cpu_and_peak_rss_are_observed(self) -> None:
        result = self.measure(
            "import json, resource, time\n"
            "memory = bytearray(32 * 1024 * 1024)\n"
            "deadline = time.process_time() + 0.12\n"
            "value = 1\n"
            "while time.process_time() < deadline:\n"
            "    value = (value * 17 + 3) % 1000003\n"
            "usage = resource.getrusage(resource.RUSAGE_SELF)\n"
            "print(json.dumps({'cpu': usage.ru_utime + usage.ru_stime, 'rss': usage.ru_maxrss}))\n"
        )
        row, _ = self.successful_measurement(result)
        child = json.loads(self.log.read_text())
        cpu = float(row[2]) + float(row[3])
        self.assertGreater(cpu, 0.10)
        self.assertGreaterEqual(cpu + 0.002, child["cpu"])
        self.assertGreaterEqual(int(row[4]), child["rss"])
        self.assertGreater(int(row[4]), 32 * 1024)

    def test_nonzero_exit_removes_previous_success_evidence(self) -> None:
        self.timing.write_text("stale-success\n")
        self.metadata.write_text('{"stale": true}\n')
        result = self.measure("import sys; print('failed-child'); sys.exit(7)")
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertIn("failed-child", self.log.read_text())
        self.assertFalse(self.timing.exists())
        self.assertFalse(self.metadata.exists())

    def test_timeout_kills_owned_group_and_reaps_direct_child(self) -> None:
        self.assert_stopped_process_group(
            "time.sleep(60)", timeout=0.8, expected_exit=124
        )

    def test_nonzero_exit_kills_owned_descendant_and_reaps_direct_child(self) -> None:
        self.assert_stopped_process_group(
            "raise SystemExit(7)", timeout=2, expected_exit=7
        )

    def assert_stopped_process_group(
        self, parent_tail: str, *, timeout: float, expected_exit: int
    ) -> None:
        pidfile = self.root / "owned-pids.json"

        def cleanup_owned_processes() -> None:
            if not pidfile.exists():
                return
            owned = json.loads(pidfile.read_text())
            group = owned["child"]["procPid"]
            for record in owned.values():
                current = process_identity(record["procPid"])
                if (
                    current is not None
                    and current["start"] == record["start"]
                    and current["pgid"] == group
                    and current["session"] == group
                    and current["state"] != "Z"
                ):
                    try:
                        os.kill(record["pid"], signal.SIGKILL)
                    except ProcessLookupError:
                        pass

        self.addCleanup(cleanup_owned_processes)
        # /proc can be mounted from an outer PID namespace. Each process reports
        # its own mounted identity and its syscall PID; never infer one from the other.
        identity_code = textwrap.dedent(
            """\
            import json, os, pathlib, signal, subprocess, sys, time
            def identity():
                stat = pathlib.Path("/proc/self/stat").read_text()
                fields = stat.rsplit(")", 1)[1].split()
                return {"pid": os.getpid(), "procPid": int(stat.split()[0]), "pgid": os.getpgrp(), "session": os.getsid(0), "procPgid": int(fields[2]), "procSession": int(fields[3]), "start": fields[19]}
            """
        )
        descendant_code = identity_code + (
            "print(json.dumps(identity()), flush=True)\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "time.sleep(60)\n"
        )
        code = identity_code + textwrap.dedent(
            f"""\
            descendant = subprocess.Popen([sys.executable, "-c", {descendant_code!r}], stdout=subprocess.PIPE, text=True)
            descendant_identity = json.loads(descendant.stdout.readline())
            target = pathlib.Path({str(pidfile)!r})
            temporary = target.with_suffix(".pending")
            temporary.write_text(json.dumps({{"child": identity(), "descendant": descendant_identity}}))
            temporary.replace(target)
            {parent_tail}
            """
        )
        self.timing.write_text("stale-success\n")
        self.metadata.write_text("{}\n")
        started = time.monotonic()
        result = self.measure(code, timeout=timeout)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(
            result.returncode, expected_exit, result.stderr + self.log.read_text()
        )
        self.assertTrue(pidfile.exists(), self.log.read_text())
        owned = json.loads(pidfile.read_text())
        group = owned["child"]["pid"]
        self.assertNotEqual(group, os.getpid())
        self.assertEqual({row["pgid"] for row in owned.values()}, {group})
        self.assertEqual({row["session"] for row in owned.values()}, {group})
        mounted_group = owned["child"]["procPid"]
        self.assertEqual({row["procPgid"] for row in owned.values()}, {mounted_group})
        self.assertEqual(
            {row["procSession"] for row in owned.values()}, {mounted_group}
        )
        self.assertIsNone(
            process_identity(mounted_group), "direct child was not reaped"
        )
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            descendant = process_identity(owned["descendant"]["procPid"])
            if descendant is None or descendant["state"] == "Z":
                break
            time.sleep(0.01)
        self.assertTrue(descendant is None or descendant["state"] == "Z", descendant)
        self.assertFalse(self.timing.exists())
        self.assertFalse(self.metadata.exists())

    def test_invalid_parameters_fail_before_subject_starts(self) -> None:
        marker = self.root / "started"
        command = [
            sys.executable,
            "-c",
            f"from pathlib import Path; Path({str(marker)!r}).touch()",
        ]
        base = [
            sys.executable,
            str(HELPER),
            "--sample=1",
            "--timeout=2",
            "--output=" + str(self.log),
            "--timing=" + str(self.timing),
            "--metadata=" + str(self.metadata),
        ]
        variants = (
            [["--sample=" + value] for value in ("0", "-1", "1.5", "true")]
            + [
                ["--timeout=" + value]
                for value in ("0", "-1", "nan", "inf", "-inf", "bad")
            ]
            + [["--metadata=" + str(self.timing)]]
        )
        for extra in variants:
            with self.subTest(arguments=extra):
                result = subprocess.run(
                    base + extra + ["--"] + command,
                    capture_output=True,
                    timeout=5,
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(marker.exists())
                self.assertFalse(self.log.exists())
                self.assertFalse(self.timing.exists())
                self.assertFalse(self.metadata.exists())
        result = subprocess.run(
            base + ["--"], capture_output=True, timeout=5, check=False
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(marker.exists())


@unittest.skipUnless(sys.platform == "linux", "Linux qualification measurements")
class WorkflowSummaryTests(MeasurementFixture, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        matches = re.findall(
            r'(?ms)^([ ]+)python3 - "\$root" "\$SOURCE_SHA" <<\'PY\'\n(.*?)^\1PY$',
            WORKFLOW.read_text(),
        )
        self.assertEqual(
            len(matches), 1, "expected the workflow's actual metrics summary"
        )
        self.summary = textwrap.dedent(matches[0][1])
        self.rows = []
        self.measurements = []
        for sample in range(1, 10):
            self.log = self.root / f"sample-{sample}.log"
            self.timing = self.root / f"sample-{sample}.time"
            self.metadata = self.root / f"sample-{sample}-measurement.json"
            row, metadata = self.successful_measurement(
                self.measure("sum(range(10000))", sample=sample)
            )
            self.rows.append(dict(zip(HEADER, row)))
            self.measurements.append(metadata)
        # These synthetic profile inputs exercise only the aggregation harness.
        self.signature = {
            "schema": "hepta.intelligence-control.signature-profile.v1",
            "samplesNanos": [1000] * 2000,
        }
        self.hard_kill = {
            "schema": "hepta.intelligence-control.hard-kill-profile.v1",
            "samplesNanos": [2_000_000] * 9,
        }
        self.write_inputs(self.rows, self.measurements, self.signature, self.hard_kill)

    def write_inputs(
        self,
        rows: list[dict],
        measurements: list[dict],
        signature: dict,
        hard_kill: dict,
    ) -> None:
        (self.root / "metrics.json").unlink(missing_ok=True)
        with (self.root / "samples.csv").open("w", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=HEADER)
            writer.writeheader()
            writer.writerows(rows)
        for index, metadata in enumerate(measurements, 1):
            (self.root / f"sample-{index}-measurement.json").write_text(
                json.dumps(metadata)
            )
        for name, value in (("signature", signature), ("hard-kill", hard_kill)):
            (self.root / f"{name}-profile.json").write_text(json.dumps(value))

    def summarize(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-c", self.summary, str(self.root), "f" * 40],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

    def test_real_samples_emit_matching_method_and_cpu_aggregation(self) -> None:
        result = self.summarize()
        self.assertEqual(result.returncode, 0, result.stderr)
        metrics = json.loads((self.root / "metrics.json").read_text())
        self.assertEqual(metrics["sampleCount"], 9)
        self.assertEqual(metrics["sourceCommit"], "f" * 40)
        self.assertEqual(metrics["timingMethod"], self.measurements[0]["timingMethod"])
        expected_cpu = statistics.fmean(
            100
            * (float(row["user_cpu_seconds"]) + float(row["system_cpu_seconds"]))
            / float(row["elapsed_seconds"])
            for row in self.rows
        )
        self.assertAlmostEqual(metrics["processCpuPercent"]["mean"], expected_cpu)
        self.assertGreater(metrics["elapsedSeconds"]["p50"], 0)
        self.assertEqual(metrics["strictSignatureVerificationMicros"]["p50"], 1)
        self.assertEqual(metrics["hardKillSpawnToExit70Millis"]["p50"], 2)
        self.assertFalse(metrics["claimBoundary"]["productionTargetHostAcceptance"])
        self.assertFalse(metrics["claimBoundary"]["activationPromotionOrRelease"])

    def test_invalid_inputs_emit_no_fresh_metrics(self) -> None:
        variants = (
            [
                ("row", "elapsed_seconds", value)
                for value in ("0", "-1", "nan", "inf", "999")
            ]
            + [("row", "user_cpu_seconds", value) for value in ("-1", "nan")]
            + [
                ("row", "system_cpu_seconds", "inf"),
                ("row", "max_rss_kib", "0"),
                ("metadata", "elapsedNanoseconds", float("nan")),
                ("metadata", "elapsedNanoseconds", True),
                ("metadata", "sample", True),
                ("metadata", "sample", 99),
                ("rows", "duplicate", None),
                ("rows", "reordered", None),
                ("rows", "missing", None),
                ("signature", "samplesNanos", [1000] * 1999),
                ("signature", "samplesNanos", [float("nan")] + [1000] * 1999),
                ("hard-kill", "samplesNanos", [0] + [2_000_000] * 8),
                ("hard-kill", "samplesNanos", [True] + [2_000_000] * 8),
            ]
        )
        for target, key, value in variants:
            with self.subTest(target=target, key=key, value=str(value)[:50]):
                rows, metadata = (
                    copy.deepcopy(self.rows),
                    copy.deepcopy(self.measurements),
                )
                signature, hard_kill = (
                    copy.deepcopy(self.signature),
                    copy.deepcopy(self.hard_kill),
                )
                if target == "row":
                    rows[0][key] = value
                elif target == "metadata":
                    metadata[0][key] = value
                elif target == "rows":
                    if key == "duplicate":
                        rows[1] = rows[0].copy()
                    elif key == "reordered":
                        rows[0], rows[1] = rows[1], rows[0]
                    else:
                        rows.pop()
                else:
                    (signature if target == "signature" else hard_kill)[key] = value
                self.write_inputs(rows, metadata, signature, hard_kill)
                result = self.summarize()
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertFalse((self.root / "metrics.json").exists())


if __name__ == "__main__":
    unittest.main()
