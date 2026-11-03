"""Readout boundaries must preserve typed provenance and fail without residue."""

from dataclasses import replace
import unittest

from v6.contracts import MemoryReadout, MemoryRequest, canonical


class ContractTests(unittest.TestCase):
    def test_request_round_trip_and_utf8_limits(self):
        request = MemoryRequest("q" * 256, "scope", "entity", "读" * 2730, 20, 10)
        self.assertEqual(MemoryRequest.from_dict(request.as_dict()), request)
        for change in (
            {"query_id": "q" * 257},
            {"text": "读" * 2731},
            {"at": True},
            {"since": 21},
            {"max_hops": 0},
            {"max_cells": 9},
            {"scope": "bad\x00scope"},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                MemoryRequest.from_dict({**request.as_dict(), **change})
        with self.assertRaises(ValueError):
            MemoryRequest.from_dict({**request.as_dict(), "expected_answer": 10})

    def test_readout_rejects_invalid_digests_and_contradictory_evidence(self):
        readout = MemoryReadout(
            "query",
            "current",
            "ok",
            17,
            ("a" * 64,),
            1,
            "b" * 64,
            "source_evidence",
            (),
            1,
            0.01,
        )
        self.assertEqual(
            canonical(MemoryReadout.from_dict(readout.as_dict()).as_dict()),
            canonical(readout.as_dict()),
        )
        changes = (
            {"snapshot_digest": "not-a-digest"},
            {"source_ids": ("short",)},
            {"source_ids": ("a" * 64, "a" * 64)},
            {"source_ids": "a" * 64},
            {"generation": True},
            {"elapsed_seconds": float("nan")},
            {"elapsed_seconds": True},
            {"hops": 0},
            {"prediction_kind": "none"},
            {"prediction_kind": "model_prediction"},
            {"cell_digests": ("c" * 64,)},
            {"value": float("inf")},
            {"value": None},
        )
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(readout, **change)
        prediction = replace(
            readout, prediction_kind="model_prediction", cell_digests=("c" * 64,)
        )
        self.assertEqual(prediction.prediction_kind, "model_prediction")
        with self.assertRaises(ValueError):
            MemoryReadout.from_dict({**readout.as_dict(), "trusted": True})

    def test_failed_readout_cannot_carry_values_sources_or_model_claims(self):
        failed = MemoryReadout(
            "query",
            "apply",
            "stale",
            None,
            (),
            2,
            "b" * 64,
            "none",
            (),
            2,
            0.02,
            "source revoked",
        )
        self.assertEqual(MemoryReadout.from_dict(failed.as_dict()), failed)
        for change in (
            {"value": 17},
            {"source_ids": ("a" * 64,)},
            {"cell_digests": ("c" * 64,)},
            {"prediction_kind": "mixed"},
            {"reason": None},
            {"reason": "r" * 1025},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(failed, **change)


if __name__ == "__main__":
    unittest.main()
