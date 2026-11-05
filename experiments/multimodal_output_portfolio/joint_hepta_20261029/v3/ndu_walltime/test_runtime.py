"""Actual waited-process contract qualification, not frozen-LLM evaluation."""

import json
import math
from pathlib import Path
import sys
import tempfile
import time
import unittest

from .runtime import Contract, Worker, canonical, digest, run_episode


IDENTITY = {"kind": "validation_fixture", "model_id": "scripted-process-contract",
            "revision": "qualification-v1"}
RECORDS = []


def worker(code, fee=0.01):
    return Worker((sys.executable, "-c", code), fee)


STOP = worker('print(\'{"action":"STOP","payload":7}\')')
VERIFIER = worker('import json,sys; x=json.load(sys.stdin); '
                  'print(json.dumps({"quality":float(x["answer"]==7)}))', 0.03)


class Qualification(unittest.TestCase):
    def run_case(self, name, controller=STOP, tools=None, verifier=VERIFIER,
                 contract=Contract(), cancelled=lambda: False):
        result = run_episode({"task_id": name}, controller, tools or {}, verifier,
                             IDENTITY, contract, cancelled)
        RECORDS.append({"case": name, "record": result})
        self.assertEqual(result["scientific_status"], "NOT_LLM_EVIDENCE")
        self.assertGreaterEqual(result["wall_seconds"], result["setup_wall_seconds"])
        self.assertGreaterEqual(result["wall_seconds"],
                                math.fsum(e["wall_seconds"] for e in result["events"]))
        self.assertAlmostEqual(result["net_utility"], result["delivered_quality"]
                               - result["attempt_fees"]
                               - contract.time_price*result["wall_seconds"], places=14)
        return result

    def test_explicit_stop_delivers_and_charges_envelope_once(self):
        result = self.run_case("delivery")
        self.assertEqual(result["termination"], "delivered")
        self.assertEqual(result["delivered_quality"], 1.0)
        self.assertAlmostEqual(result["attempt_fees"], 0.04)
        self.assertEqual([e["role"] for e in result["events"]], ["controller", "verifier"])

    def test_failed_probe_is_paid_and_observed_before_delivery(self):
        controller = worker('import json,sys; x=json.load(sys.stdin); '
            'h=x["history"]; '
            'a={"action":"probe","payload":None} if not h else '
            '{"action":"STOP","payload":7 if h[0]["status"]=="nonzero_exit" else 0}; '
            'print(json.dumps(a))')
        result = self.run_case("failed_probe", controller,
                               {"probe":worker('raise SystemExit(3)', 0.2)})
        self.assertEqual(result["termination"], "delivered")
        self.assertEqual(result["delivered_quality"], 1.0)
        self.assertAlmostEqual(result["attempt_fees"], 0.25)
        self.assertEqual(len(result["events"]), 4)

    def test_no_stop_never_delivers(self):
        controller = worker('print(\'{"action":"probe","payload":null}\')')
        result = self.run_case("no_stop", controller,
            {"probe":worker('print(\'{"answer":7}\')')}, contract=Contract(max_decisions=1))
        self.assertEqual((result["termination"], result["delivered_quality"]), ("decision_limit",0.0))
        self.assertFalse(result["stop_requested"])
        self.assertAlmostEqual(result["attempt_fees"], 0.02)

    def test_late_stop_gets_no_quality_and_retains_cost(self):
        controller = worker('import time; time.sleep(0.3); '
                            'print(\'{"action":"STOP","payload":7}\')', 0.2)
        result = self.run_case("late_stop", controller,
                              contract=Contract(deadline_seconds=0.08, call_timeout_seconds=1.0))
        self.assertEqual(result["termination"], "controller_timeout")
        self.assertTrue(result["deadline_missed"])
        self.assertEqual(result["delivered_quality"], 0)
        self.assertAlmostEqual(result["attempt_fees"], 0.2)
        self.assertGreater(result["wall_seconds"], 0.07)

    def test_verification_time_is_inside_delivery_deadline(self):
        verifier = worker('import time; time.sleep(0.3); print(\'{"quality":1}\')', 0.2)
        result = self.run_case("late_verifier", verifier=verifier,
                              contract=Contract(deadline_seconds=0.15, call_timeout_seconds=1.0))
        self.assertEqual(result["termination"], "verifier_timeout")
        self.assertTrue(result["stop_requested"])
        self.assertEqual(result["delivered_quality"], 0)
        self.assertAlmostEqual(result["attempt_fees"], 0.21)

    def test_malformed_controller_keeps_attempt_fee(self):
        result = self.run_case("bad_json", worker('print("not JSON")', 0.1))
        self.assertEqual(result["termination"], "controller_invalid_output_or_launch")
        self.assertAlmostEqual(result["attempt_fees"], 0.1)

    def test_overflowing_json_number_keeps_paid_receipt(self):
        result = self.run_case("overflow_number",
            worker('print(\'{"action":"STOP","payload":{"nested":1e999}}\')', 0.2))
        self.assertEqual(result["termination"], "controller_invalid_output_or_launch")
        self.assertAlmostEqual(result["attempt_fees"], 0.2)
        self.assertEqual(len(result["events"]), 1)

    def test_stderr_flood_cannot_turn_small_stdout_into_delivery(self):
        # Original code checked stdout after unbounded communicate() and did not
        # enforce any limit on stderr: this printed valid STOP plus 128 KiB
        # stderr and incorrectly delivered the answer under a 1 KiB budget.
        controller = worker(
            'import sys; print(\'{"action":"STOP","payload":7}\'); '
            'sys.stderr.buffer.write(b"E"*131072)', 0.13)
        result = self.run_case(
            "stderr_flood", controller,
            contract=Contract(deadline_seconds=6.0, call_timeout_seconds=5.0,
                              max_output_bytes=1024))
        self.assertEqual(result["termination"], "controller_oversized_output")
        self.assertEqual(result["delivered_quality"], 0)
        self.assertAlmostEqual(result["attempt_fees"], 0.13)
        self.assertLessEqual(result["events"][0]["capture_bytes_observed_at_abort"], 1025)

    def test_stdout_flood_aborts_without_unbounded_capture(self):
        controller = worker(
            'import sys; sys.stdout.buffer.write(b"X"*131072)', 0.11)
        result = self.run_case(
            "stdout_flood", controller,
            contract=Contract(deadline_seconds=6.0, call_timeout_seconds=5.0,
                              max_output_bytes=1024))
        self.assertEqual(result["termination"], "controller_oversized_output")
        self.assertEqual(result["delivered_quality"], 0)
        self.assertAlmostEqual(result["attempt_fees"], 0.11)
        self.assertLessEqual(result["events"][0]["capture_bytes_observed_at_abort"], 1025)

    def test_non_utf8_worker_keeps_paid_receipt(self):
        result = self.run_case("non_utf8", worker('import sys; sys.stdout.buffer.write(bytes([255]))', .2))
        self.assertEqual(result["termination"], "controller_invalid_output_or_launch")
        self.assertAlmostEqual(result["attempt_fees"], .2)

    def test_deep_json_keeps_paid_receipt(self):
        result = self.run_case("deep_json", worker(
            'print(\'{"action":"STOP","payload":\'+"["*12000+"0"+"]"*12000+"}")', .2))
        self.assertEqual(result["termination"], "controller_invalid_output_or_launch")
        self.assertAlmostEqual(result["attempt_fees"], .2)

    def test_timeout_kills_worker_descendant_before_it_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory)/"late-write"
            child = 'import time,pathlib; time.sleep(.25); pathlib.Path('+repr(str(marker))+').write_text("late")'
            parent = 'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c",'+repr(child)+']); time.sleep(1)'
            result = self.run_case("descendant_timeout", worker(parent),
                                  contract=Contract(deadline_seconds=.08))
            self.assertEqual(result["termination"], "controller_timeout")
            time.sleep(.3)
            self.assertFalse(marker.exists())

    def test_invalid_verifier_cannot_create_reward(self):
        result = self.run_case("bad_verifier", verifier=worker('print(\'{"quality":true}\')'))
        self.assertEqual(result["termination"], "invalid_verifier")
        self.assertEqual(result["delivered_quality"], 0)

    def test_duplicate_controller_action_cannot_override_admission(self):
        # Python's permissive JSON decoder otherwise chooses the final action,
        # turning a deliberately ambiguous tool request into a valid STOP.
        controller = worker('print(\'{"action":"probe","action":"STOP","payload":7}\')', 0.07)
        result = self.run_case("duplicate_controller_action", controller)
        self.assertEqual(result["termination"], "controller_invalid_output_or_launch")
        self.assertEqual(result["delivered_quality"], 0.0)
        self.assertAlmostEqual(result["attempt_fees"], 0.07)

    def test_nested_duplicate_controller_key_is_rejected(self):
        controller = worker(
            'print(\'{"action":"STOP","payload":{"key":0,"key":7}}\')', 0.07)
        result = self.run_case("nested_duplicate", controller)
        self.assertEqual(result["termination"], "controller_invalid_output_or_launch")
        self.assertEqual(result["delivered_quality"], 0.0)
        self.assertAlmostEqual(result["attempt_fees"], 0.07)

    def test_duplicate_verifier_quality_cannot_create_reward(self):
        verifier = worker('print(\'{"quality":0,"quality":1}\')', 0.09)
        result = self.run_case("duplicate_verifier_quality", verifier=verifier)
        self.assertEqual(result["termination"], "verifier_invalid_output_or_launch")
        self.assertEqual(result["delivered_quality"], 0.0)
        self.assertAlmostEqual(result["attempt_fees"], 0.10)

    def test_cancellation_after_model_call_keeps_fee_without_delivery(self):
        counter = iter([False, True])
        result = self.run_case("cancel_after_call", cancelled=lambda:next(counter))
        self.assertEqual(result["termination"], "cancelled")
        self.assertEqual(len(result["events"]), 1)
        self.assertAlmostEqual(result["attempt_fees"], 0.01)

    def test_illegal_action_cannot_execute(self):
        result = self.run_case("illegal_action", worker('print(\'{"action":"new_tool","payload":7}\')'))
        self.assertEqual(result["termination"], "invalid_action")
        self.assertEqual(len(result["events"]), 1)

    def test_nonfinite_tariff_and_unfrozen_identity_are_rejected(self):
        with self.assertRaises(ValueError):
            run_episode({}, STOP, {}, VERIFIER, IDENTITY, Contract(time_price=float("nan")))
        with self.assertRaises(ValueError):
            run_episode({}, STOP, {}, VERIFIER, {**IDENTITY, "revision":"latest"})


if __name__ == "__main__":
    import argparse
    import hashlib
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    target = Path(args.output)
    if target.exists():
        raise SystemExit("Refusing to overwrite prior qualification evidence")
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Qualification)
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    sources = {p.name:hashlib.sha256(p.read_bytes()).hexdigest()
               for p in Path(__file__).parent.glob("*.py")}
    payload = {"schema":"ndu.measured-clock.qualification.v1", "source_sha256":sources,
               "tests_run":outcome.testsRun, "tests_passed":outcome.wasSuccessful(),
               "frozen_llm_execution":"NOT_RUN_NO_MODEL_OR_ENDPOINT",
               "records":RECORDS, "case_record_sha256":digest(RECORDS)}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(canonical(payload)+"\n")
    raise SystemExit(0 if outcome.wasSuccessful() else 1)
