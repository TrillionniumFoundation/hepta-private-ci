"""Exercise real subprocess capture and resume without loading a model."""

import contextlib
import io
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import run_loop
from loop_common import identity, read, write


WORKER = '''import json,os,resource,sys,uuid
usage = resource.getrusage(resource.RUSAGE_SELF)
receipt = {"status":"completed","phase":sys.argv[2],"pid":os.getpid(),
    "process_instance_id":uuid.uuid4().hex,"python_optimize":sys.flags.optimize,
    "result":{"engineering_passed":True,"typed_output":[{"correct":True,"value":1}]},
    "worker_metrics":{"wall_seconds":0.01,"cpu_user_seconds":usage.ru_utime,
        "cpu_system_seconds":usage.ru_stime,"peak_rss_bytes":max(1,usage.ru_maxrss)*1024}}
'''


class ResumeBoundary(unittest.TestCase):
    @contextlib.contextmanager
    def fixture(self, edit_worker="", phases=("bootstrap", "feedback"),
                emit='print(json.dumps(receipt, allow_nan=False))\n'):
        with tempfile.TemporaryDirectory(dir=run_loop.HERE) as temporary:
            root = Path(temporary)
            run = root / "run"
            plan = {"phases": list(phases), "child_deadline_seconds": 10}

            def prepare(output, donor, model_dir, here):
                output.mkdir()
                write(output / "PROTOCOL.json", plan)
                code = output / "EXECUTED_SOURCE"
                code.mkdir()
                for name in ("run_loop.py", "prepare_run.py", "loop_common.py", "receipt_verifier.py"):
                    shutil.copyfile(here / name, code / name)
                (code / "loop_worker.py").write_text(WORKER + edit_worker + emit)
                write(output / "INVENTORY.json", {
                    str(path.relative_to(output)): {"identity": identity(path)}
                    for path in sorted(output.rglob("*")) if path.is_file()})
                write(output / "LOCK.json", {name: identity(output / name)["sha256"]
                                            for name in ("PROTOCOL.json", "INVENTORY.json")})

            args = SimpleNamespace(output=run, donor=root, model_dir=root,
                                   resume=False, stop_after=phases[0])
            with patch.object(run_loop, "prepare", prepare), patch.object(run_loop, "PHASES", phases), \
                    contextlib.redirect_stdout(io.StringIO()):
                yield run, args

    def refused_resume(self, run, args, phase="bootstrap"):
        captures = {path: path.read_bytes() for path in (run / "attempts" / phase).glob("*.txt")}
        args.resume = True
        with patch.object(run_loop.subprocess, "run") as launch:
            with self.assertRaisesRegex(ValueError, "no implicit retry"):
                run_loop.main(args)
            launch.assert_not_called()
        self.assertEqual({path: path.read_bytes() for path in captures}, captures)
        failed = read(run / "FAILED-02.json")
        self.assertFalse(failed["engineering_passed"])
        self.assertEqual(failed["completed_phases"], [])
        return failed

    def rewrite(self, run, change):
        path = run / "phase_results/bootstrap.json"
        receipt = read(path)
        change(receipt)
        path.write_text(json.dumps(receipt, allow_nan=False))

    def test_verified_resume_skips_the_real_completed_child(self):
        with self.fixture() as (run, args):
            run_loop.main(args)
            original = (run / "attempts/bootstrap/stdout.txt").read_bytes()
            args.resume = True
            with patch.object(run_loop.subprocess, "run") as launch:
                run_loop.main(args)
                launch.assert_not_called()
            self.assertEqual((run / "attempts/bootstrap/stdout.txt").read_bytes(), original)
            summary = read(run / "PREFLIGHT-02.json")
            self.assertEqual(summary["completed_phases"], ["bootstrap"])
            self.assertEqual(summary["unverified_phase_receipts"], {})
            self.assertEqual(len(list((run / "attempts").iterdir())), 1)

    def test_all_verified_phases_complete_without_model_work(self):
        with self.fixture() as (run, args):
            args.stop_after = "feedback"
            run_loop.main(args)
            summary = read(run / "SUMMARY.json")
            self.assertTrue(summary["engineering_passed"])
            self.assertEqual(summary["completed_phases"], ["bootstrap", "feedback"])
            self.assertEqual(summary["training_attempts"], 0)
            self.assertEqual(len(set(summary["worker_instance_ids"])), 2)

    def test_failed_engineering_result_is_retained_and_cannot_be_resumed(self):
        with self.fixture('receipt["result"]["engineering_passed"] = False\n'
                          'del receipt["worker_metrics"]\n') as (run, args):
            with self.assertRaisesRegex(RuntimeError, "did not pass"):
                run_loop.main(args)
            failed = read(run / "phase_results/bootstrap.json")
            aggregate = read(run / "FAILED-01.json")
            self.assertEqual(failed["status"], "failed")
            self.assertFalse(aggregate["engineering_passed"])
            self.assertIsNone(aggregate["measured_cost"]["peak_worker_rss_bytes"])
            self.assertEqual(aggregate["measured_cost"]["unmeasured_worker_rss_phases"], ["bootstrap"])
            self.assertGreater(aggregate["measured_cost"]["worker_wall_seconds"], 0)
            resumed = self.refused_resume(run, args)
            self.assertEqual(resumed["training_attempts"], 0)
            self.assertEqual(resumed["measured_cost"]["worker_wall_seconds"],
                             aggregate["measured_cost"]["worker_wall_seconds"])

    def test_failed_worker_cannot_be_promoted_by_editing_the_summary(self):
        with self.fixture('receipt["result"]["engineering_passed"] = False\n') as (run, args):
            with self.assertRaisesRegex(RuntimeError, "did not pass"):
                run_loop.main(args)

            def forge(row):
                row["status"] = "completed"
                row["result"]["engineering_passed"] = True
                row.pop("receipt_validation_error", None)

            self.rewrite(run, forge)
            self.refused_resume(run, args)

    def test_boolean_and_unknown_exit_codes_cannot_certify_completion(self):
        for exit_code in (False, None, 1, -9, 0.0):
            with self.subTest(exit_code=exit_code), self.fixture() as (run, args):
                run_loop.main(args)
                self.rewrite(run, lambda row: row["parent_observed"].update(returncode=exit_code))
                self.refused_resume(run, args)

    def test_saved_result_cannot_diverge_from_original_worker_output(self):
        changes = (
            lambda row: row["result"].update(typed_output=[{"correct": True, "value": 2}]),
            lambda row: row["result"]["typed_output"][0].update(correct=1),
            lambda row: row.update(process_instance_id="f" * 32),
            lambda row: row.update(protocol_sha256="0" * 64),
        )
        for index, change in enumerate(changes):
            with self.subTest(change=index), self.fixture() as (run, args):
                run_loop.main(args)
                self.rewrite(run, change)
                self.refused_resume(run, args)

    def test_capture_tampering_or_loss_prevents_resume(self):
        for stream in ("stdout", "stderr"):
            for missing in (False, True):
                with self.subTest(stream=stream, missing=missing), self.fixture() as (run, args):
                    run_loop.main(args)
                    path = run / "attempts/bootstrap" / (stream + ".txt")
                    if missing:
                        path.unlink()
                    else:
                        path.write_bytes(path.read_bytes() + b" ")
                    self.refused_resume(run, args)

    def test_unreadable_receipt_is_preserved_as_unknown_cost(self):
        with self.fixture() as (run, args):
            run_loop.main(args)
            path = run / "phase_results/bootstrap.json"
            path.write_bytes(b'{"status":')
            failed = self.refused_resume(run, args)
            self.assertEqual(path.read_bytes(), b'{"status":')
            self.assertIsNone(failed["measured_cost"]["worker_cpu_user_seconds"])
            self.assertIsNone(failed["measured_cost"]["worker_wall_seconds"])

    def test_invalid_parent_cost_is_unknown_in_the_failure_aggregate(self):
        for value in (False, -1, "unknown", 10 ** 400):
            with self.subTest(value=value), self.fixture() as (run, args):
                run_loop.main(args)
                self.rewrite(run, lambda row: row["parent_observed"].update(cpu_user_seconds=value))
                failed = self.refused_resume(run, args)
                self.assertIsNone(failed["measured_cost"]["worker_cpu_user_seconds"])

    def test_receipt_summary_rechecks_unvisited_phase_outputs(self):
        with self.fixture() as (run, args):
            run_loop.main(args)
            forged = read(run / "phase_results/bootstrap.json")
            forged["phase"] = "feedback"
            write(run / "phase_results/feedback.json", forged)
            args.resume = True
            with patch.object(run_loop.subprocess, "run") as launch:
                with self.assertRaisesRegex(ValueError, "no implicit retry"):
                    run_loop.main(args)
                launch.assert_not_called()
            failed = read(run / "FAILED-02.json")
            self.assertFalse(failed["engineering_passed"])
            self.assertEqual(failed["completed_phases"], ["bootstrap"])
            self.assertEqual(set(failed["unverified_phase_receipts"]), {"feedback"})

    def test_incomplete_attempt_is_not_relaunched(self):
        with self.fixture() as (run, args):
            run_loop.main(args)
            (run / "phase_results/bootstrap.json").unlink()
            self.refused_resume(run, args)

    def test_training_marker_survives_missing_attempt_receipts(self):
        with self.fixture(phases=("train", "fence")) as (run, args):
            run_loop.main(args)
            write(run / "TRAINING_STARTED.json", {"engineering_fixture": True})
            (run / "phase_results/train.json").unlink()
            shutil.rmtree(run / "attempts/train")
            failed = self.refused_resume(run, args, phase="train")
            self.assertEqual(failed["training_attempts"], 1)

    def test_wrong_phase_identity_or_ambiguous_json_is_never_completed(self):
        edits = ('receipt["phase"] = "feedback"\n', 'del receipt["process_instance_id"]\n',
                 'receipt["pid"] = True\n', 'receipt["parent_observed"] = {}\n')
        for edit in edits:
            with self.subTest(edit=edit), self.fixture(edit) as (run, args):
                with self.assertRaisesRegex(RuntimeError, "did not pass"):
                    run_loop.main(args)
                self.refused_resume(run, args)
        for output in ('[]', '{"status":"failed","status":"completed"}', '{"value":NaN}'):
            with self.subTest(output=output), self.fixture(emit="print(" + repr(output) + ")\n") as (run, args):
                with self.assertRaisesRegex(RuntimeError, "did not pass"):
                    run_loop.main(args)
                self.refused_resume(run, args)


if __name__ == "__main__":
    unittest.main()
