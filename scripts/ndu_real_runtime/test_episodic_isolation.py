"""Behavioral isolation controls; namespace tests never degrade to plain subprocesses."""

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

from . import episodic_isolation
from .episodic_isolation import MAX_INPUT_BYTES, run_isolated_actor


ACTOR = b"""
import json, os, socket
from pathlib import Path
task = json.loads(Path("/input/task.json").read_bytes())
denied = []
for path in task["forbidden_paths"]:
    try:
        Path(path).read_bytes()
        denied.append(False)
    except OSError:
        denied.append(True)
try:
    os.read(99, 16)
    fd_closed = False
except OSError:
    fd_closed = True
cache = Path("/cache/previous-turn")
cache_was_empty = not cache.exists()
cache.write_text("private-to-this-turn")
memory = Path("/input/memory.txt")
tool = __import__("subprocess").run(
    ["/usr/bin/python3", "-I", "-c",
     "from pathlib import Path; import sys; "
     "print(Path(sys.argv[1]).exists())", task["forbidden_paths"][0]],
    capture_output=True, text=True, check=True)
print(json.dumps({"denied": denied, "fd_closed": fd_closed,
 "tool_can_see_writer": tool.stdout.strip() == "True",
 "cache_was_empty": cache_was_empty,
 "context": memory.read_text() if memory.exists() else "",
 "unexpected_env": sorted(set(os.environ) -
   {"HOME", "XDG_CACHE_HOME", "TMPDIR", "PATH", "LANG", "LC_CTYPE"})}))
"""


class IsolationAdmissionTests(unittest.TestCase):
    def test_off_rejects_context_before_launch_or_output_creation(self):
        with tempfile.TemporaryDirectory() as root:
            destination = Path(root) / "run"
            with self.assertRaises(ValueError):
                run_isolated_actor(
                    destination,
                    b"print('actor')",
                    {},
                    mode="off",
                    memory_context="prior private fact",
                )
            self.assertFalse(destination.exists())

    def test_closed_inputs_reject_bad_modes_sizes_and_timeouts(self):
        with tempfile.TemporaryDirectory() as root:
            destination = Path(root) / "run"
            for change in (
                {"mode": []},
                {"mode": "delivery_off"},
                {"timeout_seconds": True},
                {"timeout_seconds": float("nan")},
                {"timeout_seconds": float("inf")},
                {"actor_source": b"#" * (MAX_INPUT_BYTES + 1)},
                {"public_task": {"score": float("nan")}},
            ):
                options = {"actor_source": b"pass", "public_task": {}, "mode": "off"}
                options.update(change)
                with self.subTest(change=list(change)):
                    with self.assertRaises((ValueError, TypeError)):
                        run_isolated_actor(destination, **options)
            self.assertFalse(destination.exists())

    def test_missing_bwrap_retains_failed_attempt_and_cannot_start_actor(self):
        with (
            tempfile.TemporaryDirectory() as root,
            patch.object(episodic_isolation.shutil, "which", return_value=None),
        ):
            destination = Path(root) / "run"
            result = run_isolated_actor(
                destination,
                b"print('must-not-run')",
                {"prompt": "public C"},
                mode="off",
            )
            self.assertEqual(result["status"], "SETUP_FAILED")
            self.assertIsNone(result["bootstrap"])
            self.assertEqual((destination / "stdout.bin").read_bytes(), b"")
            self.assertFalse((destination / "actor-output.bin").exists())
            self.assertEqual(
                json.loads((destination / "RECEIPT.json").read_bytes()), result
            )

    @unittest.skipUnless(
        sys.platform == "linux" and hasattr(os, "memfd_create"), "Linux memfd control"
    )
    def test_sealed_inputs_and_source_changes_keep_failed_receipts(self):
        for change in ("delete", "add"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as root:
                destination = Path(root) / "run"

                def fail_launch(command, **kwargs):
                    for descriptor in kwargs["pass_fds"]:
                        with self.assertRaises(PermissionError):
                            os.write(descriptor, b"changed")
                    inputs = destination / "inputs"
                    if change == "delete":
                        (inputs / "actor.py").unlink()
                    else:
                        (inputs / "unexpected.txt").write_text("not exposed")
                    self.assertNotIn(str(inputs), command)
                    raise OSError("synthetic process-start failure")

                with (
                    patch.object(
                        episodic_isolation.shutil, "which", return_value="/usr/bin/true"
                    ),
                    patch.object(
                        episodic_isolation.subprocess, "Popen", side_effect=fail_launch
                    ),
                ):
                    result = run_isolated_actor(destination, b"pass", {}, mode="off")
                self.assertEqual(result["status"], "SOURCE_CHANGED")
                self.assertFalse(result["source_unchanged"])
                self.assertEqual(
                    json.loads((destination / "RECEIPT.json").read_bytes()), result
                )

    def test_disk_changes_cannot_relabel_loaded_launcher(self):
        with (
            tempfile.TemporaryDirectory() as root,
            patch.object(
                episodic_isolation, "_LOADED_LAUNCHER_SOURCE", b"retired-source"
            ),
        ):
            result = run_isolated_actor(Path(root) / "run", b"pass", {}, mode="off")
            self.assertEqual(result["status"], "SOURCE_CHANGED")
            self.assertIsNone(result["process_identity"])
            self.assertEqual(
                result["launcher_sha256"], hashlib.sha256(b"retired-source").hexdigest()
            )

    def test_existing_run_cannot_be_overwritten_or_replayed(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(FileExistsError):
                run_isolated_actor(root, b"pass", {}, mode="off")


class LinuxNamespaceTests(unittest.TestCase):
    def launch(self, output, *args, **kwargs):
        result = run_isolated_actor(output, *args, **kwargs)
        self.last_stderr = (output / "stderr.bin").read_text(errors="replace")
        evidence = os.environ.get("HEPTA_MEM9_EVIDENCE_ROOT")
        if evidence:
            root = Path(evidence).resolve()
            root.mkdir(parents=True, exist_ok=True)
            target = root / (
                self._testMethodName + "-" + output.name + "-" + uuid.uuid4().hex
            )
            shutil.copytree(output, target)
        return result

    def require_execution(self, result):
        if result["status"] == "SETUP_FAILED":
            reason = (
                result.get("error")
                or self.last_stderr
                or "namespace launch unavailable"
            )
            if os.environ.get("HEPTA_MEM9_REQUIRE_ISOLATION") == "1":
                self.fail(reason)
            self.skipTest(reason)
        self.assertEqual(result["status"], "EXECUTED", result)

    def test_on_off_block_original_files_descriptors_tools_and_caches(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            writer = root / "writer"
            writer.mkdir()
            files = [
                writer / name
                for name in ("store.sqlite", "snapshot", "history", "cache")
            ]
            for path in files:
                path.write_text("A-private-canary")
            task = {"forbidden_paths": list(map(str, files)), "prompt": "new C"}
            with files[0].open("rb") as descriptor:
                os.dup2(descriptor.fileno(), 99, inheritable=True)
                try:
                    off = self.launch(root / "off", ACTOR, task, mode="off")
                    self.require_execution(off)
                    on = self.launch(
                        root / "on",
                        ACTOR,
                        task,
                        mode="on",
                        memory_context="A-private-canary",
                    )
                    self.require_execution(on)
                finally:
                    os.close(99)
            expected = {
                "denied": [True] * 4,
                "fd_closed": True,
                "tool_can_see_writer": False,
                "cache_was_empty": True,
                "context": "",
                "unexpected_env": [],
            }
            for label, result in (("off", off), ("on", on)):
                actual = json.loads((root / label / "actor-output.bin").read_bytes())
                self.assertEqual(
                    actual,
                    {
                        **expected,
                        "context": "" if label == "off" else "A-private-canary",
                    },
                )
                self.assertTrue(result["source_unchanged"])
                self.assertFalse(result["capture_truncated"])
                self.assertEqual(result["scientific_acceptance"], "HOLD")
            self.assertEqual(off["task_sha256"], on["task_sha256"])
            self.assertEqual(off["actor_sha256"], on["actor_sha256"])
            self.assertNotEqual(off["session_id"], on["session_id"])
            self.assertNotEqual(off["process_identity"], on["process_identity"])
            self.assertEqual(off["context_sha256"], hashlib.sha256(b"").hexdigest())

    def test_timeout_and_output_overflow_cannot_qualify(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            ready = self.launch(root / "ready", b"pass", {}, mode="off")
            self.require_execution(ready)
            timeout = self.launch(
                root / "timeout",
                b"import time; time.sleep(10)",
                {},
                mode="off",
                timeout_seconds=0.2,
            )
            self.assertEqual(timeout["status"], "TIMEOUT")
            overflow = self.launch(
                root / "overflow",
                b"import os; os.write(1, b'x' * 2097152)",
                {},
                mode="off",
            )
            self.assertEqual(overflow["status"], "OUTPUT_LIMIT")
            self.assertTrue(overflow["capture_truncated"])


if __name__ == "__main__":
    unittest.main()
