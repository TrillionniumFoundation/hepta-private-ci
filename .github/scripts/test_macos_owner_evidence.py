"""Synthetic evidence/watchdog regressions, never native-test evidence."""

import json
import math
import os
import shutil
import subprocess
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import macos_owner_evidence as evidence


def retain_watchdog_receipts(root, destination):
    """Preserve bounded-command evidence before unittest deletes owned temp dirs."""
    for receipt in list(root.rglob("result.json")):
        relative = receipt.parent.relative_to(root)
        target = destination / relative
        target.mkdir(parents=True, exist_ok=True)
        for name in (
            "result.json",
            "command.json",
            "stdout.log",
            "stderr.log",
            "probe-state.stdout.log",
            "probe-state.stderr.log",
        ):
            source = receipt.parent / name
            if source.is_file() and not source.is_symlink():
                shutil.copyfile(source, target / name)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.retain_watchdog_receipts)
        self.env = patch.dict(os.environ, {"CANDIDATE_SHA": "expected"})
        self.env.start()
        self.addCleanup(self.env.stop)
        start = float(int(time.monotonic()))
        self.budget = {
            "seconds": 4500,
            "clock": "monotonic",
            "start_monotonic": start,
            "deadline_monotonic": start + 4500,
            "head": "expected",
            "python": evidence.python_identity(),
        }
        (self.root / "budget.json").write_text(json.dumps(self.budget))

    def retain_watchdog_receipts(self):
        destination = os.environ.get("EVIDENCE")
        if not destination:
            return
        retain_watchdog_receipts(
            self.root, Path(destination) / "validator-cases" / self._testMethodName
        )

    def report(self, phase="supervisor-owning"):
        root = ET.Element(
            "testsuites",
            name=evidence.PROFILE,
            tests=str(len(evidence.expected(phase))),
            failures="0",
            errors="0",
        )
        for identity in sorted({x[0] for x in evidence.expected(phase)}):
            cases = [x for x in sorted(evidence.expected(phase)) if x[0] == identity]
            suite = ET.SubElement(
                root,
                "testsuite",
                name=identity,
                tests=str(len(cases)),
                failures="0",
                errors="0",
                skipped="0",
            )
            for classname, name in cases:
                ET.SubElement(
                    suite,
                    "testcase",
                    classname=classname,
                    name=name,
                    timestamp="2026-10-24T00:00:00Z",
                )
        return root

    def check_report(self, root, phase="supervisor-owning"):
        path = self.root / "junit.xml"
        ET.ElementTree(root).write(path)
        return evidence.validate_report(path, phase)

    def test_exact_all_phases(self):
        for phase in evidence.PHASES:
            self.assertEqual(
                len(self.check_report(self.report(phase), phase)),
                len(evidence.expected(phase)),
            )
        self.assertEqual(sum(len(evidence.expected(p)) for p in evidence.PHASES), 278)

    def test_bad_report_variants(self):
        for tag in [
            "failure",
            "error",
            "skipped",
            "rerunFailure",
            "flakyFailure",
            "unknown",
        ]:
            with self.subTest(tag=tag):
                root = self.report()
                ET.SubElement(root[0][0], tag)
                with self.assertRaises(ValueError):
                    self.check_report(root)
        for mutation in [
            "missing",
            "duplicate",
            "wrong-name",
            "wrong-class",
            "no-time",
            "bad-count",
            "wrong-profile",
            "extra-suite",
        ]:
            with self.subTest(mutation=mutation):
                root = self.report()
                if mutation == "missing":
                    root[0].remove(root[0][0])
                elif mutation == "duplicate":
                    root[0].append(root[0][0])
                elif mutation == "wrong-name":
                    root[0][0].set("name", "fake")
                elif mutation == "wrong-class":
                    root[0][0].set("classname", "fake")
                elif mutation == "no-time":
                    root[0][0].attrib.pop("timestamp")
                elif mutation == "bad-count":
                    root.set("failures", "1")
                elif mutation == "wrong-profile":
                    root.set("name", "local")
                else:
                    ET.SubElement(
                        root,
                        "testsuite",
                        name="extra",
                        tests="0",
                        failures="0",
                        errors="0",
                    )
                with self.assertRaises(ValueError):
                    self.check_report(root)

    def listing(self):
        return {
            "rust-suites": {
                "codex-hepta-supervisor": {
                    "binary-id": "codex-hepta-supervisor",
                    "status": "listed",
                    "testcases": {
                        name: {"ignored": False, "filter-match": {"status": "matches"}}
                        for _, name in evidence.expected("supervisor-owning")
                    },
                }
            }
        }

    def test_list_exact_and_filtered_not_passed(self):
        listing = self.listing()
        listing["rust-suites"]["codex-hepta-supervisor"]["testcases"]["unselected"] = {
            "ignored": True,
            "filter-match": {"status": "mismatch"},
        }
        path = self.root / "list.json"
        path.write_text(json.dumps(listing))
        self.assertEqual(len(evidence.validate_list(path, "supervisor-owning")), 4)

    def test_list_missing_ignored_extra_mismatch(self):
        for mutation in ["missing", "ignored", "extra", "mismatch", "binary"]:
            listing = self.listing()
            suite = listing["rust-suites"]["codex-hepta-supervisor"]
            name = next(iter(suite["testcases"]))
            if mutation == "missing":
                suite["testcases"].pop(name)
            elif mutation == "ignored":
                suite["testcases"][name]["ignored"] = True
            elif mutation == "extra":
                suite["testcases"]["fake"] = suite["testcases"][name]
            elif mutation == "mismatch":
                suite["testcases"][name]["filter-match"]["status"] = "mismatch"
            else:
                suite["binary-id"] = "wrong"
            path = self.root / "list.json"
            path.write_text(json.dumps(listing))
            with self.assertRaises(ValueError):
                evidence.validate_list(path, "supervisor-owning")

    def test_first_eperm_diagnostic_does_not_retry_signal_or_pass(self):
        child = Mock(pid=4242)
        child.wait.return_value = 0
        child.poll.return_value = 0
        with (
            patch.object(evidence.subprocess, "Popen", return_value=child),
            patch.object(
                evidence.os,
                "killpg",
                side_effect=[None, PermissionError(1, "injected EPERM")],
            ) as signals,
            patch.object(
                evidence,
                "snapshot_owned_group",
                return_value={"classification": "unverified", "state": "Z"},
            ) as snapshot,
        ):
            status = evidence.bounded(
                ["fake-native-command"],
                self.root / "eperm",
                time.monotonic() + 3,
                self.root,
            )
        self.assertEqual(status, 125)
        self.assertEqual(
            [call.args for call in signals.call_args_list],
            [(4242, evidence.signal.SIGTERM), (4242, 0)],
        )
        snapshot.assert_called_once_with(4242, self.root / "eperm")
        receipt = json.loads((self.root / "eperm/result.json").read_text())
        self.assertEqual(receipt["error_type"], "PermissionError")
        self.assertIn("injected EPERM", receipt["traceback"])

    def test_snapshot_failure_preserves_original_eperm(self):
        child = Mock(pid=4242)
        child.wait.return_value = 0
        child.poll.return_value = 0
        with (
            patch.object(evidence.subprocess, "Popen", return_value=child),
            patch.object(
                evidence.os,
                "killpg",
                side_effect=[None, PermissionError(1, "original denial")],
            ) as signals,
            patch.object(
                evidence,
                "snapshot_owned_group",
                side_effect=OSError("snapshot unavailable"),
            ),
        ):
            status = evidence.bounded(
                ["fake-native-command"],
                self.root / "gap",
                time.monotonic() + 3,
                self.root,
            )
        self.assertEqual(status, 125)
        self.assertEqual(signals.call_count, 2)
        receipt = json.loads((self.root / "gap/result.json").read_text())
        self.assertEqual(receipt["error_type"], "PermissionError")
        self.assertIn("original denial", receipt["error"])
        self.assertEqual(
            receipt["owned_group_snapshot"]["classification"], "unverified"
        )

    def test_exact_group_snapshot_raw_output_and_bounds(self):
        real_popen = subprocess.Popen
        for name, code, failure in [
            (
                "normal",
                "print('4243 1 4242 4242 501 Z Sun Oct 25 00:00:00 2026')",
                False,
            ),
            ("empty", "pass", False),
            ("large", "import sys;sys.stdout.write('x'*20000)", True),
            ("timeout", "import time;time.sleep(20)", True),
            (
                "failed",
                "import sys;print('unavailable',file=sys.stderr);sys.exit(3)",
                True,
            ),
        ]:
            directory = self.root / name
            directory.mkdir()
            seen = []

            def fake_ps(command, **kwargs):
                seen.append(command)
                return real_popen([sys.executable, "-c", code], **kwargs)

            with (
                patch.object(evidence.platform, "system", return_value="Darwin"),
                patch.object(evidence.subprocess, "Popen", side_effect=fake_ps),
            ):
                receipt = evidence.snapshot_owned_group(4242, directory)
            self.assertEqual(
                seen,
                [
                    [
                        "/bin/ps",
                        "-g",
                        "4242",
                        "-o",
                        "pid=,ppid=,pgid=,sess=,uid=,state=,lstart=",
                    ]
                ],
            )
            self.assertEqual(receipt["classification"], "unverified")
            self.assertEqual("unavailable" in receipt, failure)
            self.assertLessEqual(
                sum(
                    (directory / f"probe-state.{stream}.log").stat().st_size
                    for stream in ["stdout", "stderr"]
                ),
                16384,
            )
            self.assertLess(receipt["elapsed_seconds"], 4)

    def test_failed_command_receipts_survive_temporary_cleanup(self):
        # Reproduce the old loss and establish preservation without executing a child.
        with tempfile.TemporaryDirectory() as old:
            old_root = Path(old)
            with patch.object(
                evidence.subprocess,
                "Popen",
                side_effect=OSError("diagnostic injected error"),
            ):
                self.assertEqual(
                    evidence.bounded(
                        ["fake-native-command"],
                        old_root / "failed",
                        time.monotonic() + 3,
                        old_root,
                    ),
                    125,
                )
            old_receipt = old_root / "failed/result.json"
            self.assertTrue(old_receipt.is_file())
        self.assertFalse(old_receipt.exists())
        with tempfile.TemporaryDirectory() as new:
            new_root = Path(new)
            with patch.object(
                evidence.subprocess,
                "Popen",
                side_effect=OSError("diagnostic injected error"),
            ):
                self.assertEqual(
                    evidence.bounded(
                        ["fake-native-command"],
                        new_root / "failed",
                        time.monotonic() + 3,
                        new_root,
                    ),
                    125,
                )
            retain_watchdog_receipts(new_root, self.root / "retained")
        record = json.loads((self.root / "retained/failed/result.json").read_text())
        self.assertEqual(record["exit"], 125)
        self.assertEqual(record["error_type"], "OSError")
        self.assertIn("diagnostic injected error", record["traceback"])
        for name in ("command.json", "stdout.log", "stderr.log"):
            self.assertTrue((self.root / "retained/failed" / name).is_file())

    def test_post_log_seal_captures_late_traceback(self):
        log = self.root / "verification.log"
        log.write_text("verification started\n")
        evidence.seal(self.root)
        premature = json.loads((self.root / "artifact-hashes.json").read_text())[
            "verification.log"
        ]
        with log.open("a") as stream:
            stream.write("Traceback: diagnostic final failure\n")
        self.assertNotEqual(premature, evidence.digest(log))
        evidence.seal(self.root)
        final = json.loads((self.root / "artifact-hashes.json").read_text())
        self.assertEqual(final["verification.log"], evidence.digest(log))
        self.assertNotIn("artifact-hashes.json", final)

    def test_unsupported_python_fails_closed(self):
        with patch.object(evidence.sys, "version_info", (3, 9, 20)):
            with self.assertRaisesRegex(ValueError, "Python >= 3.10"):
                evidence.python_identity()
            with self.assertRaisesRegex(ValueError, "Python >= 3.10"):
                evidence.shared_deadline(self.root)

    def test_budget_interpreter_drift_fails_closed(self):
        self.budget["python"]["sha256"] = "different-binary"
        (self.root / "budget.json").write_text(json.dumps(self.budget))
        with self.assertRaisesRegex(ValueError, "interpreter changed"):
            evidence.shared_deadline(self.root)

    def test_cross_exponent_budget_and_one_ulp_tamper(self):
        start = 11970.084807301
        deadline = start + 4500
        self.assertNotEqual(deadline - start, 4500)
        self.budget.update(start_monotonic=start, deadline_monotonic=deadline)
        (self.root / "budget.json").write_text(json.dumps(self.budget))
        with patch.object(evidence.time, "monotonic", return_value=start + 600):
            self.assertEqual(evidence.shared_deadline(self.root), deadline)
            self.budget["deadline_monotonic"] = math.nextafter(deadline, math.inf)
            (self.root / "budget.json").write_text(json.dumps(self.budget))
            with self.assertRaisesRegex(ValueError, "invalid shared deadline"):
                evidence.shared_deadline(self.root)

    def test_budget_is_shared_not_restarted_after_setup(self):
        initial = evidence.shared_deadline(self.root)
        with patch.object(
            evidence.time,
            "monotonic",
            return_value=self.budget["start_monotonic"] + 600,
        ):
            self.assertEqual(evidence.shared_deadline(self.root), initial)
            self.assertEqual(
                evidence.shared_deadline(self.root) - evidence.time.monotonic(), 3900
            )

    def test_budget_bad_values_and_changed_head(self):
        for key, value in [
            ("seconds", 9000),
            ("clock", "wall"),
            ("head", "wrong"),
            ("deadline_monotonic", float("nan")),
            ("start_monotonic", float("inf")),
            ("deadline_monotonic", True),
        ]:
            data = dict(self.budget)
            data[key] = value
            (self.root / "budget.json").write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                evidence.shared_deadline(self.root)

    def test_budget_cannot_be_reset_before_execute(self):
        (self.root / "source.json").write_text(
            json.dumps({"budget_sha256": "not-current-budget"})
        )
        with self.assertRaisesRegex(ValueError, "budget was reset"):
            evidence.execute(self.root)

    def test_full_metadata_requires_resolve_graph(self):
        path = self.root / "metadata.json"
        for resolve in [None, {}, {"nodes": []}]:
            path.write_text(
                json.dumps(
                    {"resolve": resolve, "packages": ["p"], "workspace_members": ["p"]}
                )
            )
            with self.assertRaises(ValueError):
                evidence.validate_metadata(path)
        path.write_text(
            json.dumps(
                {
                    "resolve": {"nodes": [{"id": "p"}]},
                    "packages": ["p"],
                    "workspace_members": ["p"],
                }
            )
        )
        evidence.validate_metadata(path)

    def test_original_wrapper_forwards_full_metadata_without_regenerating(self):
        wrapper = Path(__file__).resolve().parents[2] / "scripts/run-nextest.py"
        self.assertTrue(
            wrapper.is_file(), "run tests from exact baseline-plus-candidate checkout"
        )
        fakebin = self.root / "bin"
        fakebin.mkdir()
        cargo = fakebin / "cargo"
        calls = self.root / "cargo-calls.jsonl"
        cargo.write_text(
            f"#!{sys.executable}\nimport json,sys\nwith open({str(calls)!r}, 'a') as output: output.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        )
        cargo.chmod(0o755)
        metadata = self.root / "full-metadata.json"
        metadata.write_text('{"resolve":{"nodes":[]}}')
        for phase in evidence.PHASES:
            args = evidence.selection(phase) + [
                "--cargo-metadata",
                str(metadata),
                "--profile",
                evidence.PROFILE,
                "--retries",
                "0",
                "--no-tests",
                "fail",
            ]
            env = dict(os.environ, PATH=str(fakebin) + os.pathsep + os.environ["PATH"])
            result = subprocess.run(
                [sys.executable, str(wrapper), *args],
                cwd=self.root,
                env=env,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            command = json.loads(calls.read_text().splitlines()[-1])
            self.assertEqual(command, ["nextest", "run", "--no-fail-fast", *args])
        self.assertEqual(len(calls.read_text().splitlines()), 3)

    def test_exact_just_version_rejects_suffix(self):
        evidence.validate_version("just", b"just 1.59.0\n", "just 1.59.0")
        for raw in [b"just 1.59.00\n", b"just 1.59.0-custom\n", b"just 1.59.1\n"]:
            with self.assertRaises(ValueError):
                evidence.validate_version("just", raw, "just 1.59.0")

    def test_binding_rejects_wrong_head_before_build(self):
        with (
            patch.object(evidence, "git", return_value="wrong-head"),
            patch.dict(
                os.environ, {"CANDIDATE_SHA": "expected", "WORKFLOW_SHA": "expected"}
            ),
        ):
            with self.assertRaisesRegex(ValueError, "head/workflow mismatch"):
                evidence.bind(self.root)

    def test_verifier_rejects_missing_source(self):
        with self.assertRaises(FileNotFoundError):
            evidence.verify(self.root)

    def test_verifier_rejects_head_and_dirty_drift(self):
        (self.root / "source.json").write_text(
            json.dumps({"head": "expected", "files": {}})
        )
        with patch.dict(
            os.environ, {"CANDIDATE_SHA": "expected", "WORKFLOW_SHA": "expected"}
        ):
            with patch.object(evidence, "git", return_value="wrong"):
                with self.assertRaisesRegex(ValueError, "head drift"):
                    evidence.verify(self.root)
            with patch.object(
                evidence, "git", side_effect=["expected", " M source.rs"]
            ):
                with self.assertRaisesRegex(ValueError, "dirty after run"):
                    evidence.verify(self.root)

    def test_owned_descendant_after_leader_exit(self):
        marker = self.root / "orphan-ran"
        child = f"import json,os,time;print(json.dumps(dict(pid=os.getpid(),ppid=os.getppid(),pgid=os.getpgrp(),sid=os.getsid(0),uid=os.geteuid())),flush=True);time.sleep(0.8);open({str(marker)!r},'w').close()"
        parent = f"import json,os,subprocess,sys;child=subprocess.Popen([sys.executable,'-c',{child!r}]);print(json.dumps(dict(parent_pid=os.getpid(),child_pid=child.pid,pgid=os.getpgrp(),uid=os.geteuid())),flush=True)"
        self.assertEqual(
            evidence.bounded(
                [sys.executable, "-c", parent],
                self.root / "orphan",
                time.monotonic() + 3,
                self.root,
                grace=0.1,
            ),
            0,
        )
        time.sleep(0.8)
        self.assertFalse(marker.exists())

    def test_command_success_and_failure_raw_logs(self):
        for code in [0, 7]:
            out = self.root / str(code)
            status = evidence.bounded(
                [
                    sys.executable,
                    "-c",
                    f"import sys; print('raw stdout'); print('raw stderr',file=sys.stderr);sys.exit({code})",
                ],
                out,
                time.monotonic() + 3,
                self.root,
                grace=0.1,
            )
            self.assertEqual(status, code)
            self.assertEqual((out / "stdout.log").read_bytes(), b"raw stdout\n")
            self.assertEqual((out / "stderr.log").read_bytes(), b"raw stderr\n")

    def test_total_deadline_and_unstarted_command(self):
        deadline = time.monotonic() + 0.1
        self.assertEqual(
            evidence.bounded(
                [sys.executable, "-c", "import time;time.sleep(20)"],
                self.root / "first",
                deadline,
                self.root,
                grace=0.1,
            ),
            124,
        )
        marker = self.root / "should-not-exist"
        self.assertEqual(
            evidence.bounded(
                [sys.executable, "-c", f"open({str(marker)!r},'w').close()"],
                self.root / "second",
                deadline,
                self.root,
                grace=0.1,
            ),
            125,
        )
        self.assertFalse(marker.exists())

    @unittest.skipUnless(os.name == "posix", "owned process groups are Unix-only")
    def test_owned_descendant_cleanup(self):
        marker = self.root / "descendant-ran"
        child = f"import json,os,time;print(json.dumps(dict(pid=os.getpid(),ppid=os.getppid(),pgid=os.getpgrp(),sid=os.getsid(0),uid=os.geteuid())),flush=True);time.sleep(0.8);open({str(marker)!r},'w').close()"
        parent = f"import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',{child!r}]);time.sleep(20)"
        status = evidence.bounded(
            [sys.executable, "-c", parent],
            self.root / "group",
            time.monotonic() + 0.2,
            self.root,
            grace=0.1,
        )
        self.assertEqual(status, 124)
        time.sleep(0.8)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
