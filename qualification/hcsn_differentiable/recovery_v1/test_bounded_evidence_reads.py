"""Regressions for bounded reads and binding a digest to the parsed snapshot."""

import hashlib
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import c2_independent_inventory as inventory
import c2_native_replay as native
import c2_pinned_best_decode as pinned
from c2_durable import append_receipt
import test_c2_native_replay as native_fixture
import test_c2_pinned_best_decode as pinned_fixture


class BoundedEvidenceReadTests(unittest.TestCase):
    def test_native_grown_files_cannot_bypass_stat_bound(self):
        original_stat = Path.stat
        for reader, cap_name in (
            (native._strict_result_bytes, "MAX_RESULT_BYTES"),
            (native._strict_resource_bytes, "MAX_RESOURCE_BYTES"),
        ):
            with (
                self.subTest(reader=reader.__name__),
                tempfile.TemporaryDirectory() as folder,
            ):
                target = Path(folder) / "evidence.json"
                target.write_bytes(b'{"initial":true}')
                before = target.stat()
                target.write_bytes(b'{"padding":"' + b"x" * 128 + b'"}')

                def stale_stat(path, *args, **kwargs):
                    if path == target:
                        return before
                    return original_stat(path, *args, **kwargs)

                with (
                    patch.object(native, cap_name, 64),
                    patch.object(Path, "stat", stale_stat),
                ):
                    with self.assertRaises(native.EvidenceError):
                        reader(target)

    def _snapshot_race(self, field):
        fixture = native_fixture.NativeObservationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        name = native_fixture.NAMES[0]
        fixture.add(name)
        directory = fixture.root / "artifacts" / name
        target = directory / (field + ".json")
        original_read = Path.read_bytes
        replacement = original_read(target)
        committed = (
            b'{"schema":"fixture","schema":"ambiguous"}\n'
            if field == "result"
            else b'{"schema":"wrong-resource-schema"}\n'
        )
        target.write_bytes(committed)
        rebound = fixture.root / "snapshot-receipts"
        append_receipt(
            rebound,
            owner_start_id=native_fixture.OWNER,
            attempt_id=name,
            event_type="terminal",
            payload={
                "status": "completed",
                "native_job_id": "job-" + name,
                "result_sha256": hashlib.sha256(
                    original_read(directory / "result.json")
                ).hexdigest(),
                "resource_sha256": hashlib.sha256(
                    original_read(directory / "resource.json")
                ).hexdigest(),
            },
        )

        def replace_on_reopen(path):
            if path == target:
                target.write_bytes(replacement)
            return original_read(path)

        with patch.object(Path, "read_bytes", replace_on_reopen):
            report = native.inspect_exported_observations(
                rebound,
                owner_start_id=native_fixture.OWNER,
                expected_attempts=native_fixture.NAMES,
                native_observations=fixture.native,
                artifacts_root=fixture.root / "artifacts",
            )
        self.assertIn(name, report["rejected"])
        self.assertEqual(report["structurally_matched_count"], 0)

    def test_result_digest_never_approves_a_different_json_snapshot(self):
        self._snapshot_race("result")

    def test_resource_digest_never_approves_a_different_json_snapshot(self):
        self._snapshot_race("resource")

    @unittest.skipUnless(
        hasattr(os, "mkfifo")
        and hasattr(os, "O_NONBLOCK")
        and hasattr(signal, "SIGALRM"),
        "POSIX FIFO replacement regression",
    )
    def test_readers_reject_fifo_swap_without_blocking(self):
        program = r"""
from pathlib import Path
import os, signal, sys, tempfile
from unittest.mock import patch
import c2_independent_inventory as inventory
import c2_native_replay as native
import c2_pinned_best_decode as pinned
class Blocked(Exception):
    pass
def alarm(signum, frame):
    raise Blocked("the file open blocked after a regular-file observation")
signal.signal(signal.SIGALRM, alarm)
with tempfile.TemporaryDirectory() as folder:
    target = Path(folder) / "evidence.json"
    target.write_bytes(b'{"fixture":true}')
    observed = target.stat()
    original = Path.stat
    armed = [True]
    def replace_after_stat(path, *args, **kwargs):
        if path == target and armed[0]:
            armed[0] = False
            target.unlink()
            os.mkfifo(target)
            return observed
        return original(path, *args, **kwargs)
    functions = {
        "inventory": lambda: inventory._regular_bytes(target, 128),
        "native": lambda: native._strict_result_bytes(target),
        "pinned": lambda: pinned._read_frozen(target, limit=128),
    }
    code = 24
    try:
        signal.alarm(2)
        with patch.object(Path, "stat", replace_after_stat):
            functions[sys.argv[1]]()
    except Blocked:
        code = 23
    except (ValueError, OSError):
        code = 0
    finally:
        signal.alarm(0)
    raise SystemExit(code)
"""
        for reader in ("inventory", "native", "pinned"):
            with self.subTest(reader=reader):
                result = subprocess.run(
                    [sys.executable, "-B", "-c", program, reader],
                    cwd=Path(__file__).parent,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_inventory_rejects_overflow_exponents(self):
        with self.assertRaises(inventory.InvalidEvidence):
            inventory._json(b'{"nested":[1e400]}')

    def test_pinned_inventory_rejects_overflow_exponents(self):
        fixture = pinned_fixture.PinnedBestDecodeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        path = fixture.populate()
        document = path.read_bytes()
        self.assertTrue(document.endswith(b"}"))
        path.write_bytes(document[:-1] + b',"untrusted_extra":1e400}')
        with self.assertRaises(pinned.CheckpointHold):
            pinned.audit(fixture.fits, path)
