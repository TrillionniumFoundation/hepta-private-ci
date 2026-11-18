"""Dependency-free failure behavior tests; Python sentinels are not GPU evidence."""

from contextlib import ExitStack
import os
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from . import shared_pool_v4 as shared


class CudaFixture:
    def __init__(self, error=None):
        self.error, self.empty_calls, self.caps = error, 0, []

    def is_available(self):
        return True  # An isolated branch fixture, not an actual CUDA query.

    def set_per_process_memory_fraction(self, fraction, device):
        self.caps.append((fraction, device))

    def empty_cache(self):
        self.empty_calls += 1
        if self.error:
            raise self.error


def predictor_fixture(torch, constructor_error=None, close_error=None):
    instances = []

    class View:
        def __init__(self, *_):
            instances.append(self)
            self.model, self.tokenizer, self.torch = object(), object(), torch
            self.closed, self.close_calls = False, 0
            if constructor_error:
                raise constructor_error

        def close(self):
            self.close_calls += 1
            if close_error:
                raise close_error
            self.model, self.tokenizer, self.closed = None, None, True

    return View, instances


class LegacyStyleError(RuntimeError):
    add_note = None


def notes(error):
    return "\n".join(
        [*getattr(error, "__notes__", []), *getattr(error, "cleanup_notes", [])]
    )


class PoolCleanupTests(unittest.TestCase):
    def construct_failure(
        self, stage, close_error=None, cache_error=None, error_type=RuntimeError
    ):
        primary = error_type(stage + " primary failure")
        cuda = CudaFixture(cache_error)
        torch = SimpleNamespace(cuda=cuda, device=lambda value: value)
        view_type, instances = predictor_fixture(
            torch,
            constructor_error=primary if stage == "constructor" else None,
            close_error=close_error,
        )
        base = {
            "runtime": {
                "device": "cuda:0",
                "dtype": "bfloat16",
                "min_cuda_free_bytes": 4294967296,
                "max_input_tokens": 4096,
                "max_new_tokens": 384,
            }
        }
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(shared, "verified_entries", return_value=({}, base))
            )
            stack.enter_context(
                patch.object(shared.probe, "_libraries", return_value=(torch, None))
            )
            stack.enter_context(
                patch.object(shared.probe, "check_device", return_value={})
            )
            stack.enter_context(patch.object(shared.probe, "Predictor", view_type))
            install = stack.enter_context(
                patch.object(shared.SharedAdapterPool, "_install", side_effect=primary)
            )
            with self.assertRaises(RuntimeError) as caught:
                shared.SharedAdapterPool({}, Path("/engineering-fixture"))
        self.assertIs(caught.exception, primary)
        self.assertEqual(install.call_count, 0 if stage == "constructor" else 1)
        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0].close_calls, 1)
        self.assertIsNone(instances[0].model)
        self.assertIsNone(instances[0].tokenizer)
        self.assertTrue(instances[0].closed)
        self.assertEqual(cuda.empty_calls, 1)
        self.assertEqual(cuda.caps, [(0.70, "cuda:0")])
        return primary

    def test_partial_constructor_is_retained_and_closed(self):
        self.construct_failure("constructor")

    def test_adapter_install_failure_closes_the_initialized_view(self):
        self.construct_failure("install")

    def test_constructor_error_survives_close_and_cache_errors(self):
        primary = self.construct_failure(
            "constructor", RuntimeError("close failure"), RuntimeError("cache failure")
        )
        self.assertIn("close failure", notes(primary))
        self.assertIn("cache failure", notes(primary))

    def test_cleanup_notes_work_without_python_311_add_note(self):
        primary = self.construct_failure(
            "constructor",
            LegacyStyleError("close failure"),
            LegacyStyleError("cache failure"),
            LegacyStyleError,
        )
        self.assertFalse(callable(getattr(primary, "add_note", None)))
        self.assertIn("close failure", notes(primary))
        self.assertIn("cache failure", notes(primary))
        self.assertGreater(len(primary.cleanup_notes), 0)

    def close_fixture(self, close_error=None, cache_error=None):
        cuda = CudaFixture(cache_error)
        torch = SimpleNamespace(cuda=cuda)
        view_type, _ = predictor_fixture(torch, close_error=close_error)
        view = view_type()
        pool = shared.SharedAdapterPool.__new__(shared.SharedAdapterPool)
        pool._view, pool._closed = view, False
        pool._lock, pool._owner_pid = threading.Lock(), os.getpid()
        return pool, view, cuda

    def assert_unusable(self, pool, view):
        self.assertTrue(pool._closed)
        self.assertIsNone(pool._view)
        self.assertIsNone(view.model)
        self.assertIsNone(view.tokenizer)
        self.assertTrue(view.closed)
        with self.assertRaisesRegex(ValueError, "pool is closed"):
            pool.generate("A", {}, "/not-created-closed-pool")

    def test_close_failure_cannot_leave_reusable_model_or_mask_original_error(self):
        primary = RuntimeError("close primary failure")
        pool, view, cuda = self.close_fixture(
            primary, RuntimeError("cache later failure")
        )
        with self.assertRaises(RuntimeError) as caught:
            pool.close()
        self.assertIs(caught.exception, primary)
        self.assertIn("cache later failure", notes(primary))
        self.assertEqual(cuda.empty_calls, 1)
        self.assert_unusable(pool, view)
        pool.close()
        self.assertEqual(view.close_calls, 1)

    def test_cache_only_failure_is_reported_after_references_are_cleared(self):
        primary = RuntimeError("cache primary failure")
        pool, view, cuda = self.close_fixture(cache_error=primary)
        with self.assertRaises(RuntimeError) as caught:
            pool.close()
        self.assertIs(caught.exception, primary)
        self.assertEqual(cuda.empty_calls, 1)
        self.assert_unusable(pool, view)

    def test_successful_close_is_idempotent(self):
        pool, view, cuda = self.close_fixture()
        pool.close()
        pool.close()
        self.assertEqual((view.close_calls, cuda.empty_calls), (1, 1))
        self.assert_unusable(pool, view)

    def test_invalid_cell_ids_are_rejected_before_legacy_model_access(self):
        for invalid in ("invalid/id", "", "x" * 65, "汉", 1, None):
            with (
                self.subTest(invalid=invalid),
                patch.object(shared, "legacy") as legacy,
            ):
                with self.assertRaisesRegex(ValueError, "invalid Cell ID"):
                    shared.verified_entries(
                        {"A": {}, "B": {}, invalid: {}}, Path("/unused")
                    )
                legacy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
