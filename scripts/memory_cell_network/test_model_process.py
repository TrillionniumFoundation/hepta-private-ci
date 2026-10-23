"""Fresh child bootstrap, retained failures and authenticated error responses."""

import json
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from model_process import run_child


class ModelProcessTests(unittest.TestCase):
    def test_receipt_preserves_raw_output_and_empty_reader_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reader = root / "reader"
            reader.mkdir()
            script = root / "echo.py"
            script.write_text(
                "import json, os, sys\n"
                "print('raw diagnostic', file=sys.stderr)\n"
                "print(json.dumps(dict(pid=os.getpid(), cwd=os.getcwd(), "
                "arguments=sys.argv[1:], input=sys.stdin.read())))\n"
            )
            with ThreadPoolExecutor(max_workers=1) as executor:
                result = executor.submit(
                    run_child,
                    script,
                    ["one"],
                    input_text="closed request",
                    cwd=reader,
                    receipt_dir=root / "receipts",
                ).result(timeout=10)
            self.assertEqual(
                json.loads(result["stdout"]),
                {
                    "pid": result["pid"],
                    "cwd": str(reader),
                    "arguments": ["one"],
                    "input": "closed request",
                },
            )
            protection = {"platform": sys.platform, "status": "unsupported"}
            if sys.platform == "linux":
                protection = dict(
                    platform="linux",
                    status="bound",
                    mechanism="PR_SET_PDEATHSIG",
                    signal="SIGKILL",
                    binding_scope="creating_parent_thread",
                )
            self.assertEqual(
                result["bootstrap"],
                {
                    "schema": "hepta.memory-process.started.v1",
                    "pid": result["pid"],
                    "parent_pid": os.getpid(),
                    "expected_parent_pid": os.getpid(),
                    "parent_death": protection,
                    "cwd": str(reader),
                    "script": str(script),
                },
            )
            self.assertEqual(
                json.loads(Path(result["receipt_path"]).read_text()), result
            )
            self.assertEqual(Path(result["stderr_path"]).read_text(), result["stderr"])
            self.assertIn("raw diagnostic", result["stderr"])
            self.assertEqual(list(reader.iterdir()), [])
            self.assertEqual(result["returncode"], 0)
            self.assertNotEqual(result["launch_thread_id"], threading.get_native_id())

    def test_wrong_parent_cannot_reach_target_script(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "ran"
            script = root / "target.py"
            script.write_text("from pathlib import Path\nPath('ran').touch()\n")
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(Path(__file__).with_name("model_child.py")),
                    "--parent-pid",
                    str(os.getpid() + 1),
                    str(script),
                ],
                cwd=root,
                text=True,
                capture_output=True,
                timeout=10,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("parent exited before model bootstrap", result.stderr)
            self.assertFalse(marker.exists())

    def test_nonzero_and_timeout_return_authenticated_errors_with_receipts(self):
        # Import the transport only for this TCP test; the other checks use
        # stdlib-only children and can run without loading the Torch runtime.
        from network_wire import RemoteError, call, server

        with tempfile.TemporaryDirectory() as directory:
            root, key = Path(directory), os.urandom(32)
            scripts = {
                "nonzero": "raise SystemExit(7)\n",
                "timeout": "import time\ntime.sleep(30)\n",
            }
            for name, code in scripts.items():
                (root / f"{name}.py").write_text(code)

            class Application:
                def dispatch(self, request):
                    return run_child(
                        root / f"{request['case']}.py",
                        timeout=2,
                        receipt_dir=root / "receipts",
                        operation="decoder",
                    )

            instance = server(Application(), key)
            thread = threading.Thread(target=instance.serve_forever, daemon=True)
            thread.start()
            try:
                address = f"http://127.0.0.1:{instance.server_port}"
                for case, message in (
                    ("nonzero", "exited 7"),
                    ("timeout", "timed out"),
                ):
                    with self.assertRaisesRegex(
                        RemoteError, f"isolated decoder {message}"
                    ):
                        call(address, key, {"case": case}, timeout=10)
                receipts = [
                    json.loads(path.read_text())
                    for path in (root / "receipts").glob("*.result.json")
                ]
                self.assertEqual(
                    sorted(row["timed_out"] for row in receipts), [False, True]
                )
                self.assertTrue(all(row["returncode"] != 0 for row in receipts))
                if os.name == "posix":
                    timed_out = next(row for row in receipts if row["timed_out"])
                    self.assertEqual(timed_out["exit_signal"], 9)
                self.assertTrue(
                    all(row["bootstrap"]["pid"] == row["pid"] for row in receipts)
                )
                for row in receipts:
                    self.assertEqual(
                        Path(row["stderr_path"]).read_text(), row["stderr"]
                    )
                print(
                    json.dumps({"child_failure_receipts": receipts}, sort_keys=True),
                    flush=True,
                )
            finally:
                instance.shutdown()
                thread.join(timeout=10)
                instance.server_close()


if __name__ == "__main__":
    unittest.main()
