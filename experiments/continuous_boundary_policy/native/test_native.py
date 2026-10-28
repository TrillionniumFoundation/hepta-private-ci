"""Behavioral protocol validation against the actual original NDU executable."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import time
import unittest

from .bridge import MAX_BYTES, Q, ScoreBridge, digest

BINARY = None
ROOT = None
COSTS = []


def row(identifier="case.0", scores=(Q, -Q, 0)):
    return {
        "row_id": identifier,
        "model_sha256": digest("model"),
        "objective_sha256": digest("objective"),
        "observation_sha256": digest("observation"),
        "state_sha256": digest("state"),
        "scores_q24": list(scores),
    }


class NativeScoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = ROOT / self.id().split(".")[-1]
        self.directory.mkdir()
        self.bridges = []

    def bridge(self, suffix="host"):
        host = ScoreBridge(BINARY, self.directory / suffix)
        self.bridges.append(host)
        return host

    def tearDown(self):
        for bridge in self.bridges:
            receipt = bridge.close()
            self.assertEqual(receipt["exit_code"], 0)
            self.assertIsNone(receipt["shutdown_error"])
            self.assertGreaterEqual(receipt["completed_child_cpu_seconds"], 0)
            self.assertEqual(receipt["actual_kernel_calls"], 0)
            self.assertGreater(receipt["request_bytes"], 0)
            self.assertGreater(receipt["response_bytes"], 0)
            COSTS.append(receipt)

    def test_real_ndu_extrema_and_all_tie_forms(self):
        host = self.bridge()
        scores = [
            (8 * Q, -8 * Q, 0),
            (-8 * Q, 8 * Q, 0),
            (-8 * Q, -8 * Q, 0),
            (0, 0, 0),
            (Q, Q, 0),
            (0, -Q, 0),
            (-Q, 0, 0),
            (1, 0, 0),
            (0, 1, 0),
        ]
        expected = [
            "keep",
            "repair",
            "stop",
            "stop",
            "repair",
            "stop",
            "stop",
            "keep",
            "repair",
        ]
        result = host.decide_batch(
            [row(f"case.{i}", value) for i, value in enumerate(scores)]
        )
        self.assertEqual([value["action"] for value in result["rows"]], expected)
        self.assertEqual(
            [value["tie"] for value in result["rows"]],
            [False, False, False, True, True, True, True, False, False],
        )
        self.assertEqual(result["actual_ndu_calls"], len(scores))
        self.assertEqual(result["actual_kernel_calls"], 0)
        self.assertTrue(
            all(
                value["actual_ndu_calls"] == 1 and value["actual_kernel_calls"] == 0
                for value in result["rows"]
            )
        )
        (self.directory / "receipts.json").write_text(
            json.dumps(result, indent=2) + "\n"
        )

    def test_invalid_whole_batches_execute_no_ndu_and_leave_valid_result_unchanged(
        self,
    ):
        host = self.bridge()
        good = row()
        original = host.decide_batch([good])["rows"][0]
        bad_rows = []
        for key, value in [
            ("scores_q24", [Q, 0, 1]),
            ("scores_q24", [8 * Q + 1, 0, 0]),
            ("scores_q24", [Q, 0]),
            ("scores_q24", [1.5, 0, 0]),
            ("scores_q24", [True, 0, 0]),
            ("model_sha256", "0" * 64),
            ("state_sha256", "A" * 64),
            ("observation_sha256", "g" * 64),
            ("objective_sha256", "a" * 63),
            ("row_id", ""),
            ("row_id", "a" * 257),
            ("row_id", "a b"),
            ("undeclared", True),
        ]:
            value_row = copy.deepcopy(good)
            value_row["row_id"] = "bad"
            value_row[key] = value
            bad_rows.append([good, value_row])
        missing = copy.deepcopy(good)
        del missing["model_sha256"]
        bad_rows.extend(
            [[missing], [], [good, good], [row(str(i)) for i in range(4097)]]
        )
        before = host.counters["actual_ndu_calls"]
        for invalid in bad_rows:
            response = host.rpc(
                {"command": "DecideBatch", "rows": invalid}, allow_error=True
            )
            self.assertFalse(response["ok"])
        for request in [
            {"command": "Identity", "extra": True},
            {"command": "Shutdown", "extra": True},
            {"command": "Unknown"},
        ]:
            self.assertFalse(host.rpc(request, allow_error=True)["ok"])
        self.assertEqual(host.counters["actual_ndu_calls"], before)
        self.assertEqual(host.decide_batch([good])["rows"][0], original)

    def test_each_changed_binding_changes_native_evaluation_and_receipt(self):
        host = self.bridge()
        original = row()
        expected = host.decide_batch([original])["rows"][0]
        for key in (
            "model_sha256",
            "objective_sha256",
            "observation_sha256",
            "state_sha256",
            "scores_q24",
            "row_id",
        ):
            changed = copy.deepcopy(original)
            changed[key] = (
                [Q + 1, -Q, 0]
                if key == "scores_q24"
                else "different"
                if key == "row_id"
                else digest(key)
            )
            received = host.decide_batch([changed])["rows"][0]
            for identity in ("support_sha256", "receipt_sha256", "native_ndu_digest"):
                self.assertNotEqual(received[identity], expected[identity])

    def test_stateless_cold_process_replay_is_exact(self):
        first = self.bridge("first")
        request = [row("cold.1", (Q, Q, 0)), row("cold.2", (-Q, -Q, 0))]
        expected = first.decide_batch(request)
        first.close()
        second = self.bridge("second")
        self.assertEqual(second.decide_batch(request), expected)
        self.assertEqual(first.identity, second.identity)

    def test_oversize_native_line_is_rejected_and_following_request_recovers(self):
        host = self.bridge()
        raw = b" " * (MAX_BYTES + 1) + b"\n"
        started = time.perf_counter_ns()
        host.process.stdin.write(raw)
        host.process.stdin.flush()
        response = host.process.stdout.readline(MAX_BYTES + 1)
        host.counters["python_roundtrip_ns"] += time.perf_counter_ns() - started
        parsed = json.loads(response)
        host.counters["request_bytes"] += len(raw)
        host.counters["response_bytes"] += len(response)
        host.counters["rpc_calls"] += 1
        host.counters["native_errors"] += 1
        host.counters["native_physical_rpc_micros"] += parsed["physical_rpc_micros"]
        self.assertFalse(parsed["ok"])
        self.assertEqual(parsed["error"], "Native request byte limit")
        self.assertEqual(host.rpc({"command": "Identity"}), host.identity)
        self.assertEqual(host.decide_batch([row()])["actual_ndu_calls"], 1)


def main():
    global BINARY, ROOT
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    BINARY, ROOT = args.binary.resolve(), args.output_dir.resolve()
    ROOT.mkdir(parents=True, exist_ok=False)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(NativeScoreTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {
        "schema": "hepta.boundary-policy.native-score-tests.v1",
        "binary_sha256": hashlib.sha256(BINARY.read_bytes()).hexdigest(),
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "success": result.wasSuccessful(),
        "process_costs": COSTS,
        "source_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(Path(__file__).parent.iterdir())
            if path.suffix in (".py", ".rs")
        },
    }
    (ROOT / "TESTS.json").write_text(json.dumps(report, indent=2) + "\n")
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
