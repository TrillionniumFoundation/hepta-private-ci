"""Real, tiny subprocess fixtures; no Fashion data or model imports."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest.mock import patch

from fashion_research.lifecycle import Progress
from fashion_research.supervision import supervise


@unittest.skipUnless(os.name == "posix" and Path("/proc").is_dir(), "Linux process resource supervisor")
class LifecycleTests(unittest.TestCase):
    def _progress(self, output):
        progress = Progress(output, [11, 23, 47])
        progress.start_stage("shared")
        progress.complete_stage("shared")
        progress.start_stage("content", seed=11)
        return progress.snapshot()

    def _spawn(self, output, body):
        script = ("import json, os, signal, sys\nfrom pathlib import Path\n"
                  "output = Path(sys.argv[1])\n" + textwrap.dedent(body))
        process = subprocess.Popen([sys.executable, "-c", script, str(output)],
                                   start_new_session=True, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

        def finish():
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
            process.stderr.close()

        self.addCleanup(finish)
        return process

    def _when_ready(self, output, reason):
        deadline = time.monotonic() + 5

        def request_stop():
            if (output / "ready").exists():
                return reason
            if time.monotonic() >= deadline:
                raise AssertionError("fixture did not reach ready state")
            return None

        return request_stop

    def _assert_partial(self, output, receipt, before):
        # The launcher terminal status is distinct from the worker return code.
        self.assertNotEqual(receipt["exit_code"], 0)
        self.assertIs(receipt["partial"], True)
        self.assertTrue(receipt["termination_reason"])
        for key in ("started_seeds", "unrun_seeds", "started_stages",
                    "completed_stages", "unrun_stages", "current_stage"):
            self.assertEqual(receipt[key], before[key], key)
        self.assertEqual(receipt["started_seeds"], [11])
        self.assertEqual(receipt["unrun_seeds"], [23, 47])
        self.assertEqual(json.loads((output / "result.json").read_text()), receipt)
        self.assertEqual(json.loads((output / "progress.json").read_text()), before)

    def test_requested_stop_overrides_worker_success_and_preserves_its_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            before = self._progress(output)
            process = self._spawn(output, """
                def stopped(signum, frame):
                    (output / 'result.json').write_text(json.dumps(
                        {'exit_code': 0, 'sentinel': 'worker accepted TERM'}))
                    raise SystemExit(0)
                signal.signal(signal.SIGTERM, stopped)
                (output / 'ready').write_text('ready')
                while True:
                    signal.pause()
            """)
            receipt = supervise(output, process, poll_seconds=.005, grace_seconds=.2,
                                request_stop=self._when_ready(output, "fixture requested stop"),
                                parent_clock=lambda: 0)
            self._assert_partial(output, receipt, before)
            self.assertEqual(receipt["worker_returncode"], 0)
            self.assertEqual(receipt["termination_reason"], "fixture requested stop")
            self.assertEqual(json.loads((output / "worker-result.json").read_text()),
                             {"exit_code": 0, "sentinel": "worker accepted TERM"})

    def test_ignored_term_is_killed_and_no_worker_finally_is_required(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            before = self._progress(output)
            process = self._spawn(output, """
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
                try:
                    (output / 'ready').write_text('ready')
                    while True:
                        signal.pause()
                finally:
                    (output / 'worker-finally').write_text('finished')
            """)
            receipt = supervise(output, process, poll_seconds=.005, grace_seconds=.02,
                                request_stop=self._when_ready(output, "fixture ignored TERM"),
                                parent_clock=lambda: 0)
            self._assert_partial(output, receipt, before)
            self.assertEqual(receipt["worker_returncode"], -signal.SIGKILL)
            self.assertEqual(receipt["termination_reason"], "fixture ignored TERM")
            self.assertIs(receipt["accounting_complete"], False)
            self.assertFalse((output / "worker-finally").exists())

    def test_self_sigkill_without_result_gets_atomic_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            before = self._progress(output)
            process = self._spawn(output, """
                try:
                    (output / 'ready').write_text('ready')
                    os.kill(os.getpid(), signal.SIGKILL)
                finally:
                    (output / 'worker-finally').write_text('finished')
            """)
            receipt = supervise(output, process, poll_seconds=.005, parent_clock=lambda: 0)
            self._assert_partial(output, receipt, before)
            self.assertEqual(receipt["worker_returncode"], -signal.SIGKILL)
            self.assertIs(receipt["accounting_complete"], False)
            self.assertFalse((output / "worker-result.json").exists())
            self.assertFalse((output / "worker-finally").exists())

    def test_worker_signal_context_runs_finally_and_restores_both_handlers(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            process = self._spawn(output, """
                from fashion_research.lifecycle import WorkerInterrupted, atomic_json, worker_signals
                previous = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
                caught = None
                with worker_signals():
                    try:
                        os.kill(os.getpid(), signal.SIGTERM)
                    except WorkerInterrupted as error:
                        caught = str(error)
                    finally:
                        atomic_json(output / 'finally-receipt.json',
                                    {'finally_ran': True, 'interruption': caught})
                restored = {signal.Signals(s).name: signal.getsignal(s) == old
                            for s, old in previous.items()}
                atomic_json(output / 'restored-handlers.json', restored)
                raise SystemExit(0 if caught and all(restored.values()) else 1)
            """)
            _, error = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, error.decode())
            self.assertEqual(json.loads((output / "finally-receipt.json").read_text()),
                             {"finally_ran": True, "interruption": "worker interrupted by SIGTERM"})
            self.assertEqual(json.loads((output / "restored-handlers.json").read_text()),
                             {"SIGTERM": True, "SIGINT": True})
            self.assertEqual(list(output.glob("*.tmp-*")), [])

    def test_supervisor_does_not_create_output_before_worker_preflight(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "worker-owned-output"
            allow = Path(directory) / "allow-worker"
            process = self._spawn(output, """
                import time
                from fashion_research.lifecycle import Progress, atomic_json
                allow = output.parent / 'allow-worker'
                deadline = time.monotonic() + 5
                while not allow.exists():
                    if time.monotonic() >= deadline:
                        raise SystemExit(8)
                    time.sleep(.001)
                if output.exists():
                    raise SystemExit(7)
                output.mkdir()
                progress = Progress(output, [])
                for stage in ('shared', 'final_receipt'):
                    progress.start_stage(stage)
                    progress.complete_stage(stage)
                atomic_json(output / 'result.json', {'exit_code': 0, 'status': 'fixture_complete'})
            """)

            def release():
                allow.touch()
                return None

            receipt = supervise(output, process, poll_seconds=.005,
                                request_stop=release, parent_clock=lambda: 0)
            self.assertEqual(receipt["worker_returncode"], 0)
            self.assertEqual(receipt["exit_code"], 0)
            self.assertFalse(receipt["partial"])

    def test_supervisor_exception_reaps_worker_and_retains_actual_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            before = self._progress(output)
            process = self._spawn(output, """
                (output / 'ready').write_text('ready')
                while True:
                    pass
            """)
            ready = self._when_ready(output, "ready")

            def fail_when_ready():
                if ready():
                    raise RuntimeError("handmade supervisor exception after WNOHANG")
                return None

            receipt = supervise(output, process, poll_seconds=.005,
                                request_stop=fail_when_ready, parent_clock=lambda: 0)
            self._assert_partial(output, receipt, before)
            self.assertEqual(receipt["worker_returncode"], -signal.SIGKILL)
            self.assertGreater(receipt["worker_CPU_ns"], 0)
            self.assertIn("handmade supervisor exception", receipt["termination_reason"])
            with self.assertRaises(ChildProcessError):
                os.waitpid(process.pid, os.WNOHANG)

    def test_cpu_cap_kills_immediately_without_term_or_flush_grace(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            before = self._progress(output)
            process = self._spawn(output, """
                def stopped(signum, frame):
                    (output / 'term-received').write_text('TERM')
                    raise SystemExit(0)
                signal.signal(signal.SIGTERM, stopped)
                (output / 'ready').write_text('ready')
                while True:
                    pass
            """)
            signals = []
            original_kill, original_killpg = os.kill, os.killpg

            def kill(pid, signum):
                signals.append(signum)
                return original_kill(pid, signum)

            def killpg(pgid, signum):
                signals.append(signum)
                return original_killpg(pgid, signum)

            # Verify the resource branch bypasses grace without a timing-speed gate.
            with patch("fashion_research.supervision.os.kill", side_effect=kill), \
                    patch("fashion_research.supervision.os.killpg", side_effect=killpg):
                receipt = supervise(output, process, cpu_limit_ns=10_000_000,
                                    poll_seconds=.002, grace_seconds=5, parent_clock=lambda: 0)
            self._assert_partial(output, receipt, before)
            self.assertIn("cpu", receipt["termination_reason"].lower())
            self.assertEqual(receipt["worker_returncode"], -signal.SIGKILL)
            self.assertIn(signal.SIGKILL, signals)
            self.assertNotIn(signal.SIGTERM, signals)
            self.assertFalse((output / "term-received").exists())
            self.assertIs(receipt["accounting_complete"], False)


if __name__ == "__main__":
    unittest.main()
