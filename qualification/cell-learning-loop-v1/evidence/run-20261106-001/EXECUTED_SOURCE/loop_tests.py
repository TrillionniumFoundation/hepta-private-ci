"""Exercise the resume/failed-cost boundary without loading or training a model."""

import contextlib
import io
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import run_loop
from loop_common import read, write


class ResumeBoundary(unittest.TestCase):
    def test_failed_engineering_result_is_retained_and_cannot_be_resumed(self):
        with tempfile.TemporaryDirectory(dir=run_loop.HERE) as temporary:
            root = Path(temporary)
            run = root / "run"
            plan = {"phases": ["bootstrap"], "child_deadline_seconds": 10}

            def prepare(output, donor, model_dir, here):
                output.mkdir()
                write(output / "PROTOCOL.json", plan)
                code = output / "EXECUTED_SOURCE"
                code.mkdir()
                for name in ("run_loop.py", "prepare_run.py", "loop_common.py"):
                    shutil.copyfile(here / name, code / name)
                (code / "loop_worker.py").write_text(
                    'import json,os,sys\n'
                    'print(json.dumps({"status":"completed","phase":sys.argv[2],"pid":os.getpid(),'
                    '"result":{"engineering_passed":False}}))\n')

            args = SimpleNamespace(output=run, donor=root, model_dir=root, resume=False, stop_after="bootstrap")
            with patch.object(run_loop, "prepare", prepare), patch.object(run_loop, "PHASES", ("bootstrap",)), \
                    patch.object(run_loop, "frozen", return_value=plan), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, "did not pass"):
                    run_loop.main(args)
                failed = read(run / "phase_results/bootstrap.json")
                aggregate = read(run / "FAILED-01.json")
                self.assertEqual(failed["status"], "failed")
                self.assertFalse(aggregate["engineering_passed"])
                self.assertIsNone(aggregate["measured_cost"]["peak_worker_rss_bytes"])
                self.assertEqual(aggregate["measured_cost"]["unmeasured_worker_rss_phases"], ["bootstrap"])
                original_stdout = (run / "attempts/bootstrap/stdout.txt").read_bytes()
                args.resume = True
                with self.assertRaisesRegex(ValueError, "no implicit retry"):
                    run_loop.main(args)
                self.assertEqual((run / "attempts/bootstrap/stdout.txt").read_bytes(), original_stdout)
                self.assertEqual(read(run / "FAILED-02.json")["training_attempts"], 0)
                self.assertEqual(len(list((run / "attempts").iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
