"""Metadata/loader controls only; real training and model sessions are replaced."""
from contextlib import ExitStack, contextmanager, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from . import audit_cpu_matched_v2 as offline
from . import frozen_timed_inference_audit as frozen
from . import timed_cpu_matched_v2 as paired
from . import timed_cpu_matched_v3_immutable as immutable
from . import timed_cpu_sealed_entry_v1 as sealed
from .test_immutable_trial_receipts import record
from . import test_timed_cpu_matched_v2 as budget_fixture
from .test_timed_cpu_sealed_entry_v1 import GOOD

PINS = {
    "copy": "e92c7f7d5efd75ba4bd7c3511da02bc157f13af127e48cd16ba72dea24dfa895",
    "mqar4": "bd8cf2b234e749b0320d2372a27a1c2dab1b7a2692b9ba3897e8e28966ec1a62",
}


class MetadataBoundaryTests(unittest.TestCase):
    def test_paired_cpu_and_accuracy_must_be_finite(self):
        for field in ("training_cpu_seconds", "id", "ood"):
            for value in (float("nan"), float("inf"), -float("inf")):
                with self.subTest(field=field, value=value):
                    left, right = budget_fixture.CPUBudgetFollowupTests.pair()
                    if field in ("id", "ood"):
                        right[field]["accuracy"] = value
                    else:
                        right[field] = value
                    with self.assertRaises(paired.UnresolvedContent):
                        paired.validate_pair(left, right)

    def test_registered_pair_rejects_float_seed_and_unknown_task(self):
        for field, value in (("seed", 2.0), ("task", "unregistered")):
            with self.subTest(field=field):
                left, right = budget_fixture.CPUBudgetFollowupTests.pair()
                left[field] = right[field] = value
                with self.assertRaises(paired.UnresolvedContent):
                    paired.validate_pair(left, right)

    def test_offline_accuracy_and_eval_cpu_must_be_finite(self):
        original = offline.load_raw(Path(offline.__file__).parent /
                                    "TIMED_CPU_MATCHED_FOLLOWUP_12_RAW_20261031.json.gz.b64")
        for field in ("accuracy", "cpu_seconds"):
            for value in (float("nan"), float("inf"), -float("inf")):
                with self.subTest(field=field, value=value):
                    changed = deepcopy(original)
                    changed["records"][0]["id"][field] = value
                    with self.assertRaises(offline.UnresolvedAudit):
                        offline.audit(changed)

    def test_offline_comparison_cannot_use_nan_as_equal(self):
        original = offline.load_raw(Path(offline.__file__).parent /
                                    "TIMED_CPU_MATCHED_FOLLOWUP_12_RAW_20261031.json.gz.b64")
        for field in ("training_cpu_relative_gap", "id_signed_pp", "ood_signed_pp"):
            with self.subTest(field=field):
                changed = deepcopy(original)
                changed["comparisons"][0][field] = float("nan")
                with self.assertRaises(offline.UnresolvedAudit):
                    offline.audit(changed)

    def test_result_identity_is_checked_before_any_immutable_publication(self):
        with TemporaryDirectory() as directory:
            wrong = record("mqar4", 3, "physical_event_timestamp")
            with patch.object(paired, "run", return_value=wrong) as runner, patch.object(
                    immutable, "publish", wraps=immutable.publish) as publisher:
                with self.assertRaises(immutable.UnresolvedReceipt):
                    immutable.run_and_publish("copy", 2, "aggregate_count", Path(directory))
                runner.assert_called_once_with("copy", 2, "aggregate_count")
                publisher.assert_not_called()
            self.assertEqual(list(Path(directory).rglob("*.json")), [])

    def test_run_id_full_grammar_is_checked_before_training_or_source_reads(self):
        prefix = "copy-s2-aggregate_count-"
        for suffix in ("abcdefgh/bad", "abcdefgh.bad", "a" * 97):
            with self.subTest(suffix=suffix), TemporaryDirectory() as directory:
                with patch.object(sealed.timed_cpu_matched_v2, "run", return_value=GOOD) as runner, patch.object(
                        sealed, "_source_seals", return_value={}) as source_reads:
                    with self.assertRaises(sealed.EvidenceUnresolved):
                        sealed.run_and_record("copy", 2, "aggregate_count", Path(directory), prefix + suffix)
                    runner.assert_not_called()
                    source_reads.assert_not_called()
                self.assertEqual(list(Path(directory).rglob("*.json")), [])


class FrozenLoaderBoundaryTests(unittest.TestCase):
    @contextmanager
    def fake_workload(self, loader):
        seen = []

        class Model:
            def __init__(self, width):
                self.state = None

            def eval(self):
                return self

            def load_state_dict(self, state):
                self.state = state

        class Owner:
            def __init__(self, model, spec, **kwargs):
                seen.append(model)
                self.event_count = 0

            def ingest(self, time, value):
                self.event_count += 1
                return 1, 1.0

        def example(task, *, length, seed):
            return [0.0] * length, [1.0] * length, [True] * length, None, list(range(length))

        with ExitStack() as stack:
            stack.enter_context(patch.object(frozen, "TrainableEventContent", Model))
            loaded = stack.enter_context(patch.object(frozen.torch, "load", side_effect=loader))
            stack.enter_context(patch.object(frozen.torch, "set_num_threads"))
            stack.enter_context(patch.object(frozen, "model_digest", side_effect=lambda model: model.state))
            stack.enter_context(patch.object(frozen, "ContentSession", Owner))
            stack.enter_context(patch.object(frozen, "TimedFireSession", Owner))
            stack.enter_context(patch.object(frozen, "default_spec", return_value=object()))
            stack.enter_context(patch.object(frozen, "example", side_effect=example))
            stack.enter_context(patch.object(frozen, "train_pilot", side_effect=AssertionError("training forbidden")))
            yield loaded, seen

    def test_public_audit_refuses_unpinned_loaded_model_before_sessions(self):
        with self.fake_workload(lambda *args, **kwargs: "0" * 64) as (loaded, seen):
            with self.assertRaises(RuntimeError):
                frozen.audit("synthetic-copy.pt", task="copy", actors=1, length=12)
            loaded.assert_called_once()
            self.assertEqual(seen, [])

    def test_public_audit_accepts_pinned_synthetic_model_without_training(self):
        with self.fake_workload(lambda *args, **kwargs: PINS["copy"]) as (loaded, seen):
            result = frozen.audit("synthetic-copy.pt", task="copy", actors=1, length=12)
            loaded.assert_called_once()
            self.assertEqual(result["model_sha256"], PINS["copy"])
            self.assertFalse(result["production_activation"])
            self.assertFalse(result["all_scientific_blockers_closed"])
            self.assertIs(seen[0], seen[1])

    def test_main_uses_same_verified_model_for_both_length_panels(self):
        counts = {}

        def replace_on_reload(path, **kwargs):
            task = Path(path).name.split("_", 1)[0]
            counts[task] = counts.get(task, 0) + 1
            return PINS[task] if counts[task] == 1 else "0" * 64

        with TemporaryDirectory() as directory, self.fake_workload(replace_on_reload) as (loaded, seen):
            output = Path(directory) / "result.json"
            argv = ["audit", "--weights-dir", directory, "--actors", "1", "--output", str(output)]
            with patch("sys.argv", argv), redirect_stdout(io.StringIO()):
                frozen.main()
            result = json.loads(output.read_text())
            self.assertEqual(counts, {"copy": 1, "mqar4": 1})
            self.assertEqual(loaded.call_count, 2)
            self.assertEqual(len(result["records"]), 4)
            for result_row in result["records"]:
                self.assertEqual(result_row["model_sha256"], PINS[result_row["task"]])
            self.assertTrue(all(model is seen[0] for model in seen[:4]))
            self.assertTrue(all(model is seen[4] for model in seen[4:]))
            self.assertIsNot(seen[0], seen[4])


if __name__ == "__main__":
    unittest.main()
