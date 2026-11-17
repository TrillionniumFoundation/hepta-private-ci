#!/usr/bin/env python3
"""Synthetic-only tests for the fail-closed admission contract."""

from __future__ import annotations

import copy
import unittest

from admission import AdmissionError, load_request, validate_request


class AdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = load_request()

    def test_frozen_request_holds(self) -> None:
        result = validate_request(self.request)
        self.assertEqual(result["status"], "HOLD_INCOMPLETE_HISTORY")
        self.assertEqual(result["full_fit_replays"], "0/6")
        self.assertFalse(result["replay_admitted"])
        self.assertFalse(result["diagnostics_count_as_full_replay"])

    def reject(self, mutation) -> None:
        candidate = copy.deepcopy(self.request)
        mutation(candidate)
        with self.assertRaises(AdmissionError):
            validate_request(candidate)

    def test_rejects_replay_admission(self) -> None:
        self.reject(lambda value: value["decision"].__setitem__("replay_admitted", True))

    def test_rejects_execution_key(self) -> None:
        self.reject(lambda value: value["decision"].__setitem__("execution_key", "new-key"))

    def test_rejects_diagnostic_relabel(self) -> None:
        self.reject(lambda value: value["diagnostics"].__setitem__("counts_as_full_training_replay", True))

    def test_rejects_full_replay_claim(self) -> None:
        self.reject(lambda value: value["decision"].__setitem__("full_fit_replays_completed", 6))

    def test_rejects_current_balance_fill(self) -> None:
        self.reject(lambda value: value["budget"].__setitem__("current_charged_remainder_seconds", 1.0))

    def test_rejects_unknown_optimizer_fill(self) -> None:
        self.reject(lambda value: value["decision"].__setitem__("lifetime_optimizer_calls", 52))

    def test_rejects_cursor_inference(self) -> None:
        self.reject(lambda value: value["fits"][0].__setitem__("cursor", 0))

    def test_rejects_wall_rewrite(self) -> None:
        self.reject(lambda value: value["fits"][0].__setitem__("original_whole_process_wall_seconds", 0.0))

    def test_rejects_runtime_completion_claim(self) -> None:
        self.reject(lambda value: value["source_runtime_model_data"].__setitem__("runtime_identity_bytes_git_bound", True))

    def test_rejects_nonzero_optimizer_execution(self) -> None:
        self.reject(lambda value: value["constraints"].__setitem__("optimizer_calls", 1))


if __name__ == "__main__":
    unittest.main()
