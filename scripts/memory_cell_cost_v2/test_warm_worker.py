"""Pure source/measurement controls; no real benchmark or model is executed."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from warm_worker import GENERATION_LIMITS, GenerationGuard, sample_loop, source_query


class Shape:
    def __init__(self, *values):
        self.shape = values


class WarmTests(unittest.TestCase):
    def generate_arguments(self, prompt=78, output=16):
        return {
            "input_ids": Shape(1, prompt),
            "attention_mask": Shape(1, prompt),
            "max_new_tokens": output,
        }

    def test_twenty_first_actual_call_is_refused_without_invoking_decoder(self):
        calls, events = [], []

        def generate(**kwargs):
            calls.append(kwargs)
            return Shape(1, kwargs["input_ids"].shape[1] + 16)

        guard = GenerationGuard(
            generate, GENERATION_LIMITS, lambda: {"index": 0}, events.append
        )
        for _ in range(20):
            guard(**self.generate_arguments())
        with self.assertRaises(ValueError):
            guard(**self.generate_arguments())
        self.assertEqual(
            (len(calls), guard.calls, guard.input_tokens, guard.output_tokens),
            (20, 20, 1560, 320),
        )
        self.assertEqual(sum(r["event"] == "decoder_started" for r in events), 20)

    def test_prompt_and_output_setting_rejected_before_real_invocation(self):
        calls = []

        def generate(**kwargs):
            calls.append(kwargs)
            return Shape(1, 1)

        for prompt, output in ((193, 16), (0, 16), (78, 17), (78, True)):
            with self.subTest(prompt=prompt, output=output):
                guard = GenerationGuard(
                    generate, GENERATION_LIMITS, dict, lambda row: None
                )
                with self.assertRaises(ValueError):
                    guard(**self.generate_arguments(prompt, output))
                self.assertEqual(guard.calls, 0)
        self.assertEqual(calls, [])
        with self.assertRaises(ValueError):
            GenerationGuard(generate, dict(GENERATION_LIMITS, calls=21), dict)

    def test_oversized_return_is_retained_then_closes_guard(self):
        calls, events = [], []

        def generate(**kwargs):
            calls.append(kwargs)
            return Shape(1, 95)

        guard = GenerationGuard(generate, GENERATION_LIMITS, dict, events.append)
        with self.assertRaisesRegex(ValueError, "output exceeds"):
            guard(**self.generate_arguments())
        self.assertEqual((len(calls), guard.calls, guard.output_tokens), (1, 1, 17))
        self.assertFalse(events[-1]["within_frozen_output_budget"])
        with self.assertRaises(ValueError):
            guard(**self.generate_arguments())
        self.assertEqual(len(calls), 1)

    def test_decoder_failure_keeps_spent_call_and_start_marker(self):
        events = []

        def generate(**kwargs):
            raise RuntimeError("controlled decoder error")

        guard = GenerationGuard(generate, GENERATION_LIMITS, dict, events.append)
        with self.assertRaises(RuntimeError):
            guard(**self.generate_arguments())
        self.assertEqual((guard.calls, guard.input_tokens, guard.closed), (1, 78, True))
        self.assertEqual([r["event"] for r in events], ["decoder_started"])

    def test_source_outcomes_are_used_and_drift_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = []
            for code, codes in (("A", (0, 0)), ("B", (1, 0))):
                row = {
                    "code": code,
                    "outcomes": {
                        op: {
                            phase: {"returncode": rc}
                            for phase in ("action", "after", "semantic")
                        }
                        for op, rc in zip(("operation-one", "operation-two"), codes)
                    },
                }
                raw = json.dumps(row).encode()
                path = root / code
                path.write_bytes(raw)
                sources.append(
                    {
                        "path": str(path),
                        "bytes": len(raw),
                        "sha256": hashlib.sha256(raw).hexdigest(),
                    }
                )
            request = {
                "sources": sources,
                "operations": ["operation-one", "operation-two"],
            }
            self.assertEqual(
                source_query(request, {"codes": ["A"]})["text"], "operation-one"
            )
            self.assertEqual(
                source_query(request, {"codes": ["A", "B"]})["text"], "operation-two"
            )
            with self.assertRaises(ValueError):
                source_query(request, {"codes": ["unknown"]})
            (root / "A").write_text("drift")
            with self.assertRaises(ValueError):
                source_query(request, {"codes": ["A"]})

    def test_failure_retains_started_sample_and_stops_without_retry(self):
        jobs = [dict(phase="measured", index=i, query_id=str(i)) for i in range(3)]
        events, calls = [], []

        def query(job):
            calls.append(job["index"])
            if job["index"] == 1:
                raise RuntimeError("controlled query failure")
            return {"text": "unscored result"}

        self.assertFalse(sample_loop(jobs, query, events.append))
        self.assertEqual(calls, [0, 1])
        self.assertEqual(
            [r["event"] for r in events],
            ["query_started", "sample", "query_started", "sample"],
        )
        self.assertFalse(events[-1]["success"])
        self.assertIn("controlled query failure", events[-1]["error"])
        self.assertEqual(
            events[-1]["end_ns"] - events[-1]["start_ns"], events[-1]["wall_ns"]
        )


if __name__ == "__main__":
    unittest.main()
