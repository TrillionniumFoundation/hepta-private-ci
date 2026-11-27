"""Development-only behavior fixtures; no old evaluation panel is replayed."""

from dataclasses import FrozenInstanceError, asdict, replace
import json
import math
import unittest

from .candidate_memory import CandidateMemory, CandidateMemoryError, CandidateScope


SCOPE = CandidateScope("operation-A", "case-A", "a" * 64, 1000, 800)


def observation(text, box=(10, 20, 90, 50), origin="pixel_ocr", value=0.25):
    return {"text": text, "bbox": list(box), "origin": origin}, [value] * 126


def observe(memory, step, values, scope=SCOPE):
    return memory.observe(scope, step, [v[0] for v in values], [v[1] for v in values])


class CandidateMemoryTests(unittest.TestCase):
    def test_overview_candidate_survives_roi_and_current_duplicate_refreshes(self):
        memory = CandidateMemory(max_entries=3, max_serialized_bytes=32_000)
        first = observe(memory, 0, [observation("old total"), observation("shop")])
        roi = observe(memory, 1, [observation("ROI", (400, 300, 500, 350))])
        self.assertEqual([r.text for r in roi.records], ["ROI", "old total", "shop"])
        self.assertEqual(roi.records[1], first.records[0])
        self.assertEqual(roi.records[1].observed_step, 0)
        self.assertEqual(roi.records[0].bbox, (400, 300, 500, 350))
        refreshed = observe(memory, 2, [observation("old total", value=0.75)])
        self.assertEqual(
            [r.text for r in refreshed.records], ["old total", "ROI", "shop"]
        )
        self.assertEqual(refreshed.records[0].features, (0.75,) * 126)
        self.assertEqual(refreshed.records[0].observed_step, 2)
        self.assertEqual(refreshed.receipt.duplicate_candidates, 1)
        self.assertFalse(refreshed.receipt.full_physical_cost_known)
        self.assertGreaterEqual(refreshed.receipt.decision_cpu_seconds, 0)
        self.assertGreaterEqual(refreshed.receipt.decision_wall_seconds, 0)

    def test_every_original_source_scope_change_resets_the_entire_pool(self):
        for field, value in (
            ("original_operation_id", "operation-B"),
            ("case_id", "case-B"),
            ("source_image_sha256", "b" * 64),
            ("source_width", 1200),
            ("source_height", 900),
        ):
            with self.subTest(field=field):
                memory = CandidateMemory(max_serialized_bytes=32_000)
                observe(memory, 9, [observation("old")])
                changed = replace(SCOPE, **{field: value})
                result = observe(memory, 0, [observation("new")], changed)
                self.assertEqual([r.text for r in result.records], ["new"])
                self.assertTrue(result.receipt.scope_reset)
                self.assertEqual(result.receipt.reset_discarded, 1)
                self.assertEqual(result.records[0].scope, changed)

    def test_eviction_priority_distinct_identity_and_exact_byte_accounting(self):
        memory = CandidateMemory(max_entries=3, max_serialized_bytes=32_000)
        observe(memory, 0, [observation("old-a"), observation("old-b")])
        observe(memory, 1, [observation("recent")])
        selected = observe(memory, 2, [observation("now"), observation("now")])
        self.assertEqual([r.text for r in selected.records], ["now", "recent", "old-a"])
        self.assertEqual(selected.receipt.duplicate_candidates, 1)
        self.assertEqual(selected.receipt.entry_dropped, 1)
        distinct = observe(
            memory,
            3,
            [
                observation("same"),
                observation("same", (20, 20, 90, 50)),
                observation("same", origin="registered_public_text"),
            ],
        )
        self.assertEqual(len(distinct.records), 3)
        serialized = json.dumps(
            {"scope": asdict(SCOPE), "records": [asdict(r) for r in distinct.records]},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
        self.assertEqual(distinct.receipt.resident_serialized_bytes, len(serialized))
        one = CandidateMemory(max_serialized_bytes=32_000)
        single = observe(one, 0, [observation("fits")])
        bounded = CandidateMemory(
            max_serialized_bytes=single.receipt.resident_serialized_bytes
        )
        result = observe(bounded, 0, [observation("x" * 4000), observation("fits")])
        self.assertEqual([r.text for r in result.records], ["fits"])
        self.assertEqual(result.receipt.byte_dropped, 1)
        self.assertEqual(
            result.receipt.resident_serialized_bytes, bounded.max_serialized_bytes
        )
        full = CandidateMemory(max_serialized_bytes=2_000_000)
        result = observe(full, 0, [observation(str(i)) for i in range(128)])
        result = observe(full, 1, [observation("new")])
        self.assertEqual(len(result.records), 128)
        self.assertEqual(result.records[-1].text, "126")
        with self.assertRaises(AttributeError):
            full.max_entries = 129
        with self.assertRaises(ValueError):
            CandidateMemory(max_serialized_bytes=32_000, max_entries=129)

    def test_invalid_public_inputs_are_rejected_without_same_scope_loss(self):
        invalid = []
        for field, value in (
            ("original_operation_id", ""),
            ("case_id", " "),
            ("source_image_sha256", "x" * 64),
            ("source_width", True),
            ("source_height", 0),
        ):
            with self.assertRaises(ValueError):
                replace(SCOPE, **{field: value})
        for feature in (math.nan, math.inf, True):
            invalid.append(observation("bad", value=feature))
        invalid += [
            observation("bad", (-1, 0, 4, 4)),
            observation("bad", (0, 0, 1001, 4)),
            observation("bad", (0, 0, 0, 4)),
            observation("bad", origin="evaluator_label"),
        ]
        invalid.append(({**observation("bad")[0], "label": "answer"}, [0.0] * 126))
        invalid.append((observation("bad")[0], [0.0] * 125))
        for value in invalid:
            memory = CandidateMemory(max_serialized_bytes=32_000)
            original = observe(memory, 0, [observation("kept")])
            with self.assertRaises(CandidateMemoryError) as caught:
                observe(memory, 1, [value])
            self.assertEqual(caught.exception.receipt.status, "rejected")
            self.assertEqual(caught.exception.receipt.resident_entries, 1)
            self.assertEqual(observe(memory, 1, []).records, original.records)
        with self.assertRaises(CandidateMemoryError):
            observe(memory, 1, [])
        with self.assertRaises(CandidateMemoryError):
            observe(memory, 2, [observation("many")] * 129)

    def test_caller_mutation_and_rejected_new_scope_cannot_leak_old_records(self):
        memory = CandidateMemory(max_serialized_bytes=32_000)
        metadata, features = observation("original")
        first = observe(memory, 0, [(metadata, features)])
        metadata["text"], metadata["bbox"][0], features[0] = "changed", 99, 99
        retained = observe(memory, 1, [])
        self.assertEqual(retained.records, first.records)
        self.assertIsNot(retained.records[0], first.records[0])
        with self.assertRaises(FrozenInstanceError):
            retained.records[0].text = "changed"
        with self.assertRaises(TypeError):
            retained.records[0].features[0] = 99
        other = replace(SCOPE, original_operation_id="next-operation")
        with self.assertRaises(CandidateMemoryError) as caught:
            observe(memory, 0, [observation("invalid", (0, 0, 0, 1))], other)
        self.assertTrue(caught.exception.receipt.scope_reset)
        self.assertEqual(caught.exception.receipt.resident_entries, 0)
        self.assertEqual(observe(memory, 0, [], other).records, ())


if __name__ == "__main__":
    unittest.main()
