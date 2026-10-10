"""Resource admission failure must prevent candidate execution, not weaken it."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from control_engineering_v2 import candidate


class CandidateResourceLimitTests(unittest.TestCase):
    def backend(self):
        return SimpleNamespace(
            RLIMIT_AS=1,
            RLIMIT_NPROC=2,
            RLIMIT_CPU=3,
            RLIMIT_FSIZE=4,
            RLIMIT_NOFILE=5,
            RLIM_INFINITY=-1,
            getrlimit=Mock(return_value=(16, 32)),
            setrlimit=Mock(),
        )

    def test_requested_limits_never_widen_existing_limits(self):
        backend = self.backend()
        with patch.object(candidate, "_resource", backend):
            candidate._resource_limiter(1024, 128, 30)()
        self.assertEqual(backend.setrlimit.call_count, 5)
        for call in backend.setrlimit.call_args_list:
            self.assertEqual(call.args[1], (16, 32) if call.args[0] != 3 else (16, 31))

    def test_missing_backend_or_required_limit_rejects_entry(self):
        backend = self.backend()
        del backend.RLIMIT_NPROC
        for unavailable in (None, backend):
            with self.subTest(backend=unavailable):
                with patch.object(candidate, "_resource", unavailable):
                    with self.assertRaisesRegex(RuntimeError, "unavailable"):
                        candidate._resource_limiter(1024, 128, 30)()

    def test_limit_read_or_write_failure_rejects_entry(self):
        for method in ("getrlimit", "setrlimit"):
            for failure in (OSError("denied"), ValueError("unsupported")):
                with self.subTest(method=method, failure=type(failure)):
                    backend = self.backend()
                    getattr(backend, method).side_effect = failure
                    with patch.object(candidate, "_resource", backend):
                        with self.assertRaisesRegex(RuntimeError, "cannot enforce"):
                            candidate._resource_limiter(1024, 128, 30)()

    @unittest.skipUnless(os.name == "posix", "pre-exec admission is POSIX-specific")
    def test_failed_preexec_does_not_run_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "entered"
            with patch.object(candidate, "_resource", None):
                code = candidate._run_bounded(
                    (sys.executable, "-I", "-c", f"open({str(marker)!r}, 'w').close()"),
                    cwd=Path(directory),
                    environment=None,
                    timeout=5,
                    memory_bytes=512 * 1024 * 1024,
                    processes=128,
                )
            self.assertEqual(code, 127)
            self.assertFalse(marker.exists())

    @unittest.skipUnless(os.name == "posix", "pre-exec admission is POSIX-specific")
    def test_successful_admission_still_executes_a_bounded_candidate(self):
        if candidate._resource is None:
            self.skipTest("resource backend is unavailable")
        code = candidate._run_bounded(
            (sys.executable, "-I", "-c", "pass"),
            cwd=None,
            environment=None,
            timeout=5,
            memory_bytes=512 * 1024 * 1024,
            processes=128,
        )
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
