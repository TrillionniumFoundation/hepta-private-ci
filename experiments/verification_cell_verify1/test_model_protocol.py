import json
import tempfile
from pathlib import Path
import unittest

from .model_protocol import Journal, cases, messages, public_view


class ProtocolTests(unittest.TestCase):
    def test_every_hidden_fault_has_identical_initial_model_input(self):
        prompts = {json.dumps(messages(public_view([]), "neutral"), sort_keys=True)
                   for split in ("train", "calibration", "confirmation") for _ in cases(split)}
        self.assertEqual(len(prompts), 1)
        for field in ("fault", "goal", "task_id", "source_group", "oracle", "worker_wall_ns"):
            value = public_view([True])
            value[field] = "hidden"
            with self.assertRaises(ValueError):
                messages(value, "neutral")

    def test_ack_boundary_rejects_coercion_and_inconsistent_step(self):
        for value in ([1], [None], ["false"], [True] * 4, {"ack": True}):
            with self.assertRaises(ValueError):
                public_view(value)
        invalid = public_view([True])
        invalid["tick"] = True
        with self.assertRaises(ValueError):
            messages(invalid, "neutral")

    def test_failed_attempt_and_cost_are_retained_no_output_reuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            for error, status in ((RuntimeError, "failed"), (KeyboardInterrupt, "cancelled")):
                target = Path(temporary) / status
                journal = Journal(target, {"frozen": True})
                with self.assertRaises(error):
                    with journal.operation("real_forward", {"case": "x"}):
                        journal.consume(assessments=1, forward_passes=1, input_tokens=10)
                        raise error("GPU failure")
                receipt = json.loads((target / "operations.jsonl").read_text())
                self.assertEqual(receipt["status"], status)
                self.assertEqual(receipt["counters"], {"assessments": 1, "forward_passes": 1, "input_tokens": 10})
                with self.assertRaises(FileExistsError):
                    Journal(target, {})

if __name__ == "__main__":
    unittest.main()
