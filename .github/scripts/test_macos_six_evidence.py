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

import macos_six_evidence as evidence


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

    def report(self, phase="original-automation-migrations"):
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

    def check_report(self, root, phase="original-automation-migrations"):
        path = self.root / "junit.xml"
        ET.ElementTree(root).write(path)
        return evidence.validate_report(path, phase)

    def test_exact_all_phases(self):
        for phase in evidence.PHASES:
            self.assertEqual(
                len(self.check_report(self.report(phase), phase)),
                len(evidence.expected(phase)),
            )
        self.assertEqual(sum(len(evidence.expected(p)) for p in evidence.PHASES), 137)

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
                "codex-hepta-automation": {
                    "binary-id": "codex-hepta-automation",
                    "status": "listed",
                    "testcases": {
                        name: {"ignored": False, "filter-match": {"status": "matches"}}
                        for _, name in evidence.expected(
                            "original-automation-migrations"
                        )
                    },
                }
            }
        }

    def test_list_exact_and_filtered_not_passed(self):
        listing = self.listing()
        listing["rust-suites"]["codex-hepta-automation"]["testcases"]["unselected"] = {
            "ignored": True,
            "filter-match": {"status": "mismatch"},
        }
        path = self.root / "list.json"
        path.write_text(json.dumps(listing))
        self.assertEqual(
            len(evidence.validate_list(path, "original-automation-migrations")), 4
        )

    def test_list_missing_ignored_extra_mismatch(self):
        for mutation in ["missing", "ignored", "extra", "mismatch", "binary"]:
            listing = self.listing()
            suite = listing["rust-suites"]["codex-hepta-automation"]
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
                evidence.validate_list(path, "original-automation-migrations")

    def owned_snapshot_fixture(self, process, directory, stage, state="S"):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "probe-state.stdout.log").write_text(
            f"{process.pid} {os.getpid()} {process.pid} 0 {os.geteuid()} {state} Sun Oct 25 01:48:48 2026\n"
        )
        (directory / "probe-state.stderr.log").write_bytes(b"")
        return {
            "exit": 0,
            "owned_pgid": process.pid,
            "observer_pid": os.getpid(),
            "observer_euid": os.geteuid(),
            "binary_sha256": "a" * 64,
            "argv": [
                "/bin/ps",
                "-g",
                str(process.pid),
                "-o",
                "pid=,ppid=,pgid=,sess=,uid=,state=,lstart=",
            ],
            "limit_bytes": 16384,
            "timeout_seconds": 2,
            "stage": stage,
        }

    def terminal_cleanup_fixture(self, process, directory, stage, deadline):
        return self.owned_snapshot_fixture(process, directory, stage, "Z<")

    def live_cleanup_fixture(self, process, directory, stage, deadline):
        return self.owned_snapshot_fixture(process, directory, stage, "S")

    @patch.object(evidence.os, "getsid", new=lambda pid: 4242)
    @patch.object(evidence.os, "getpgid", new=lambda pid: 4242)
    def test_lifecycle_sole_zombie_reaps_exact_child_without_final_signal(self):
        for wait_status, returncode in [(0, 0), (15, -15)]:
            with self.subTest(wait_status=wait_status):
                child = Mock(pid=4242, returncode=None)
                child.wait.side_effect = [
                    subprocess.TimeoutExpired("fake", 0),
                    returncode,
                ]

                def snapshot(process, directory, stage):
                    return self.owned_snapshot_fixture(
                        process,
                        directory,
                        stage,
                        state="Z<" if stage == "before-final-kill" else "S",
                    )

                directory = self.root / f"reap-{wait_status}"
                with (
                    patch.object(evidence.platform, "system", return_value="Darwin"),
                    patch.object(evidence.subprocess, "Popen", return_value=child),
                    patch.object(
                        evidence, "capture_owned_snapshot", side_effect=snapshot
                    ),
                    patch.object(evidence, "observe_command", return_value=None),
                    patch.object(evidence, "observe_leader", return_value=returncode),
                    patch.object(
                        evidence,
                        "capture_cleanup_snapshot",
                        side_effect=self.terminal_cleanup_fixture,
                    ),
                    patch.object(evidence.os, "killpg") as signals,
                    patch.object(
                        evidence.os, "waitpid", return_value=(4242, wait_status)
                    ) as reap,
                ):
                    self.assertEqual(
                        evidence.bounded(
                            ["fake"],
                            directory,
                            time.monotonic() + 3,
                            self.root,
                            grace=0.1,
                        ),
                        124,
                    )
                self.assertEqual(
                    [c.args for c in signals.call_args_list],
                    [],
                )
                reap.assert_called_once_with(4242, os.WNOHANG)
                self.assertEqual(child.returncode, returncode)
                self.assertTrue(
                    json.loads((directory / "result.json").read_text())[
                        "leader_lifecycle"
                    ]["reaped"]
                )

    @patch.object(evidence.os, "getsid", new=lambda pid: 4242)
    @patch.object(evidence.os, "getpgid", new=lambda pid: 4242)
    def test_lifecycle_reap_error_returns_125_without_later_group_signal(self):
        for index, failure in enumerate(
            [ChildProcessError("ECHILD"), OSError("reap failure"), (0, 0)]
        ):
            with self.subTest(failure=str(failure)):
                child = Mock(pid=4242, returncode=None)
                child.wait.side_effect = subprocess.TimeoutExpired("fake", 0)

                def snapshot(process, directory, stage):
                    return self.owned_snapshot_fixture(
                        process,
                        directory,
                        stage,
                        "Z<" if stage == "before-final-kill" else "S",
                    )

                directory = self.root / f"failed-reap-{index}"
                with (
                    patch.object(evidence.platform, "system", return_value="Darwin"),
                    patch.object(evidence.subprocess, "Popen", return_value=child),
                    patch.object(
                        evidence, "capture_owned_snapshot", side_effect=snapshot
                    ),
                    patch.object(evidence, "observe_command", return_value=None),
                    patch.object(evidence, "observe_leader", return_value=0),
                    patch.object(
                        evidence,
                        "capture_cleanup_snapshot",
                        side_effect=self.terminal_cleanup_fixture,
                    ),
                    patch.object(evidence.os, "killpg") as signals,
                    patch.object(
                        evidence.os,
                        "waitpid",
                        side_effect=failure if isinstance(failure, Exception) else None,
                        return_value=failure,
                    ),
                ):
                    self.assertEqual(
                        evidence.bounded(
                            ["fake"],
                            directory,
                            time.monotonic() + 3,
                            self.root,
                            grace=0.1,
                        ),
                        125,
                    )
                self.assertEqual(
                    [c.args for c in signals.call_args_list],
                    [],
                )
                self.assertIsNone(child.returncode)

    @patch.object(evidence.os, "getsid", new=lambda pid: 4242)
    @patch.object(evidence.os, "getpgid", new=lambda pid: 4242)
    @patch.object(evidence.platform, "system", return_value="Linux")
    def test_lifecycle_esrch_never_sends_gratuitous_final_kill(self, _platform):
        child = Mock(pid=4242, returncode=None)
        child.wait.return_value = 0
        with (
            patch.object(evidence.platform, "system", return_value="Linux"),
            patch.object(evidence.subprocess, "Popen", return_value=child),
            patch.object(
                evidence,
                "capture_owned_snapshot",
                side_effect=self.owned_snapshot_fixture,
            ),
            patch.object(
                evidence.os, "killpg", side_effect=[None, ProcessLookupError()]
            ) as signals,
            patch.object(evidence.os, "waitpid") as reap,
        ):
            self.assertEqual(
                evidence.bounded(
                    ["fake"], self.root / "absent", time.monotonic() + 3, self.root
                ),
                0,
            )
        self.assertEqual(
            [c.args for c in signals.call_args_list],
            [(4242, evidence.signal.SIGTERM), (4242, 0)],
        )
        reap.assert_not_called()

    @patch.object(evidence.os, "getsid", new=lambda pid: 4242)
    @patch.object(evidence.os, "getpgid", new=lambda pid: 4242)
    def test_lifecycle_unknown_startup_fails_before_kill(self):
        child = Mock(pid=4242, returncode=None)
        child.wait.return_value = 0
        with (
            patch.object(evidence.platform, "system", return_value="Darwin"),
            patch.object(evidence.subprocess, "Popen", return_value=child),
            patch.object(
                evidence, "capture_owned_snapshot", side_effect=OSError("no identity")
            ),
            patch.object(evidence.os, "killpg") as signals,
        ):
            self.assertEqual(
                evidence.bounded(
                    ["fake"],
                    self.root / "unknown",
                    time.monotonic() + 3,
                    self.root,
                    grace=0,
                ),
                125,
            )
        self.assertEqual([c.args for c in signals.call_args_list], [])

    @patch.object(evidence.os, "getsid", new=lambda pid: 4242)
    @patch.object(evidence.os, "getpgid", new=lambda pid: 4242)
    def test_lifecycle_snapshot_identity_and_completeness_negatives(self):
        child = Mock(pid=4242, returncode=None)
        with patch.object(
            evidence, "capture_owned_snapshot", side_effect=self.owned_snapshot_fixture
        ):
            identity = evidence.bind_owned_leader(child, self.root / "start")
        for mutation in [
            "pid",
            "ppid",
            "pgid",
            "uid",
            "start",
            "binary",
            "reaped",
            "missing",
            "empty",
            "duplicate",
            "foreign",
            "unrelated",
            "malformed",
            "truncated",
            "stderr",
            "ps-fail",
            "timeout",
        ]:
            with self.subTest(mutation=mutation):
                child.returncode = 0 if mutation == "reaped" else None
                directory = self.root / mutation

                def snapshot(process, directory, stage):
                    receipt = self.owned_snapshot_fixture(
                        process, directory, stage, "Z<"
                    )
                    path = directory / "probe-state.stdout.log"
                    text = path.read_text()
                    pieces = text.split()
                    if mutation in {"pid", "ppid", "pgid", "uid"}:
                        index = {"pid": 0, "ppid": 1, "pgid": 2, "uid": 4}[mutation]
                        pieces[index] = str(int(pieces[index]) + 1)
                        text = " ".join(pieces) + "\n"
                    elif mutation == "start":
                        text = text.replace("01:48:48", "01:48:49")
                    elif mutation == "binary":
                        receipt["binary_sha256"] = "changed"
                    elif mutation == "empty":
                        text = ""
                    elif mutation == "duplicate":
                        text += text
                    elif mutation in {"foreign", "unrelated"}:
                        text += f"4243 1 {4244 if mutation == 'foreign' else 4242} 0 {os.geteuid()} S Sun Oct 25 01:48:48 2026\n"
                    elif mutation == "malformed":
                        text = "unparseable\n"
                    elif mutation == "truncated":
                        text = "x" * 16385
                    elif mutation == "stderr":
                        (directory / "probe-state.stderr.log").write_text("warning")
                    elif mutation == "ps-fail":
                        receipt["exit"] = 1
                    elif mutation == "timeout":
                        receipt["unavailable"] = "snapshot timeout"
                    path.write_text(text)
                    return receipt

                with (
                    patch.object(
                        evidence, "capture_owned_snapshot", side_effect=snapshot
                    ),
                    patch.object(evidence.os, "waitpid") as reap,
                    patch.object(evidence.os, "killpg") as signals,
                ):
                    with self.assertRaises(ValueError):
                        evidence.pre_kill_owned_leader(
                            child,
                            None if mutation == "missing" else identity,
                            directory,
                        )
                reap.assert_not_called()
                signals.assert_not_called()

    @patch.object(evidence.os, "getsid", new=lambda pid: 4242)
    @patch.object(evidence.os, "getpgid", new=lambda pid: 4242)
    def test_lifecycle_live_owned_family_never_counts_as_reaped(self):
        child = Mock(pid=4242, returncode=None)
        with patch.object(
            evidence, "capture_owned_snapshot", side_effect=self.owned_snapshot_fixture
        ):
            identity = evidence.bind_owned_leader(child, self.root / "live-start")
            with patch.object(evidence.os, "waitpid") as reap:
                result = evidence.pre_kill_owned_leader(
                    child, identity, self.root / "live"
                )
        self.assertFalse(result["reaped"])
        reap.assert_not_called()

    @unittest.skipUnless(os.name == "posix", "direct-child waitpid is POSIX-only")
    def test_native_waitpid_contract_has_no_cached_or_echild_success(self):
        child = subprocess.Popen(
            [sys.executable, "-c", "raise SystemExit(7)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 3
            while True:
                pid, status = os.waitpid(child.pid, os.WNOHANG)
                if pid == child.pid:
                    self.assertTrue(os.WIFEXITED(status) or os.WIFSIGNALED(status))
                    child.returncode = os.waitstatus_to_exitcode(status)
                    break
                self.assertEqual(pid, 0)
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.01)
            self.assertEqual(child.returncode, 7)
            with self.assertRaises(ChildProcessError):
                os.waitpid(child.pid, os.WNOHANG)
        finally:
            if child.returncode is None:
                child.wait(timeout=3)

    @patch.object(evidence.os, "getsid", new=lambda pid: 4242)
    @patch.object(evidence.os, "getpgid", new=lambda pid: 4242)
    def test_lifecycle_multiple_owned_zombies_are_not_accepted_as_terminal(self):
        child = Mock(pid=4242, returncode=None)
        with patch.object(
            evidence, "capture_owned_snapshot", side_effect=self.owned_snapshot_fixture
        ):
            identity = evidence.bind_owned_leader(child, self.root / "multi-start")

        def snapshot(process, directory, stage):
            receipt = self.owned_snapshot_fixture(process, directory, stage, "Z<")
            path = directory / "probe-state.stdout.log"
            with path.open("a") as stream:
                stream.write(
                    f"4243 4242 4242 0 {os.geteuid()} Z Sun Oct 25 01:48:48 2026\n"
                )
            return receipt

        with (
            patch.object(evidence, "capture_owned_snapshot", side_effect=snapshot),
            patch.object(evidence.os, "waitpid") as reap,
        ):
            self.assertFalse(
                evidence.pre_kill_owned_leader(child, identity, self.root / "multi")[
                    "reaped"
                ]
            )
        reap.assert_not_called()

    def test_lifecycle_competing_reaper_never_authorizes_reap(self):
        child = Mock(pid=4242, returncode=None)
        for target, name, value in [
            (evidence.signal, "getsignal", evidence.signal.SIG_IGN),
            (evidence.threading, "active_count", 2),
        ]:
            with (
                patch.object(target, name, return_value=value),
                patch.object(evidence, "capture_owned_snapshot") as snapshot,
                patch.object(evidence.os, "waitpid") as reap,
            ):
                with self.assertRaises(ValueError):
                    evidence.pre_kill_owned_leader(child, {}, self.root / "competing")
            snapshot.assert_not_called()
            reap.assert_not_called()

    @patch.object(evidence.os, "getsid", new=lambda pid: 4242)
    @patch.object(evidence.os, "getpgid", new=lambda pid: 4242)
    def test_lifecycle_reap_requires_exact_terminal_status(self):
        child = Mock(pid=4242, returncode=None)
        with patch.object(
            evidence, "capture_owned_snapshot", side_effect=self.owned_snapshot_fixture
        ):
            identity = evidence.bind_owned_leader(child, self.root / "reap-start")
        for result in [
            (0, 0),
            (9999, 0),
            (4242, 0x137F),
            ChildProcessError("ECHILD"),
            OSError("wait error"),
        ]:
            child.returncode = None

            def snapshot(process, directory, stage):
                return self.owned_snapshot_fixture(process, directory, stage, "Z<")

            with (
                patch.object(evidence, "capture_owned_snapshot", side_effect=snapshot),
                patch.object(
                    evidence.os,
                    "waitpid",
                    side_effect=result if isinstance(result, Exception) else None,
                    return_value=result,
                ),
                patch.object(evidence.os, "killpg") as signals,
            ):
                with self.assertRaises((ValueError, OSError)):
                    evidence.pre_kill_owned_leader(
                        child, identity, self.root / "bad-reap"
                    )
            self.assertIsNone(child.returncode)
            signals.assert_not_called()

    @unittest.skipUnless(os.name == "posix", "owned waitid contract is POSIX-only")
    def test_native_waitid_wnowait_keeps_child_waitable_until_single_reap(self):
        evidence.require_waitid_contract()
        child = subprocess.Popen(
            [sys.executable, "-c", "raise SystemExit(7)"], start_new_session=True
        )
        try:
            result = evidence.observe_command(child, time.monotonic() + 3)
            self.assertEqual(result, 7)
            self.assertIsNone(child.returncode)
            second = evidence.observe_leader(child)
            self.assertEqual(second, 7)
            pid, status = os.waitpid(child.pid, os.WNOHANG)
            self.assertEqual(pid, child.pid)
            self.assertTrue(os.WIFEXITED(status))
            child.returncode = os.waitstatus_to_exitcode(status)
            self.assertEqual(child.returncode, 7)
            with self.assertRaises(ChildProcessError):
                os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOWAIT | os.WNOHANG)
            receipt = self.root / "waitid-contract"
            receipt.mkdir()
            evidence.write(
                receipt / "result.json",
                {
                    "purpose": "runtime WNOWAIT contract, not product qualification",
                    "python": evidence.python_identity(),
                    "pid": child.pid,
                    "first_observed_exit": result,
                    "second_observed_exit": second,
                    "waitpid_pid": pid,
                    "waitpid_status": status,
                    "returncode": child.returncode,
                    "second_waitid": "ChildProcessError asserted",
                },
            )
        finally:
            if child.returncode is None:
                child.wait(timeout=3)

    def test_waitid_observation_rejects_nonterminal_wrong_identity_and_maps_signals(
        self,
    ):
        child = Mock(pid=4242, returncode=None)
        for code, status, expected in [
            (os.CLD_EXITED, 7, 7),
            (os.CLD_KILLED, 15, -15),
            (os.CLD_DUMPED, 6, -6),
        ]:
            event = Mock(
                si_pid=4242,
                si_signo=evidence.signal.SIGCHLD,
                si_code=code,
                si_status=status,
                si_uid=0,
            )
            with patch.object(evidence.os, "waitid", return_value=event) as observe:
                self.assertEqual(evidence.observe_leader(child), expected)
            observe.assert_called_once_with(
                os.P_PID, 4242, os.WEXITED | os.WNOWAIT | os.WNOHANG
            )
            self.assertIsNone(child.returncode)
        for field, value in [
            ("si_pid", 9999),
            ("si_signo", 0),
            ("si_code", os.CLD_STOPPED),
            ("si_status", 999),
        ]:
            event = Mock(
                si_pid=4242,
                si_signo=evidence.signal.SIGCHLD,
                si_code=os.CLD_EXITED,
                si_status=0,
            )
            setattr(event, field, value)
            with patch.object(evidence.os, "waitid", return_value=event):
                with self.assertRaises(ValueError):
                    evidence.observe_leader(child)

    def test_missing_waitid_contract_fails_before_spawn_without_platform_fallback(self):
        saved = os.waitid
        try:
            del os.waitid
            with (
                patch.object(evidence.platform, "system", return_value="Darwin"),
                patch.object(evidence.subprocess, "Popen") as spawn,
                patch.object(evidence.os, "killpg") as signals,
            ):
                self.assertEqual(
                    evidence.bounded(
                        ["fake"],
                        self.root / "no-waitid",
                        time.monotonic() + 3,
                        self.root,
                    ),
                    125,
                )
            spawn.assert_not_called()
            signals.assert_not_called()
        finally:
            os.waitid = saved

    def test_fast_exit_before_session_read_completes_without_any_signal(self):
        child = Mock(pid=4242, returncode=None)
        child.wait.side_effect = AssertionError("must not auto-reap")
        child.poll.side_effect = AssertionError("must not auto-reap")

        def startup(process, directory, stage):
            return self.owned_snapshot_fixture(process, directory, stage, "Z<")

        with (
            patch.object(evidence.platform, "system", return_value="Darwin"),
            patch.object(evidence.subprocess, "Popen", return_value=child),
            patch.object(evidence, "capture_owned_snapshot", side_effect=startup),
            patch.object(
                evidence,
                "capture_cleanup_snapshot",
                side_effect=self.terminal_cleanup_fixture,
            ),
            patch.object(evidence, "observe_leader", return_value=0),
            patch.object(evidence.os, "getsid") as sid,
            patch.object(evidence.os, "getpgid") as pgid,
            patch.object(evidence.os, "killpg") as signals,
            patch.object(evidence.os, "waitpid", return_value=(4242, 0)) as reap,
        ):
            self.assertEqual(
                evidence.bounded(
                    ["fake"],
                    self.root / "fast-complete",
                    time.monotonic() + 3,
                    self.root,
                    grace=0.1,
                ),
                0,
            )
        sid.assert_not_called()
        pgid.assert_not_called()
        signals.assert_not_called()
        child.wait.assert_not_called()
        child.poll.assert_not_called()
        reap.assert_called_once_with(4242, os.WNOHANG)
        self.assertEqual(child.returncode, 0)

    def test_fast_exited_owned_leader_uses_derived_session_not_invented_getsid(self):
        child = Mock(pid=4242, returncode=None)

        def snapshot(process, directory, stage):
            return self.owned_snapshot_fixture(process, directory, stage, "Z<")

        with (
            patch.object(evidence, "capture_owned_snapshot", side_effect=snapshot),
            patch.object(evidence, "observe_leader", return_value=0),
            patch.object(evidence.os, "getsid") as sid,
            patch.object(evidence.os, "getpgid") as pgid,
        ):
            identity = evidence.bind_owned_leader(child, self.root / "fast-start")
        self.assertEqual(identity["sid"], child.pid)
        self.assertEqual(
            identity["session_observation"], "derived: leader already terminal"
        )
        self.assertNotIn("observed_sid", identity)
        sid.assert_not_called()
        pgid.assert_not_called()

    @patch.object(evidence.os, "getsid", new=lambda pid: 4242)
    @patch.object(evidence.os, "getpgid", new=lambda pid: 4242)
    def test_owned_orphan_session_cleanup_keeps_leader_unreaped_without_signal_zero(
        self,
    ):
        child = Mock(pid=4242, returncode=None)
        child.wait.side_effect = AssertionError("must not auto-reap")
        child.poll.side_effect = AssertionError("must not auto-reap")
        calls = 0

        def snapshot(process, directory, stage, deadline):
            nonlocal calls
            receipt = self.terminal_cleanup_fixture(process, directory, stage, deadline)
            if calls == 0:
                with (directory / "probe-state.stdout.log").open("a") as stream:
                    stream.write(
                        f"4243 1 4242 0 {os.geteuid()} S Sun Oct 25 01:48:48 2026\n"
                    )
            calls += 1
            return receipt

        with (
            patch.object(evidence.platform, "system", return_value="Darwin"),
            patch.object(evidence.subprocess, "Popen", return_value=child),
            patch.object(
                evidence,
                "capture_owned_snapshot",
                side_effect=self.owned_snapshot_fixture,
            ),
            patch.object(evidence, "capture_cleanup_snapshot", side_effect=snapshot),
            patch.object(evidence, "observe_command", return_value=0),
            patch.object(evidence, "observe_leader", return_value=0),
            patch.object(evidence.os, "killpg") as signals,
            patch.object(evidence.os, "waitpid", return_value=(4242, 0)) as reap,
        ):
            self.assertEqual(
                evidence.bounded(
                    ["fake"],
                    self.root / "orphan-session",
                    time.monotonic() + 3,
                    self.root,
                    grace=0.2,
                ),
                0,
            )
        self.assertEqual(
            [c.args for c in signals.call_args_list], [(4242, evidence.signal.SIGTERM)]
        )
        reap.assert_called_once_with(4242, os.WNOHANG)
        child.wait.assert_not_called()
        child.poll.assert_not_called()

    @patch.object(evidence.os, "getsid", new=lambda pid: 4242)
    @patch.object(evidence.os, "getpgid", new=lambda pid: 4242)
    def test_nonchild_zombie_is_never_reaped_or_signaled_and_times_out_unknown(self):
        child = Mock(pid=4242, returncode=None)

        def snapshot(process, directory, stage, deadline):
            receipt = self.terminal_cleanup_fixture(process, directory, stage, deadline)
            with (directory / "probe-state.stdout.log").open("a") as stream:
                stream.write(
                    f"4243 1 4242 0 {os.geteuid()} Z Sun Oct 25 01:48:48 2026\n"
                )
            return receipt

        with (
            patch.object(evidence.platform, "system", return_value="Darwin"),
            patch.object(evidence.subprocess, "Popen", return_value=child),
            patch.object(
                evidence,
                "capture_owned_snapshot",
                side_effect=self.owned_snapshot_fixture,
            ),
            patch.object(evidence, "capture_cleanup_snapshot", side_effect=snapshot),
            patch.object(evidence, "observe_command", return_value=0),
            patch.object(evidence, "observe_leader", return_value=0),
            patch.object(evidence.os, "killpg") as signals,
            patch.object(evidence.os, "waitpid") as reap,
        ):
            self.assertEqual(
                evidence.bounded(
                    ["fake"],
                    self.root / "nonchild-zombie",
                    time.monotonic() + 3,
                    self.root,
                    grace=0.01,
                ),
                125,
            )
        signals.assert_not_called()
        reap.assert_not_called()

    @patch.object(evidence.os, "getsid", new=lambda pid: 4242)
    @patch.object(evidence.os, "getpgid", new=lambda pid: 4242)
    def test_live_orphan_requires_real_sid_and_pgid_even_with_matching_ps_group(self):
        child = Mock(pid=4242, returncode=None)
        with patch.object(
            evidence, "capture_owned_snapshot", side_effect=self.owned_snapshot_fixture
        ):
            identity = evidence.bind_owned_leader(child, self.root / "sid-start")
        directory = self.root / "sid-state"
        receipt = self.owned_snapshot_fixture(child, directory, "before-term", "Z<")
        with (directory / "probe-state.stdout.log").open("a") as stream:
            stream.write(f"4243 1 4242 0 {os.geteuid()} S Sun Oct 25 01:48:48 2026\n")
        for name in ["getsid", "getpgid"]:
            with (
                patch.object(evidence, "observe_leader", return_value=0),
                patch.object(evidence.os, name, return_value=9999),
            ):
                with self.assertRaises(ValueError):
                    evidence.owned_session_state(child, identity, receipt, directory)
        with (
            patch.object(evidence, "observe_leader", return_value=0),
            patch.object(evidence.os, "getsid", side_effect=ProcessLookupError()),
        ):
            self.assertEqual(
                evidence.owned_session_state(child, identity, receipt, directory)[
                    "state"
                ],
                "await-fresh-member-snapshot",
            )
        with (
            patch.object(evidence, "observe_leader", return_value=0),
            patch.object(evidence.os, "getsid", side_effect=PermissionError()),
        ):
            with self.assertRaises(PermissionError):
                evidence.owned_session_state(child, identity, receipt, directory)

    @patch.object(evidence.platform, "system", return_value="Linux")
    def test_first_eperm_diagnostic_does_not_retry_signal_or_pass(self, _platform):
        child = Mock(pid=4242, returncode=None)
        child.wait.return_value = 0
        child.poll.return_value = 0
        with (
            patch.object(evidence.subprocess, "Popen", return_value=child),
            patch.object(
                evidence,
                "capture_owned_snapshot",
                side_effect=self.owned_snapshot_fixture,
            ),
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

    @patch.object(evidence.os, "getsid", new=lambda pid: 4242)
    @patch.object(evidence.os, "getpgid", new=lambda pid: 4242)
    def test_term_and_kill_denials_snapshot_once_without_further_signals(self):
        for sig, stage, effects, grace in [
            (
                evidence.signal.SIGTERM,
                "first-eperm-term",
                [PermissionError(1, "denied term")],
                0.06,
            ),
            (
                evidence.signal.SIGKILL,
                "first-eperm-kill",
                [None, PermissionError(1, "denied kill")],
                0.06,
            ),
        ]:
            for diagnostic_failure in [False, True]:
                with self.subTest(signal=sig, diagnostic_failure=diagnostic_failure):
                    child = Mock(pid=4242, returncode=None)
                    child.wait.return_value = 0
                    directory = self.root / f"denied-{sig}-{diagnostic_failure}"
                    with (
                        patch.object(evidence.subprocess, "Popen", return_value=child),
                        patch.object(
                            evidence.platform, "system", return_value="Darwin"
                        ),
                        patch.object(evidence, "observe_command", return_value=None),
                        patch.object(evidence, "observe_leader", return_value=None),
                        patch.object(
                            evidence,
                            "capture_cleanup_snapshot",
                            side_effect=self.live_cleanup_fixture,
                        ),
                        patch.object(
                            evidence,
                            "capture_owned_snapshot",
                            side_effect=self.owned_snapshot_fixture,
                        ),
                        patch.object(
                            evidence.os, "killpg", side_effect=effects
                        ) as signals,
                        patch.object(
                            evidence,
                            "snapshot_owned_group",
                            side_effect=OSError("diagnostic unavailable")
                            if diagnostic_failure
                            else None,
                            return_value={"classification": "unverified", "state": "Z"},
                        ) as snapshot,
                    ):
                        status = evidence.bounded(
                            ["fake-native-command"],
                            directory,
                            time.monotonic() + 3,
                            self.root,
                            grace=0.06,
                        )
                    self.assertEqual(status, 125)
                    expected = [(4242, evidence.signal.SIGTERM)]
                    if sig == evidence.signal.SIGKILL:
                        expected.append((4242, evidence.signal.SIGKILL))
                    self.assertEqual(
                        [call.args for call in signals.call_args_list], expected
                    )
                    snapshot.assert_called_once_with(4242, directory)
                    receipt = json.loads((directory / "result.json").read_text())
                    self.assertEqual(receipt["error_type"], "PermissionError")
                    self.assertIn("denied", receipt["error"])
                    self.assertEqual(receipt["owned_group_snapshot"]["stage"], stage)
                    self.assertEqual(
                        receipt["owned_group_snapshot"]["classification"], "unverified"
                    )
                    self.assertEqual(
                        "unavailable" in receipt["owned_group_snapshot"],
                        diagnostic_failure,
                    )

    @patch.object(evidence.os, "getsid", new=lambda pid: 4242)
    @patch.object(evidence.os, "getpgid", new=lambda pid: 4242)
    @patch.object(evidence.platform, "system", return_value="Linux")
    def test_snapshot_failure_preserves_original_eperm(self, _platform):
        child = Mock(pid=4242, returncode=None)
        child.wait.return_value = 0
        child.poll.return_value = 0
        with (
            patch.object(evidence.subprocess, "Popen", return_value=child),
            patch.object(
                evidence,
                "capture_owned_snapshot",
                side_effect=self.owned_snapshot_fixture,
            ),
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
            env = dict(
                os.environ,
                PATH=str(fakebin) + os.pathsep + os.environ["PATH"],
                CARGO_TERM_COLOR="always",
            )
            result = subprocess.run(
                [sys.executable, str(wrapper), *args],
                cwd=self.root,
                env=env,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            command = json.loads(calls.read_text().splitlines()[-1])
            self.assertEqual(command, ["nextest", "run", "--no-fail-fast", *args])
        self.assertEqual(len(calls.read_text().splitlines()), len(evidence.PHASES))

    def test_every_nextest_selection_explicitly_disables_color(self):
        for phase in evidence.PHASES:
            args = evidence.selection(phase)
            self.assertEqual(args[:2], ["--color", "never"])
            self.assertEqual(args.count("--color"), 1)
            self.assertFalse(any(arg.startswith("--color=") for arg in args))

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


class StageEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.phase = "sandboxing-seatbelt"
        self.logs = self.root / self.phase / "run"
        self.logs.mkdir(parents=True)
        self.case = "create_seatbelt_args_with_read_only_git_and_codex_subpaths"
        self.begin = f"HEPTA_SEATBELT_STAGE|{self.case}|begin"
        self.token = f"HEPTA_SEATBELT_STAGE|{self.case}|complete"
        self.plan = {
            "required": {self.phase: {self.begin: 1, self.token: 1}},
            "unresolved": [],
        }
        self.here = patch.object(evidence, "HERE", self.root)
        self.here.start()
        self.addCleanup(self.here.stop)

    def check(self, output):
        (self.root / "macos_six_stages.json").write_text(json.dumps(self.plan))
        (self.logs / "stdout.log").write_text(self.begin + "\n" + output)
        (self.logs / "stderr.log").write_text("")
        evidence.validate_stages(self.root)

    def test_exact_receipt(self):
        self.check("    " + self.token + "\n")

    def test_missing_duplicate_wrong_case_or_trailing_text(self):
        for value in [
            "",
            self.token + "\n" + self.token,
            self.token.replace(f"|{self.case}|", "|other|"),
            self.token + "extra",
        ]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.check(value)

    def test_real_nextest_sgr_reset_suffix_is_rejected(self):
        # Batch94 raw nextest stderr ended the complete receipt with ESC[0m.
        with self.assertRaisesRegex(ValueError, "missing/duplicate/unknown"):
            self.check(self.token + "\x1b[0m\n")

    def test_not_exercised_is_rejected_even_with_complete(self):
        with self.assertRaisesRegex(ValueError, "not exercised"):
            self.check(self.token + "\nHEPTA_SEATBELT_STAGE|case|not_exercised\n")

    def test_unknown_extra_stage_is_rejected(self):
        with self.assertRaises(ValueError):
            self.check(self.token + f"\nHEPTA_SEATBELT_STAGE|{self.case}|unknown\n")

    def test_complete_before_begin_is_rejected(self):
        (self.root / "macos_six_stages.json").write_text(json.dumps(self.plan))
        (self.logs / "stdout.log").write_text(self.token + "\n" + self.begin)
        (self.logs / "stderr.log").write_text("")
        with self.assertRaisesRegex(ValueError, "begin and complete"):
            evidence.validate_stages(self.root)

    def test_unresolved_and_empty_contract_are_not_qualification(self):
        self.plan["unresolved"] = ["same-policy positive missing"]
        with self.assertRaises(ValueError):
            self.check(self.token)
        self.plan = {"required": {}, "unresolved": []}
        with self.assertRaises(ValueError):
            self.check(self.token)


class StageCompositionTests(unittest.TestCase):
    def test_reviewed_plan_matches_all_selected_case_and_startup_identities(self):
        plan = json.loads((evidence.HERE / "macos_six_stages.json").read_text())
        self.assertEqual(plan["unresolved"], [])
        self.assertEqual(
            set(plan["required"]),
            {"original-sandboxing-seatbelt", "sandboxing-seatbelt"},
        )
        case = "nested_protected_paths_cannot_be_bypassed_by_renaming_ancestors"
        prefix = f"HEPTA_SEATBELT_STAGE|{case}|restricted_policy_started:"
        actual = {
            k: v
            for k, v in plan["required"]["sandboxing-seatbelt"].items()
            if k.startswith(prefix)
        }
        self.assertEqual(
            actual, {f"{prefix}{p}:{a}": 1 for p in range(7) for a in range(3)}
        )
        self.assertEqual(
            sum(plan["required"]["original-sandboxing-seatbelt"].values()), 5
        )
        self.assertEqual(sum(plan["required"]["sandboxing-seatbelt"].values()), 92)

    def test_synthetic_complete_contract_and_each_missing_startup(self):
        # Synthetic validator inputs only, never a native stage receipt.
        plan = json.loads((evidence.HERE / "macos_six_stages.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            texts = {}
            for phase, tokens in plan["required"].items():
                lines = []
                names = sorted({token.split("|")[1] for token in tokens})
                for name in names:
                    prefix = f"HEPTA_SEATBELT_STAGE|{name}|"
                    lines.append(prefix + "begin")

                    def stage_order(item):
                        token = item[0]
                        return (
                            0
                            if "|restricted_policy_started:" in token
                            else 1
                            if "|ancestor_rename_denied:" in token
                            else 2
                            if "|protected_bytes_unchanged:" in token
                            else 3,
                            token,
                        )

                    for token, count in sorted(tokens.items(), key=stage_order):
                        if token.startswith(prefix) and token not in {
                            prefix + "begin",
                            prefix + "complete",
                        }:
                            lines.extend([token] * count)
                    lines.append(prefix + "complete")
                text = "\n".join(lines) + "\n"
                texts[phase] = text
                logs = root / phase / "run"
                logs.mkdir(parents=True)
                (logs / "stdout.log").write_text(text)
                (logs / "stderr.log").write_text("")
            evidence.validate_stages(root)
            phase = "sandboxing-seatbelt"
            for token in plan["required"][phase]:
                if "|restricted_policy_started:" not in token:
                    continue
                with self.subTest(missing=token):
                    (root / phase / "run/stdout.log").write_text(
                        texts[phase].replace(token + "\n", "")
                    )
                    with self.assertRaises(ValueError):
                        evidence.validate_stages(root)
            (root / phase / "run/stdout.log").write_text(texts[phase])
            evidence.validate_stages(root)
            case = "nested_protected_paths_cannot_be_bypassed_by_renaming_ancestors"
            prefix = f"HEPTA_SEATBELT_STAGE|{case}|"
            startup = prefix + "restricted_policy_started:0:0"
            denial = prefix + "ancestor_rename_denied:0:0"
            reversed_stages = (
                texts[phase]
                .replace(startup, "PLACEHOLDER")
                .replace(denial, startup)
                .replace("PLACEHOLDER", denial)
            )
            (root / phase / "run/stdout.log").write_text(reversed_stages)
            with self.assertRaisesRegex(ValueError, "denial must follow"):
                evidence.validate_stages(root)


if __name__ == "__main__":
    unittest.main()
