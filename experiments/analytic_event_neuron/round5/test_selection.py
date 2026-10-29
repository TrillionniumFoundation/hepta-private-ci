"""Exercise the actual selectors, their information boundary and freeze gate."""

from copy import deepcopy
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np

from .. import task
from ..round4 import calibration as cal, calibration_study as legacy
from . import selection_study as study
from .selection_math import select_gaussian, select_prior, zero_context


def fixture_seed(role):
    return int.from_bytes(hashlib.sha256(("hepta.aen.r5.unit-validation.v1|" + role).encode()).digest()[:6], "big")


class SelectionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old = task.build_dataset(fixture_seed("old"), 256, "calibration_development")
        cls.new = task.build_dataset(fixture_seed("new"), 256, "calibration_development", "drift_shift")
        cls.anchor = {"kind": "filter", "parameters": [.12, .18, 1.], "planning_q": .18, "planning_noise_scale": 1.}
        cls.online = {**cls.anchor, "parameters": [.32, .18, 1.]}
        cls.model = cal.make_model(cls.anchor, cls.online, context_count=0)
        cls.model["prior"] = .0137

    @contextmanager
    def bound_fixture(self):
        """Tiny synthetic binding fixture, outside every registered data identity."""
        reg = {**study.registration(), "namespace": "hepta.aen.r5.unit-binding.v1", "seeds": [99107],
               "windows": ["drift_shift"], "confirmation_rows_per_domain": 4}
        with TemporaryDirectory() as directory, patch.object(study, "registration", return_value=reg):
            root = Path(directory)
            prepared_root = root / "prepared"
            seed_root = prepared_root / "seed_99107"
            seed_root.mkdir(parents=True)
            for name in ("ORIGINAL_TRAIN.npz", "ANCHOR.json", "window_00_TRAIN.npz",
                         "window_00_OLD_DEV.npz", "window_00_NEW_DEV.npz", "window_00_CHECKPOINT.json"):
                (seed_root / name).write_text("synthetic binding fixture; not an experiment\n")
            artifacts = {p.relative_to(prepared_root).as_posix(): study.sha(p) for p in seed_root.iterdir()}
            environment = study.environment_snapshot()
            prepared = {"registration": reg, "registration_sha256": study.object_sha(reg),
                        "sources_sha256": study.source_snapshot(), "planned_seed_schedule": study.seed_schedule(reg),
                        "environment": environment, "optimizer_failures": [], "confirmation_arrays_constructed": False,
                        "artifacts_sha256": artifacts, "checkpoint_receipts": [{"seed": 99107, "window": 0,
                            "checkpoint_sha256": artifacts["seed_99107/window_00_CHECKPOINT.json"]}]}
            study.write(prepared_root / "PREPARED.json", prepared)
            study.freeze_prepared(root, study.object_sha(reg))
            destination = root / "confirmation"
            destination.mkdir()
            study.write(root / "CONFIRMATION_STARTED.json", {"freeze_sha256": study.sha(root / "FREEZE.json"), "environment": environment})
            arrays, digests = {}, {}
            for domain, window, law, name in (("old", -1, "gaussian", "seed_99107_OLD.npz"),
                                             ("new", 0, "drift_shift", "seed_99107_window_00_NEW.npz")):
                data = task.build_dataset(study.seed_value(reg, "confirmation", 99107, window, domain), 4,
                                          "selection_" + domain + "_confirmation", law)
                np.savez_compressed(destination / name, **data)
                digests[domain] = task.dataset_digest(data)
                scores, _ = cal.scores(cal.predict_distribution(self.model, task.history(data)), data)
                arrays.update({arm + "__" + domain + "__" + key: value for arm in study.ARMS for key, value in scores.items()})
            score_path = destination / "seed_99107_window_00_SCORES.npz"
            np.savez_compressed(score_path, **arrays)
            row = {"seed": 99107, "window": 0, "environment": "drift_shift", "score_path": score_path.name,
                   "score_sha256": study.sha(score_path), "query_dataset_digests": digests,
                   "checkpoint_sha256": artifacts["seed_99107/window_00_CHECKPOINT.json"]}
            index = {"registration": reg, "records": [row], "freeze_sha256": study.sha(root / "FREEZE.json"),
                     "environment": environment, "unique_query_trajectories": 8, "public_context_histories": 0,
                     "old_rows_reused_across_windows": True}

            def reseal():
                (destination / "seed_99107_window_00.json").write_text(json.dumps(row))
                index["artifacts_sha256"] = {p.name: study.sha(p) for p in destination.iterdir() if p.name != "INDEX.json"}
                (destination / "INDEX.json").write_text(json.dumps(index))

            reseal()
            yield root, index, arrays, reseal

    def test_actual_legacy_selector_matches_pinned_implementation(self):
        for projection in (False, True):
            model = {**self.model, "projection": projection}
            actual, record = select_prior(model, self.old, self.new, "legacy")
            expected, old_record = cal.select_model(model, self.old, self.new, zero_context(), zero_context())
            self.assertEqual(actual, expected)
            self.assertEqual(record["candidates"], old_record["candidates"])
            self.assertEqual(record["selected_index"], old_record["selected_index"])

    def test_full_range_can_select_beyond_fitted_cap_under_the_same_guard(self):
        limited, old_record = select_prior(self.model, self.old, self.new, "legacy")
        full, record = select_prior(self.model, self.old, self.new, "full_range")
        self.assertGreater(full["prior"], self.model["prior"])
        self.assertLessEqual(limited["prior"], self.model["prior"])
        chosen = record["candidates"][record["selected_index"]]
        self.assertTrue(chosen["eligible"])
        self.assertLessEqual(chosen["old_upper_heuristic"], .02)
        self.assertEqual(record["development_dataset_digests"], old_record["development_dataset_digests"])
        old_grid = {row["prior"] for row in old_record["candidates"]}
        full_grid = {row["prior"] for row in record["candidates"]}
        self.assertFalse(old_grid <= full_grid)
        self.assertEqual(len(old_grid), len(full_grid))

    def test_gaussian_replay_predictions_match_existing_selector(self):
        replay = {**self.anchor, "parameters": [.22, .19, 1.03]}
        actual, receipt = select_gaussian(self.anchor, replay, self.old, self.new, "balanced_replay")
        expected, old_receipt = legacy.select_replay(self.anchor, replay, self.old, self.new)
        expected["context_count"] = 0
        self.assertEqual(receipt["selected_index"], old_receipt["selected_index"])
        history = task.history(self.new)
        a, b = cal.predict_distribution(actual, history), cal.predict_distribution(expected, history)
        for key in a:
            np.testing.assert_array_equal(a[key], b[key])

    def test_selected_law_uses_only_public_history_and_matches_dense_reference(self):
        selected, _ = select_prior(self.model, self.old, self.new, "full_range")
        data = legacy.subset(self.new, 6)
        history = task.history(data)
        original = cal.predict_distribution(selected, history)
        altered = deepcopy(data)
        altered["future"][:] = -999.
        altered["ids"][:] = "irrelevant"
        altered["law"], altered["drift"] = "unused_metadata", -100.
        updated = cal.predict_distribution(selected, task.history(altered))
        dense = cal.predict_distribution(selected, history, classical=True)
        for key in original:
            np.testing.assert_array_equal(original[key], updated[key])
            np.testing.assert_allclose(original[key], dense[key], rtol=0, atol=2e-12)
        np.testing.assert_allclose(cal.mixture_event_probs(original).sum(-1), 1., rtol=0, atol=2e-15)

    def test_prior_gradient_against_five_point_difference(self):
        data = legacy.subset(self.new, 12)
        cache, target = cal.component_cache(self.model, task.history(data)), task.targets(data)
        for projection in (False, True):
            for raw in (-1.1, .6):
                step = 2e-4
                values = [cal.prior_objective([raw + shift * step], cache, target, projection)[0] for shift in (-2, -1, 1, 2)]
                reference = (values[0] - 8 * values[1] + 8 * values[2] - values[3]) / (12 * step)
                actual = cal.prior_objective([raw], cache, target, projection)[1][0]
                self.assertAlmostEqual(actual, reference, delta=2e-9)

    def test_selector_rejects_confirmation_labels_and_extra_context(self):
        wrong = {**self.old, "split": "selection_old_confirmation"}
        with self.assertRaises(ValueError):
            select_prior(self.model, wrong, self.new, "full_range")
        with self.assertRaises(ValueError):
            select_gaussian(self.anchor, self.online, wrong, self.new, "current_only_online")
        with self.assertRaises(ValueError):
            select_prior({**self.model, "context_count": 8}, self.old, self.new, "full_range")

    def test_phase_and_smoke_identities_are_disjoint_and_smoke_cannot_address_holdouts(self):
        registered, smoke = study.registration(), study.registration("development_smoke")
        full_seeds = {row["generator_seed"] for row in study.seed_schedule(registered)}
        smoke_seeds = {row["generator_seed"] for row in study.seed_schedule(smoke)}
        self.assertFalse(full_seeds & smoke_seeds)
        with self.assertRaises(ValueError):
            study.seed_value(smoke, "confirmation", 99001, -1, "old")

    def test_missing_or_wrong_freeze_cannot_construct_any_confirmation_array(self):
        with TemporaryDirectory() as directory, patch.object(task, "build_dataset", wraps=task.build_dataset) as generator:
            root = Path(directory)
            with self.assertRaises(ValueError):
                study.confirm(root, None)
            self.assertFalse((root / "confirmation").exists())
            with self.assertRaises(ValueError):
                study.freeze_prepared(root, "unreviewed")
            (root / "confirmation").mkdir()
            with self.assertRaises(ValueError):
                study.freeze_prepared(root, study.object_sha(study.registration()))
            generator.assert_not_called()

    def test_selected_checkpoint_reopens_exactly(self):
        selected, _ = select_prior(self.model, self.old, self.new, "full_range")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            study.write(path, selected)
            restored = json.loads(path.read_text())
            history = task.history(legacy.subset(self.new, 4))
            left, right = cal.predict_distribution(selected, history), cal.predict_distribution(restored, history)
            for key in left:
                np.testing.assert_array_equal(left[key], right[key])

    def test_recovery_verifies_source_environment_and_prepared_model(self):
        with self.bound_fixture() as (root, index, _, _):
            self.assertEqual(len(study.verify_confirmation(root)[1]), 1)
            with patch.object(study, "environment_snapshot", return_value={"changed": True}):
                with self.assertRaises(ValueError):
                    study.verify_confirmation(root)
            with patch.object(study, "source_snapshot", return_value={"changed": "source"}):
                with self.assertRaises(ValueError):
                    study.verify_confirmation(root)
            checkpoint = root / "prepared/seed_99107/window_00_CHECKPOINT.json"
            checkpoint.write_text("changed model")
            with self.assertRaises(ValueError):
                study.summarize(root)
            self.assertFalse((root / "confirmation/RESULTS.json").exists())

    def test_recovery_rejects_rebound_raw_identities_score_shapes_and_wrong_freeze(self):
        for alteration in ("raw_identity", "score_shape", "checkpoint_binding", "freeze_binding", "missing_raw"):
            with self.subTest(alteration=alteration), self.bound_fixture() as (root, index, arrays, reseal):
                row, destination = index["records"][0], root / "confirmation"
                if alteration == "raw_identity":
                    path = destination / "seed_99107_window_00_NEW.npz"
                    data = legacy.load(path)
                    data["seed"] += 1
                    np.savez_compressed(path, **data)
                    row["query_dataset_digests"]["new"] = task.dataset_digest(data)
                elif alteration == "score_shape":
                    arrays["frozen__new__density_nll"] = arrays["frozen__new__density_nll"][:-1]
                    path = destination / row["score_path"]
                    np.savez_compressed(path, **arrays)
                    row["score_sha256"] = study.sha(path)
                elif alteration == "checkpoint_binding":
                    row["checkpoint_sha256"] = "detached"
                elif alteration == "freeze_binding":
                    index["freeze_sha256"] = "different freeze"
                else:
                    (destination / "seed_99107_OLD.npz").unlink()
                reseal()
                with self.assertRaises(ValueError):
                    study.verify_confirmation(root)


if __name__ == "__main__":
    unittest.main()
