"""Real CPU experiment execution with explicitly synthetic features and dates.

No pretrained weights, real temporal outcome, native owner or production grant.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import torch

from development_study import (benchmark_reuse, feature_requests, fit_and_seal, prepare_views)
from development_study_data import (StudyConfig, PHASES, audit_rows, canonical, digest,
                                    phase, public_input, read_dataset, write_once)
from development_study_fit import (RoutedBank, fit_candidates, routed_centers,
                                   select_candidate, widen_candidate)
from development_study_review import score_predictions
from development_tensors import BasisCellHeads, parameter_digest
from test_shared_encoder_eviction import ToyBackend


def fixture_rows(count=8):
    rows = []
    epoch = datetime(2000, 1, 1, tzinfo=timezone.utc)
    for window, p in enumerate(PHASES):
        for i in range(count):
            ident = f"{p}-{i:04}"
            rows.append({"sample_id": ident, "source_group": ident, "episode_id": ident,
                "scope": "synthetic-only", "language": "en", "split": "train" if window < 3 else p,
                "training_phase": p if window < 3 else None,
                "observed_at": (epoch + timedelta(days=window, seconds=i)).isoformat(),
                "state": f"synthetic source {ident}", "question": "synthetic binary task",
                "options": ["class-zero", "class-one"], "label": i % 2})
    return rows


def fixture_features(rows):
    x = torch.randn(len(rows), 4, generator=torch.Generator().manual_seed(912))
    x[:, 0] = torch.tensor([2*r["label"]-1 for r in rows])
    return x


class StudyChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.threads = torch.get_num_threads()
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.threads)

    def setUp(self):
        self.config = StudyConfig(rank=2, base_steps=6, adaptation_steps=8, minimum_groups=2,
                                  origin="synthetic_fixture")
        self.rows = fixture_rows()

    def test_full_phase_audit(self):
        rows = audit_rows(self.rows, self.config)
        self.assertEqual(len(rows), 64)
        self.assertEqual([phase(r) for r in rows][::8], list(PHASES))

    def test_missing_and_unknown_keys(self):
        for mutation in (lambda r: r.pop("scope"), lambda r: r.update(truth_hint=1)):
            rows = deepcopy(self.rows)
            mutation(rows[0])
            with self.assertRaises(ValueError):
                audit_rows(rows, self.config)

    def test_training_subphase_group_and_episode_leak(self):
        for field in ("source_group", "episode_id"):
            rows = deepcopy(self.rows)
            rows[8][field] = rows[0][field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                audit_rows(rows, self.config)

    def test_changed_question_does_not_hide_reused_source(self):
        rows = deepcopy(self.rows)
        rows[8]["state"] = rows[0]["state"]
        rows[8]["question"] = "a different question"
        with self.assertRaises(ValueError):
            audit_rows(rows, self.config)

    def test_whitespace_unicode_source_alias(self):
        rows = deepcopy(self.rows)
        rows[0]["state"] = "café source"
        rows[8]["state"] = "  cafe\u0301   source\n"
        with self.assertRaises(ValueError):
            audit_rows(rows, self.config)

    def test_scope_and_reordered_options_refused(self):
        for key, value in (("scope", "other"), ("options", ["class-one", "class-zero"])):
            rows = deepcopy(self.rows)
            rows[9][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                audit_rows(rows, self.config)

    def test_bad_times_and_overlapping_windows(self):
        for value in ("2000-01-01T00:00:00", self.rows[0]["observed_at"], "not-a-time"):
            rows = deepcopy(self.rows)
            rows[8]["observed_at"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                audit_rows(rows, self.config)

    def test_missing_training_class_is_not_imputed(self):
        rows = deepcopy(self.rows)
        for row in rows[:8]:
            row["label"] = 0
        with self.assertRaises(ValueError):
            audit_rows(rows, self.config)

    def test_optional_future_folds_not_fabricated(self):
        rows = [r for r in self.rows if phase(r) not in {"future_1", "future_2", "ood"}]
        self.assertEqual(len(audit_rows(rows, self.config)), 40)

    def test_config_refuses_nan_bool_unbounded_and_unknown_origin(self):
        for config in (replace(self.config, rank=True), replace(self.config, alpha=float("nan")),
                       replace(self.config, rank=33), replace(self.config, origin="authenticated")):
            with self.subTest(config=config), self.assertRaises(ValueError):
                config.validate()

    def test_byte_bound_and_digest_failures(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data.jsonl"
            payload = b"".join(canonical(r) for r in self.rows)
            path.write_bytes(payload)
            self.assertEqual(len(read_dataset(path, hashlib.sha256(payload).hexdigest(), self.config)), 64)
            with self.assertRaises(ValueError):
                read_dataset(path, "0"*64, self.config)
            path.write_bytes(b'{"label":0,"label":1}\n')
            with self.assertRaises(ValueError):
                read_dataset(path, hashlib.sha256(path.read_bytes()).hexdigest(), self.config)

    def test_evaluation_truth_not_in_training_view(self):
        inputs, truth = prepare_views(self.rows)
        self.assertTrue(all("label" not in r for r in inputs))
        self.assertEqual(len(truth), 32)
        self.assertNotIn("held_out-0000", truth)

    def test_widening_retains_initial_nonzero_parent_function(self):
        parent = RoutedBank(BasisCellHeads(4, 2, 2, ("parent",)))
        with torch.no_grad():
            parent.bank.coefficients.fill_(.4)
            parent.bank.gates.fill_(.2)
        x = fixture_features(self.rows)
        wider = widen_candidate(parent, seed=31)
        torch.testing.assert_close(wider(x), parent(x), atol=1e-6, rtol=1e-6)
        self.assertEqual(wider.bank.rank, 4)

    def test_router_has_no_supported_split_on_identical_features(self):
        parent = RoutedBank(BasisCellHeads(4, 2, 2, ("parent",)))
        self.assertIsNone(routed_centers(torch.ones(8, 4), torch.tensor([0, 1]*4), parent))

    def test_five_arms_reuse_one_base_and_total_step_budget(self):
        x = fixture_features(self.rows)
        y = torch.tensor([r["label"] for r in self.rows])
        models, report, _, _ = fit_candidates(x[:8], y[:8], x[8:16], y[8:16], x[16:24], y[16:24], self.config)
        self.assertEqual(set(models), {"frozen", "continued", "wider", "more_data", "split"})
        for arm in ("continued", "wider", "more_data", "split"):
            self.assertEqual(report["adaptation"][arm]["steps"], 8)
        self.assertEqual(report["adaptation"]["more_data"]["training_rows"], 16)
        self.assertEqual(report["adaptation"]["split"]["training_rows"], 8)
        self.assertEqual(report["adaptation"]["split"]["trainable_parameters"], 10)
        self.assertEqual(report["adaptation"]["wider"]["trainable_parameters"], 9)
        self.assertTrue(torch.equal(models["frozen"].bank.basis, models["split"].bank.basis))
        self.assertEqual(report["adaptation"]["frozen"]["parameter_digest"], parameter_digest(models["frozen"]))

    def test_future_label_permutation_cannot_change_weights_or_selection(self):
        x = fixture_features(self.rows)
        changed = deepcopy(self.rows)
        for r in changed:
            if phase(r) not in {"base", "adapt", "extra", "calibration"}:
                r["label"] = 1-r["label"]
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            ra = fit_and_seal(*prepare_views(self.rows), x, self.config, Path(a))
            rb = fit_and_seal(*prepare_views(changed), x, self.config, Path(b))
            self.assertEqual(ra["predictions_sha256"], rb["predictions_sha256"])
            sa, sb = [json.loads((Path(p)/"selection.json").read_bytes()) for p in (a, b)]
            self.assertEqual(sa["checkpoints"], sb["checkpoints"])
            self.assertEqual(sa["selected_arm"], sb["selected_arm"])

    def test_extra_test_label_at_fitter_entry_is_rejected(self):
        inputs, truth = prepare_views(self.rows)
        truth["held_out-0000"] = 1
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(ValueError):
            fit_and_seal(inputs, truth, fixture_features(self.rows), self.config, Path(folder))

    def test_create_once_no_second_training_overwrites(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            fit_and_seal(*prepare_views(self.rows), fixture_features(self.rows), self.config, output)
            original = (output/"predictions.json").read_bytes()
            with self.assertRaises(FileExistsError):
                fit_and_seal(*prepare_views(self.rows), fixture_features(self.rows), self.config, output)
            self.assertEqual((output/"predictions.json").read_bytes(), original)

    def test_shared_serial_physical_calls_and_feature_parity(self):
        backend = ToyBackend()
        requests = feature_requests(audit_rows(self.rows, self.config), backend, self.config, "f"*64)
        result = benchmark_reuse(requests, backend, self.config)
        self.assertEqual(result["arms"]["serial_no_cache"]["backend_calls"], 32)
        self.assertEqual(result["arms"]["shared_batch"]["backend_calls"], 1)
        self.assertEqual(result["arms"]["shared_batch"]["encoded_rows"], 4)
        self.assertEqual(result["max_abs_feature_error"], 0)
        self.assertTrue(result["simulated_encoder"])

    def gate_inputs(self, groups=512):
        labels = torch.zeros(groups, dtype=torch.long)
        logits = {n: torch.tensor([[0., 1.]]).repeat(groups, 1) for n in ("frozen", "continued", "wider", "more_data")}
        logits["split"] = torch.tensor([[1., 0.]]).repeat(groups, 1)
        costs = {n: {"stored_scalars": 100} for n in logits}
        return logits, labels, [str(i) for i in range(groups)], costs

    def test_split_supported_only_against_all_strong_controls(self):
        values = self.gate_inputs()
        result = select_candidate(*values, self.config)
        self.assertEqual(result["selected_arm"], "split")
        self.assertFalse(result["production_authorized"])
        values[0]["wider"] = values[0]["split"].clone()
        result = select_candidate(*values, self.config)
        self.assertFalse(result["split_supported_on_calibration"])
        self.assertEqual(result["selected_arm"], "wider")

    def test_many_correlated_rows_are_not_many_source_groups(self):
        logits, labels, groups, costs = self.gate_inputs()
        result = select_candidate(logits, labels, ["same"]*len(groups), costs, self.config)
        self.assertFalse(result["split_supported_on_calibration"])
        self.assertEqual(result["comparisons"]["wider"]["group_count"], 1)

    def test_complexity_penalty_can_reject_an_accurate_split(self):
        logits, labels, groups, costs = self.gate_inputs()
        costs["split"]["stored_scalars"] = 2000
        result = select_candidate(logits, labels, groups, costs, replace(self.config, scalar_penalty=.001))
        self.assertFalse(result["split_supported_on_calibration"])

    def test_independent_scorer_complete_census_and_no_self_labels(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            fit_and_seal(*prepare_views(self.rows), fixture_features(self.rows), self.config, output)
            records = json.loads((output/"predictions.json").read_bytes())
            arms = tuple(sorted({p["arm"] for p in records}))
            result = score_predictions(records, self.rows, arms, 2)
            self.assertEqual(result["arms"]["frozen"]["held_out"]["rows"], 8)
            self.assertFalse(result["statistical_superiority_established"])
            for bad in (records[:-1], records+[records[0]], [dict(records[0], label=1)]+records[1:],
                        [dict(records[0], input_fingerprint="0"*64)]+records[1:]):
                with self.subTest(count=len(bad)), self.assertRaises(ValueError):
                    score_predictions(bad, self.rows, arms, 2)

    def test_write_once_refuses_nan_and_preserves_original(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/"record.json"
            with self.assertRaises(ValueError):
                write_once(p, {"bad": float("nan")})
            self.assertFalse(p.exists())
            write_once(p, {"old": 1})
            with self.assertRaises(FileExistsError):
                write_once(p, {"old": 2})
            self.assertEqual(json.loads(p.read_text()), {"old": 1})


if __name__ == "__main__":
    unittest.main()
