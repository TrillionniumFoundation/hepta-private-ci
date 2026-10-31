"""Actual Linux-process recovery, concurrency, accounting and state qualification."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import unittest

ZERO = "0" * 64
RUNS = []
BINARY = None
OUTPUT = None


def fixture():
    return {"schema": "hepta.fpt.owner-adoption.v2", "sequence": 1, "predecessor": ZERO,
            "config": {"run_id": "fpt.v2.fixture", "objective_digest": "1" * 64,
                       "artifact_digest": "2" * 64,
                       "model": {"drift": -0.45, "weights": [0.0, 0.0], "interaction": 0.0,
                                 "sigma": 0.3, "cancel_rate": 0.0, "barrier": 0.0,
                                 "reset_gap": 0.9, "refractory_us": 60000},
                       "deadline_us": 1000000, "read_budget": 4,
                       "credit": {"initial_micros": 0, "maximum_micros": 2000000,
                                  "step_micros": 800000, "target_quarters": 1,
                                  "maximum_read_price_micros": 2000000}},
            "checkpoint": {"level": 1.0, "time_us": 0, "phase": {"kind": "Active"},
                           "events": 0, "rng_seed": 17, "rng_counter": 0,
                           "cancellation": {"seed": 19, "counter": 0, "at_us": None}},
            "hit_times_us": [], "owner_monotonic_us": 1, "expected_price_micros": 0, "expected_price_residue": 0,
            "ndu_receipt_digest": "3" * 64,
            "features_q24": [8388608, 0, 0, 0, 0],
            "action": {"kind": "Read", "relative_path": "chunk.txt", "query": "needle"}}


def successor(request, receipt):
    value = copy.deepcopy(request)
    value.update(sequence=request["sequence"] + 1, predecessor=receipt["record"]["digest"],
                 owner_monotonic_us=request["owner_monotonic_us"] + 1,
                 expected_price_micros=receipt["record"]["body"]["price_after_micros"],
                 expected_price_residue=receipt["record"]["body"]["price_after_residue"])
    return value


def invoke(directory, request, point=None):
    args = [str(BINARY), "--store", str(directory / "owner"), "--data-root", str(directory / "data")]
    marker = directory / ("pause-" + point) if point else None
    if point:
        args += ["--pause-at", point, "--pause-marker", str(marker)]
    started = time.monotonic()
    process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    process.stdin.write(json.dumps(request).encode())
    process.stdin.close()
    process.stdin = None
    if point:
        deadline = time.monotonic() + 10
        while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        if not marker.exists():
            out, err = process.communicate(timeout=1)
            raise AssertionError((point, process.returncode, out, err))
        return process, args, started
    out, err = process.communicate(timeout=10)
    row = {"args": args, "request": request, "returncode": process.returncode,
           "stdout": out.decode(), "stderr": err.decode(), "wall_seconds": time.monotonic() - started}
    RUNS.append(row)
    return process.returncode, json.loads(out)


def kill_probe(process, args, started, request):
    process.send_signal(signal.SIGKILL)
    out, err = process.communicate(timeout=3)
    RUNS.append({"args": args, "request": request, "returncode": process.returncode,
                 "stdout": out.decode(), "stderr": err.decode(), "signal": "SIGKILL",
                 "wall_seconds": time.monotonic() - started})
    if process.returncode != -signal.SIGKILL:
        raise AssertionError("probe did not die from real SIGKILL")


def inventory(directory):
    return {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.rglob("*") if p.is_file()}


class OwnerQualification(unittest.TestCase):
    def setUp(self):
        self.directory = OUTPUT / self._testMethodName
        self.directory.mkdir()
        (self.directory / "data").mkdir()
        (self.directory / "data/chunk.txt").write_text("needle=verified answer\n")

    def success(self, request, directory=None):
        code, row = invoke(directory or self.directory, request)
        self.assertEqual(code, 0, row)
        return row

    def denied(self, request, reason, directory=None):
        directory = directory or self.directory
        before = inventory(directory / "owner") if (directory / "owner").exists() else None
        code, row = invoke(directory, request)
        self.assertNotEqual(code, 0)
        self.assertIn(reason, row["error"])
        if before is not None:
            self.assertEqual(inventory(directory / "owner"), before)

    def test_real_owner_read_replay_and_credit(self):
        request = fixture()
        first = self.success(request)
        body = first["record"]["body"]
        self.assertEqual((body["attempts"], body["total_spent"], body["price_after_micros"]), (1, 1, 800000))
        self.assertEqual(body["observation"]["answer"], "verified answer")
        self.assertNotEqual(body["native"]["after"], ZERO)
        before = inventory(self.directory / "owner")
        replay = self.success(request)
        self.assertEqual(replay["record"], first["record"])
        self.assertEqual((replay["new_attempts"], replay["replayed"]), (0, True))
        self.assertEqual(inventory(self.directory / "owner"), before)
        next_request = successor(request, first)
        next_request["action"] = {"kind": "Stop"}
        stopped = self.success(next_request)
        self.assertEqual(stopped["record"]["body"]["terminal"], "Stopped")
        self.denied(successor(next_request, stopped), "terminal task")
        self.assertEqual(self.success(request)["record"], first["record"])

    def test_joint_result_and_credit_survive_cold_process(self):
        request = fixture()
        first = self.success(request)
        second = successor(request, first)
        row = self.success(second)
        self.assertEqual(row["record"]["body"]["price_before_micros"], 800000)
        self.assertEqual(row["record"]["body"]["price_after_micros"], 1600000)
        self.assertEqual(row["record"]["body"]["total_spent"], 2)
        self.assertEqual(self.success(second)["record"], row["record"])

    def test_immutable_physics_and_clock(self):
        request = fixture()
        first = self.success(request)
        next_request = successor(request, first)
        for label, change in [
            ("sigma", lambda r: r["config"]["model"].update(sigma=0.4)),
            ("price", lambda r: r["config"]["credit"].update(step_micros=900000)),
            ("budget", lambda r: r["config"].update(read_budget=100)),
            ("rng", lambda r: r["checkpoint"].update(rng_seed=18)),
            ("cancel", lambda r: r["checkpoint"]["cancellation"].update(seed=20)),
        ]:
            with self.subTest(label=label):
                candidate = copy.deepcopy(next_request)
                change(candidate)
                self.denied(candidate, "immutable")
        candidate = copy.deepcopy(next_request)
        candidate["checkpoint"]["rng_counter"] = 1
        self.denied(candidate, "continuation")

    def test_typed_state_rejects_invalid_phase_and_extra_fields(self):
        for label, change in [
            ("level", lambda r: r["checkpoint"].update(level=0.0)),
            ("phase", lambda r: r["checkpoint"].update(phase={"kind": "Refractory", "until_us": 70000})),
            ("genesis_refractory", lambda r: r["checkpoint"].update(level=0.9, phase={"kind": "Refractory", "until_us": 50})),
            ("rate", lambda r: r["config"]["model"].update(cancel_rate=0.2)),
            ("unknown", lambda r: r["checkpoint"].update(unknown=1)),
        ]:
            with self.subTest(label=label):
                case = self.directory / label
                case.mkdir(); (case / "data").mkdir()
                request = fixture(); change(request)
                code, result = invoke(case, request)
                self.assertNotEqual(code, 0, result)
                self.assertFalse(list((case / "owner").glob("dispatch-*")))

    def test_reset_refractory_release_and_rng_continuation(self):
        request = fixture(); request["action"] = {"kind": "Wait"}
        first = self.success(request)
        second = successor(request, first)
        second["hit_times_us"] = [5]
        second["checkpoint"].update(time_us=10, level=0.9, events=1, rng_counter=1,
                                     phase={"kind": "Refractory", "until_us": 60005})
        row = self.success(second)
        third = successor(second, row); third["hit_times_us"] = []
        third["checkpoint"]["time_us"] = 20
        third["action"] = fixture()["action"]
        self.denied(third, "refractory holding")
        third["checkpoint"].update(time_us=60005, phase={"kind": "Active"})
        released = self.success(third)
        self.assertEqual(released["new_attempts"], 1)
        self.assertEqual(released["record"]["body"]["request"]["checkpoint"]["events"], 1)

    def test_physical_cancellation_is_distinct_from_resource_price(self):
        request = fixture()
        request["config"]["model"]["cancel_rate"] = 0.5
        request["checkpoint"]["cancellation"].update(at_us=50, counter=1)
        first = self.success(request)
        next_request = successor(request, first)
        next_request["checkpoint"].update(time_us=50, rng_counter=1)
        row = self.success(next_request)
        self.assertEqual((row["new_attempts"], row["record"]["body"]["terminal"]), (0, "Cancelled"))
        self.assertEqual(row["record"]["body"]["request"]["config"]["model"]["cancel_rate"], 0.5)

    def test_cancellation_terminates_inside_refractory(self):
        request = fixture(); request["action"] = {"kind": "Wait"}
        request["config"]["model"]["cancel_rate"] = 0.5
        request["checkpoint"]["cancellation"].update(at_us=50, counter=1)
        first = self.success(request)
        second = successor(request, first); second["hit_times_us"] = [5]
        second["checkpoint"].update(time_us=10, level=0.9, events=1, rng_counter=1,
                                     phase={"kind": "Refractory", "until_us": 60005})
        row = self.success(second)
        third = successor(second, row); third["hit_times_us"] = []
        third["checkpoint"]["time_us"] = 50
        third["action"] = fixture()["action"]
        cancelled = self.success(third)
        self.assertEqual((cancelled["new_attempts"], cancelled["record"]["body"]["terminal"]), (0, "Cancelled"))

    def test_failed_opened_read_charged_once(self):
        (self.directory / "data/chunk.txt").write_bytes(b"\xff")
        request = fixture()
        row = self.success(request)
        self.assertEqual((row["new_attempts"], row["record"]["body"]["terminal"]), (1, "ReadFailed"))
        self.assertEqual(row["record"]["body"]["price_after_micros"], 800000)
        self.assertEqual(self.success(request)["new_attempts"], 0)

    def test_budget_prevents_second_read(self):
        request = fixture(); request["config"]["read_budget"] = 1
        row = self.success(request)
        stopped = self.success(successor(request, row))
        self.assertEqual((stopped["new_attempts"], stopped["record"]["body"]["terminal"]), (0, "BudgetExhausted"))

    def test_price_admission_uses_exact_settled_feedback(self):
        request = fixture()
        request["config"]["credit"]["maximum_read_price_micros"] = 1000000
        first = self.success(request)
        second = successor(request, first)
        stale = copy.deepcopy(second); stale["expected_price_micros"] = 0
        self.denied(stale, "stale resource price")
        next_row = self.success(second)
        third = successor(second, next_row)
        blocked = self.success(third)
        self.assertEqual((blocked["new_attempts"], blocked["record"]["body"]["terminal"]), (0, "PriceLimited"))
        self.assertEqual(blocked["record"]["body"]["total_spent"], 2)

    def test_zero_time_wait_cannot_lower_price(self):
        request = fixture(); row = self.success(request)
        for _ in range(5):
            request = successor(request, row); request["action"] = {"kind": "Wait"}
            row = self.success(request)
            body = row["record"]["body"]
            self.assertEqual((body["price_after_micros"], body["price_after_residue"]), (800000, 0))
        request = successor(request, row)
        request["checkpoint"]["time_us"] = 100000
        row = self.success(request)
        body = row["record"]["body"]
        self.assertEqual((body["price_after_micros"], body["price_after_residue"]), (780000, 0))

    def test_physical_time_partition_preserves_exact_credit(self):
        balances = []
        for label, times in [("whole", [11]), ("partitioned", list(range(1, 12)))]:
            case = self.directory / label; case.mkdir(); (case / "data").mkdir()
            (case / "data/chunk.txt").write_text("needle=verified answer\n")
            request = fixture()
            request["config"]["credit"].update(initial_micros=1000, step_micros=7, target_quarters=3)
            request["expected_price_micros"] = 1000
            row = self.success(request, case)
            for timestamp in times:
                request = successor(request, row); request["action"] = {"kind": "Wait"}
                request["checkpoint"]["time_us"] = timestamp
                row = self.success(request, case)
            body = row["record"]["body"]
            balances.append((body["price_after_micros"], body["price_after_residue"]))
        self.assertEqual(balances, [(1006, 3999769), (1006, 3999769)])

    def test_fractional_price_cannot_hide_under_integer_admission_limit(self):
        request = fixture()
        request["config"]["credit"].update(step_micros=1, maximum_read_price_micros=0)
        first = self.success(request)
        second = successor(request, first); second["action"] = {"kind": "Wait"}
        second["checkpoint"]["time_us"] = 500000
        row = self.success(second)
        body = row["record"]["body"]
        self.assertEqual((body["price_after_micros"], body["price_after_residue"]), (0, 3500000))
        third = successor(second, row); third["action"] = fixture()["action"]
        blocked = self.success(third)
        self.assertEqual((blocked["new_attempts"], blocked["record"]["body"]["terminal"]), (0, "PriceLimited"))

    def test_idle_then_endpoint_read_is_invariant_to_explicit_wait(self):
        for initial in [0, 1500000]:
            outcomes = []
            for split in [False, True]:
                case = self.directory / (str(initial) + "-" + str(split))
                case.mkdir(); (case / "data").mkdir()
                (case / "data/chunk.txt").write_text("needle=verified answer\n")
                request = fixture(); request["action"] = {"kind": "Wait"}
                request["config"]["deadline_us"] = 2000000
                request["config"]["credit"].update(initial_micros=initial, step_micros=1000000,
                                                    target_quarters=4, maximum_read_price_micros=1000000)
                request["expected_price_micros"] = initial
                row = self.success(request, case)
                if split:
                    request = successor(request, row)
                    request["checkpoint"]["time_us"] = 1000000
                    row = self.success(request, case)
                request = successor(request, row); request["action"] = fixture()["action"]
                request["checkpoint"]["time_us"] = 1000000
                row = self.success(request, case); body = row["record"]["body"]
                outcomes.append((row["new_attempts"], body["terminal"], body["admission_price_micros"],
                                 body["admission_price_residue"], body["price_after_micros"], body["price_after_residue"]))
            admission = max(0, initial - 1000000)
            expected = (1, None, admission, 0, admission + 1000000, 0)
            self.assertEqual(outcomes, [expected, expected])

    def test_refractory_release_cannot_invent_an_instantaneous_hit(self):
        request = fixture(); request["action"] = {"kind": "Wait"}
        row = self.success(request)
        request = successor(request, row); request["hit_times_us"] = [5]
        request["checkpoint"].update(time_us=10, level=0.9, events=1, rng_counter=1,
                                     phase={"kind": "Refractory", "until_us": 60005})
        row = self.success(request)
        next_request = successor(request, row); next_request["hit_times_us"] = [60005]
        next_request["checkpoint"].update(time_us=60005, events=2,
                                          phase={"kind": "Refractory", "until_us": 120005})
        self.denied(next_request, "event order/refractory")
        next_request["hit_times_us"] = [60006]
        next_request["checkpoint"].update(time_us=60006, rng_counter=2,
                                          phase={"kind": "Refractory", "until_us": 120006})
        accepted = self.success(next_request)
        self.assertEqual(accepted["record"]["body"]["request"]["checkpoint"]["events"], 2)

    def test_nonregular_sources_are_bounded_and_never_opened(self):
        source = self.directory / "data/chunk.txt"
        source.unlink(); os.mkfifo(source)
        row = self.success(fixture())
        self.assertEqual((row["new_attempts"], row["record"]["body"]["terminal"]), (0, "ReadFailed"))
        self.assertIn("nonregular", row["record"]["body"]["observation"]["error"])

    def test_dangling_owner_links_fail_without_following(self):
        for name in ["owner.lock", "native-witness.bin", "native-journal.bin", "prepared-0001.json"]:
            with self.subTest(name=name):
                case = self.directory / name; case.mkdir(); (case / "data").mkdir()
                (case / "owner").mkdir(mode=0o700)
                target = case / "must-not-create"
                (case / "owner" / name).symlink_to(target)
                code, row = invoke(case, fixture())
                self.assertNotEqual(code, 0, row)
                self.assertIn("nonregular", row["error"])
                self.assertFalse(target.exists())

    def test_completed_record_corruption_refuses_native_execution(self):
        request = fixture(); self.success(request)
        (self.directory / "owner/settled-0001.json").write_text('{"digest":')
        self.denied(request, "invalid owner record")

    def test_two_processes_cannot_hold_the_owner(self):
        request = fixture()
        process, args, start = invoke(self.directory, request, "locked")
        try:
            self.denied(request, "Busy")
        finally:
            kill_probe(process, args, start, request)
        row = self.success(request)
        self.assertEqual(row["new_attempts"], 1)

    def test_real_sigkill_recovery_matrix(self):
        for point in ["prepared", "dispatched", "native_committed", "effect_entered",
                      "effect_completed", "record_synced", "published"]:
            with self.subTest(point=point):
                case = self.directory / point
                case.mkdir(); (case / "data").mkdir()
                (case / "data/chunk.txt").write_text("needle=verified answer\n")
                request = fixture()
                process, args, start = invoke(case, request, point)
                kill_probe(process, args, start, request)
                if point == "prepared":
                    row = self.success(request, case)
                    self.assertEqual((row["new_attempts"], row["replayed"]), (1, False))
                elif point == "published":
                    row = self.success(request, case)
                    self.assertEqual((row["new_attempts"], row["replayed"]), (0, True))
                    self.assertEqual(row["record"]["body"]["price_after_micros"], 800000)
                else:
                    self.denied(request, "Indeterminate", case)
                    self.denied(request, "Indeterminate", case)
                    self.assertFalse((case / "owner/settled-0001.json").exists())

    def test_later_unknown_effect_also_fences_historical_replay(self):
        request = fixture()
        first = self.success(request)
        next_request = successor(request, first)
        process, args, start = invoke(self.directory, next_request, "native_committed")
        kill_probe(process, args, start, next_request)
        self.denied(next_request, "Indeterminate")
        self.denied(request, "Indeterminate")
        stored = json.loads((self.directory / "owner/settled-0001.json").read_text())
        self.assertEqual(stored, first["record"])


def main():
    global BINARY, OUTPUT
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    BINARY, OUTPUT = args.binary.resolve(), args.output.resolve()
    OUTPUT.mkdir(parents=True, exist_ok=False)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(OwnerQualification))
    report = {"schema": "hepta.fpt.owner-adoption.process-qualification.v2", "tests_run": result.testsRun,
              "success": result.wasSuccessful(), "failures": len(result.failures), "errors": len(result.errors),
              "failure_details": [str(case) + "\n" + detail for case, detail in result.failures + result.errors],
              "binary_sha256": hashlib.sha256(BINARY.read_bytes()).hexdigest(), "invocations": RUNS,
              "real_sigkill_count": sum(r.get("signal") == "SIGKILL" for r in RUNS),
              "scope": "Linux real native owner, bounded local reads and process crash/replay; no power-loss or production claim",
              "production_activation": False}
    (OUTPUT / "QUALIFICATION.json").write_text(json.dumps(report, indent=2) + "\n")
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
