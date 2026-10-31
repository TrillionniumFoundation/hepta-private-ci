"""Synthetic summary fixtures exercise pairing and gates without confirmation data."""

from copy import deepcopy
import gzip
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from ..round4.runtime_codec import Decoder, Encoder
from ..round4.runtime_law import make_law, release_law
from ..statistics import paired_interval
from . import summary
from .data import ARMS, DOMAINS, SEEDS


def synthetic_scopes(differences=None):
    scopes = {}
    differences = [.02] * len(SEEDS) if differences is None else differences
    for seed_index, seed in enumerate(SEEDS):
        for domain in DOMAINS:
            arms = {}
            for arm in ARMS:
                mode = arm if arm in ("event", "direct", "float") else "float"
                law = make_law([1.0], [0.0], [.25])
                decoder = Decoder(mode)
                decoder.apply(Encoder(mode).encode(law, 1, 1.0, "observed"))
                released = release_law(law, -.5, .5)
                released.update(native_vs_reference_max_absolute_error=0.0,
                                native_mixture_probabilities=released["physical_probabilities"])
                stage = {"public": {"initial": 0.0, "repair_cost": .25},
                         "runtime": {"decoder": decoder.snapshot(), "law": released}}
                arms[arm] = []
                for index in range(2):
                    value = differences[seed_index] + index * .001 if arm == "analytic" else 0.0
                    arms[arm].append({"index": index, "arm": arm, "utility": value,
                        "cost": 0.0, "squared_error": 0.0, "wall_ns": 1, "cpu_ns": 1,
                        "packet_bytes": 1, "native_requests": 1, "native_ticks": 1,
                        "native_roundtrip_ns": 1, "evidence_archive_wall_ns": 1,
                        "actions": ["stop"], "delivered": 0.0, "target": 0.0,
                        "stages": [deepcopy(stage)]})
            scopes[seed, domain] = arms
    return scopes


def run_synthetic(scopes, calibration_pass=True):
    seen = []

    def observed_interval(matrix, *arguments):
        seen.append(np.asarray(matrix))
        return paired_interval(matrix, *arguments)

    with tempfile.TemporaryDirectory() as directory:
        with patch.object(summary, "verify"), patch.object(summary, "load_scopes", return_value=(scopes, {})), \
                patch.object(summary, "first_stage_metrics", return_value={"calibration_pass": calibration_pass}), \
                patch.object(summary, "paired_interval", side_effect=observed_interval):
            result = summary.summarize(directory, "a" * 64)
    return result, seen


class SummaryContract(unittest.TestCase):
    def test_pairing_preserves_training_clusters_and_whole_trajectories(self):
        result, matrices = run_synthetic(synthetic_scopes())
        np.testing.assert_allclose(matrices[0], np.tile([.02, .021], (5, 1)), rtol=0, atol=1e-15)
        primary = result["primary"]["analytic-numeric"]
        self.assertEqual(primary["training_seed_count"], 5)
        self.assertEqual(primary["trajectories_per_seed"], 2)
        self.assertTrue(primary["passes_registered_superiority"])
        self.assertTrue(result["joint_research_gate_pass"])
        self.assertFalse(result["production_promotion"])

    def test_positive_aggregate_does_not_override_negative_seed(self):
        result, _ = run_synthetic(synthetic_scopes([-.002, .02, .02, .02, .02]))
        primary = result["primary"]["analytic-numeric"]
        self.assertGreater(primary["mean_difference"], .005)
        self.assertGreater(primary["interval"][0], 0)
        self.assertLess(min(primary["per_seed_mean_difference"]), 0)
        self.assertFalse(primary["passes_registered_superiority"])

    def test_calibration_failure_blocks_joint_gate_despite_utility_gain(self):
        result, _ = run_synthetic(synthetic_scopes(), calibration_pass=False)
        self.assertTrue(result["all_primary_gates_pass"])
        self.assertFalse(result["joint_research_gate_pass"])

    def test_actual_decoder_coordinates_ignore_mode_but_detect_state_change(self):
        scopes = synthetic_scopes()
        result, _ = run_synthetic(scopes)
        self.assertEqual(result["equivalence"]["event-direct"]["decoded_coordinate_mismatches"], 0)
        scopes[SEEDS[0], DOMAINS[0]]["direct"][0]["stages"][0]["runtime"]["decoder"]["values"][0] += 1
        result, _ = run_synthetic(scopes)
        self.assertEqual(result["equivalence"]["event-direct"]["decoded_coordinate_mismatches"], 1)
        self.assertEqual(result["equivalence"]["event-direct"]["maximum_probability_error"], 0)

    def test_first_stage_calibration_excludes_selected_second_stage(self):
        rows = synthetic_scopes()[SEEDS[0], DOMAINS[0]]["event"]
        expected = summary.first_stage_metrics(rows)
        for row in rows:
            row["stages"].append({"deliberately_unusable_selected_stage": True})
        self.assertEqual(summary.first_stage_metrics(rows), expected)
        self.assertEqual(expected["independent_sample_count"], 2)
        self.assertEqual(expected["horizon_measurements_per_trajectory"], 1)

    def test_loader_sorts_pairing_and_rejects_duplicate_or_rescored_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "confirmation/seed_1/unit"
            folder.mkdir(parents=True)
            (folder / "DATA.npz").write_bytes(b"synthetic inventory fixture; no data arrays")
            rows = [{"index": i, "arm": arm, "utility": 1.0, "delivered": 0.0,
                     "target": 0.0, "cost": 0.0, "final_readback_ns": 1, "score_started_ns": 2}
                    for i in reversed(range(128)) for arm in ("left", "right")]

            def write_fixture():
                with gzip.open(folder / "ROWS.json.gz", "wt") as stream:
                    json.dump(rows, stream)
                report = {"namespace": "registered", "rows_sha256": summary.sha(folder / "ROWS.json.gz"),
                    "data_sha256": summary.sha(folder / "DATA.npz"), "seed": 1, "domain": "unit",
                    "independent_trajectories": 128}
                (folder / "SUMMARY.json").write_text(json.dumps(report))
                (folder / "RUN_COMPLETED.json").write_text(json.dumps({"namespace": "registered",
                    "summary_sha256": summary.sha(folder / "SUMMARY.json")}))

            with patch.object(summary, "SEEDS", (1,)), patch.object(summary, "DOMAINS", ("unit",)), \
                    patch.object(summary, "ARMS", ("left", "right")):
                write_fixture()
                scopes, _ = summary.load_scopes(root)
                self.assertEqual([r["index"] for r in scopes[1, "unit"]["left"]], list(range(128)))
                original = rows[-1]
                rows[-1] = deepcopy(rows[0])
                write_fixture()
                with self.assertRaises(ValueError):
                    summary.load_scopes(root)
                rows[-1] = original
                rows[0]["utility"] = .9
                write_fixture()
                with self.assertRaises(ValueError):
                    summary.load_scopes(root)


if __name__ == "__main__":
    unittest.main()
