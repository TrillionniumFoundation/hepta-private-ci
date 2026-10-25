"""Synthetic integrity and statistical-unit checks; not new scientific evidence."""

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import cell_field_closure_data as data
import cell_field_closure_evaluate as evaluation
from cell_field_closure_audit import (direct_cost, predictions_from_state, replay_branch,
                                     verify_candidate_members, verify_seal)
from cell_field_closure_control import closure_maps, fixed_actions
from cell_field_closure_evaluate import paired_interval, source_scores
from cell_field_closure_run import seal
from cell_field_action_control import score_common
from cell_field_control import build_reference
from cell_field_state import CellTrainingState, dataset_digest
from cell_learning_models import NumpyCellHead


class EvidenceTests(unittest.TestCase):
    def test_registered_source_owner_blocks_repreparation_in_a_new_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            plan = {"source_owner_directory": str(root / "owner")}
            protocol = root / "protocol.json"
            data.write(protocol, plan)
            original = root / "owner/data"
            original.mkdir(parents=True)
            with patch.object(data, "_read_archive") as source_read:
                with self.assertRaises(FileExistsError):
                    data.prepare("unused", "unused", "unused", "unused", protocol, original)
                with self.assertRaisesRegex(ValueError, "registered source owner"):
                    data.prepare("unused", "unused", "unused", "unused", protocol, root / "new-output/data")
                source_read.assert_not_called()
            self.assertFalse((root / "new-output").exists())

    def test_final_access_remains_at_original_owner_across_output_names_and_copies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            plan = {"source_owner_directory": str(root / "owner")}
            original, copied = root / "owner/data", root / "copied/data"
            original.mkdir(parents=True)
            copied.mkdir(parents=True)
            data.claim_final_access(plan, original, {"outputs": "first", "failure_consumes_sources": True})
            with self.assertRaises(FileExistsError):
                data.claim_final_access(plan, original, {"outputs": "new-evaluation-output"})
            with self.assertRaisesRegex(ValueError, "registered source owner"):
                data.claim_final_access(plan, copied, {"outputs": "copied-source-output"})
            self.assertFalse((copied / "final_access_v4.json").exists())
            with patch.object(evaluation, "verify_run", return_value=(plan, {})):
                with self.assertRaisesRegex(ValueError, "registered source owner"):
                    evaluation.preflight(root / "unused-run", copied, root / "unused-audit")

    def test_source_owner_rejects_missing_relative_and_symlink_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            owner = root / "owner"
            owner.mkdir()
            alias = root / "alias"
            alias.symlink_to(owner, target_is_directory=True)
            for plan, source in (({}, owner / "data"),
                                 ({"source_owner_directory": "relative"}, owner / "data"),
                                 ({"source_owner_directory": str(alias)}, alias / "data"),
                                 ({"source_owner_directory": str(owner)}, alias / "data")):
                with self.subTest(plan=plan, source=source), self.assertRaises(ValueError):
                    data.registered_source_directory(plan, source)
            (owner / "data").symlink_to(root / "other", target_is_directory=True)
            with self.assertRaises(ValueError):
                data.registered_source_directory({"source_owner_directory": str(owner)}, owner / "data")

    def test_class_stratification_preserves_fixed_class_effects(self):
        labels = np.repeat(np.arange(4), 16)
        effects = np.repeat([-1.0, 0.5, -0.25, 0.25], 16)
        result = paired_interval(effects, labels)
        np.testing.assert_array_equal(result["interval"], [-0.125, -0.125])
        self.assertTrue(result["passes"])
        self.assertEqual(result["quantiles"], [0.05 / 12, 1 - 0.05 / 12])
        self.assertFalse(paired_interval(np.zeros(64), labels)["passes"])

    def test_probability_metric_and_invalid_payload(self):
        labels = np.tile(np.arange(4), 4)
        nll, accuracy = source_scores(np.full((16, 4), 0.25), labels)
        np.testing.assert_allclose(nll, np.log(4), atol=0, rtol=0)
        self.assertEqual(accuracy.mean(), 0.25)
        with self.assertRaises(ValueError):
            source_scores(np.full((16, 4), 0.2), labels)
        with self.assertRaises(ValueError):
            source_scores(np.full((16, 4), 0.25), labels.astype(float))

    def test_seal_rejects_changed_bytes_and_additions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data.write(root / "evidence.json", {"value": 1})
            seal(root, "test-seal.json")
            verify_seal(root, "test-seal.json", exact=True)
            data.write(root / "unregistered.json", {"value": 2})
            with self.assertRaisesRegex(ValueError, "extra"):
                verify_seal(root, "test-seal.json", exact=True)
            (root / "unregistered.json").unlink()
            (root / "evidence.json").write_text('{"value":2}\n')
            with self.assertRaisesRegex(ValueError, "differs"):
                verify_seal(root, "test-seal.json")

    def test_seal_rejects_traversal_before_reading_outside(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data.write(root / "test-seal.json", {"schema": "hepta.cell-closure-seal.v4",
                "files": {"../outside": {"sha256": "invalid", "bytes": 1}}})
            with self.assertRaisesRegex(ValueError, "escapes"):
                verify_seal(root, "test-seal.json")

    def test_candidate_seal_requires_every_forecast_and_excludes_actual_branches(self):
        candidates = {"anchors": [{"id": "anchor"}], "warmups": [{"id": "warm", "path": "warm.npz"}]}
        plan = {"arms": ["loss2", "history2", "history4", "moment4", "full"]}
        names = ["source-freeze.json", "projection.npz", "new-projected-features.npz", "protocol.json",
                 "inputs.json", "candidates.json", "warm.npz", "warm-warm-receipts.json",
                 "anchor/checkpoint/state.npz", "anchor/checkpoint/manifest.json", "anchor/reference.npz",
                 "anchor/actions.npz", "anchor/forecast.json", "anchor/loss2-forecast.npz",
                 "anchor/history2-forecast.npz", "anchor/history4-forecast.npz",
                 "anchor/moment4-forecast.npz", "anchor/full-forecast.npz"]
        manifest = {"files": dict.fromkeys(names, {})}
        verify_candidate_members(manifest, candidates, plan)
        for changed in ({}, {k: v for k, v in manifest["files"].items() if k != "anchor/history4-forecast.npz"},
                        {**manifest["files"], "anchor/action-00.npz": {}},
                        {**manifest["files"], "runs.json": {}}):
            with self.assertRaisesRegex(ValueError, "candidate seal"):
                verify_candidate_members({"files": changed}, candidates, plan)

    def test_separate_direct_cost_includes_positive_retention_and_impulse_effort(self):
        rng = np.random.default_rng(885)
        plan = {"horizon": 8, "h": 0.02, "direct_coefficient": 0.03, "effort_price": 0.1}
        fields, baseline = rng.normal(size=(9, 2)), rng.normal(size=(9, 2))
        action = rng.normal(size=36)
        sequence = np.zeros((8, 36))
        sequence[0] = action
        expected = score_common(fields, sequence, baseline, 0.2)["direct_soft_total"]
        self.assertAlmostEqual(direct_cost(fields, action, baseline, 0.2, plan), expected, places=14)

    def test_existing_adam_state_matches_real_impulse_and_saved_prediction_audit(self):
        rng = np.random.default_rng(886)
        old, current, probe = [rng.normal(size=(16, 8)) for _ in range(3)]
        labels = np.tile(np.arange(4), 4)
        contexts = {"old": dataset_digest(old, labels), "current": dataset_digest(current, labels)}
        for mode in ("linear", "gated"):
            state = CellTrainingState(NumpyCellHead(8, 4, mode), bindings={"scope": "synthetic-unit-test"},
                                      contexts=contexts, active_context="old")
            for _ in range(64):
                state.advance(old, labels)
            state.select_context("current")
            reference = build_reference(state, current, labels, probes=((probe, labels), (old, labels)), horizon=8)
            action = fixed_actions(state.parameter_count)[1]
            branch = state.clone()
            states, observations, receipts = [branch.vector()], [reference.observe(branch.vector())[0][:2]], []
            receipts.append(branch.advance(current, labels, intervention=0.02 * action))
            expected = reference.states[1].copy()
            expected[:state.parameter_count] += 0.02 * action
            np.testing.assert_array_equal(branch.vector(), expected)
            states.append(branch.vector())
            observations.append(reference.observe(branch.vector())[0][:2])
            for _ in range(7):
                receipts.append(branch.advance(current, labels))
                states.append(branch.vector())
                observations.append(reference.observe(branch.vector())[0][:2])
            states, observations = np.asarray(states), np.asarray(observations)
            self.assertEqual(replay_branch(state, (current, labels), ((probe, labels), (old, labels)),
                                           states, observations, receipts, action, 0.02), 8)
            changed = observations.copy()
            changed[4, 0] += 0.01
            with self.assertRaises(AssertionError):
                replay_branch(state, (current, labels), ((probe, labels), (old, labels)),
                              states, changed, receipts, action, 0.02)
            changed_receipts = [dict(receipt) for receipt in receipts]
            changed_receipts[5]["context"] = "wrong-context"
            with self.assertRaisesRegex(ValueError, "receipt differs"):
                replay_branch(state, (current, labels), ((probe, labels), (old, labels)),
                              states, observations, changed_receipts, action, 0.02)
            np.testing.assert_allclose(predictions_from_state(branch.vector(), mode, probe),
                                       branch.head.predict_proba(probe), atol=0, rtol=0)
            for arm in ("loss2", "history2", "history4", "moment4", "full"):
                maps, metadata = closure_maps(reference, arm)
                self.assertEqual(maps.shape, (9, 2, state.parameter_count))
                self.assertTrue(np.isfinite(maps).all())
                self.assertTrue(metadata["full_state_calibration_required"])

    def test_full_component_exclusion_and_reserve_are_source_disjoint(self):
        def row(identity, month, label, group=None, text=None):
            stamp = int(datetime(2014, month, 12, tzinfo=timezone.utc).timestamp() * 1000)
            return {"source_id": identity, "source_group_id": group or identity,
                    "text": text or identity, "label": label, "timestamp_ms": stamp,
                    "publisher": "fixture publisher", "source_row_sha256": data.sha(identity.encode())}

        ordinary = [row(f"fresh-{month}-{label}-{number}", month, label)
                    for month in (4, 7) for label in range(4) for number in range(3)]
        # Transitive story/title links must exclude all three, including the unseen member.
        first = [row("prior-a", 4, 0, "story-a", "title-a"),
                 row("prior-b", 4, 0, "story-a", "title-b"),
                 row("prior-c", 4, 0, "story-b", "title-b")]
        prior_groups = [first, [row("prior-v2", 4, 1)], [row("prior-v3", 7, 2)]]
        legacy = [row("legacy-a", 4, 0, text="legacy title"), row("legacy-b", 4, 0, text="legacy title")]
        excluded = [row("cross-a", 4, 0, "cross"), row("cross-b", 7, 0, "cross"),
                    row("conflict-a", 4, 0, "conflict"), row("conflict-b", 4, 1, "conflict")]
        rows = ordinary + [r for group in prior_groups for r in group] + legacy + excluded
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths, pins = [], {}
            for name, group in zip(("v1", "v2", "v3"), prior_groups):
                identities = sorted(r["source_id"] for r in group)
                path = root / (name + ".json")
                identity = data.write(path, {"rows": [{"raw_source_id": identities[0],
                    "component_id": "news-group:" + data.sha(identities),
                    "component_member_count": len(identities), "component_members_sha256": data.sha(identities)}]})
                paths.append(str(path))
                pins[name] = identity["sha256"]
            protocol = root / "protocol.json"
            data.write(protocol, {"source_owner_directory": str(root.resolve()),
                "source_salt": "explicit-synthetic-test-only", "new_source_plan": [
                {"role": "old_test_v4", "month": "2014-04", "rows": 4},
                {"role": "future_july_v4", "month": "2014-07", "rows": 4}]})
            with patch.object(data, "PINS", pins), patch.object(data, "_read_archive", return_value=rows), \
                 patch.object(data, "select_rows", return_value={"train": [legacy[0]]}), \
                 patch.object(data, "publisher_is_ood", return_value=False):
                result = data.prepare("unused-fixture-archive", *paths, str(protocol), str(root / "data"))
            self.assertEqual(result["selected_components"], 8)
            self.assertEqual(result["reserved_components"], 16)
            self.assertEqual(result["excluded_counts"], {"prior": 3, "legacy": 1, "cross_month": 1, "conflict": 1})
            sources = json.loads((root / "data/sources.json").read_bytes())["rows"]
            reserve = json.loads((root / "data/reserved_components.json").read_bytes())
            selected_ids = {r["component_id"] for r in sources}
            expected = {"news-group:" + data.sha([r["source_id"]]) for r in ordinary}
            self.assertEqual(selected_ids | set(reserve["component_ids"]), expected)
            self.assertFalse(selected_ids & set(reserve["component_ids"]))
            self.assertFalse(reserve["labels_or_titles_emitted"])


if __name__ == "__main__":
    unittest.main()
