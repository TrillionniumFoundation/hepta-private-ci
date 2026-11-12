"""Fixture-only causal replay, durable failures and real subprocess recovery."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from hepta_cells.readout_credit import ReadoutCredit
from hepta_cells.stem_credit_study import BANDS, _documents, run_credit_study


def fixture():
    rng = np.random.default_rng(44)
    rows = []
    for i in range(32):
        initial = rng.normal(0, 0.1, 64).tolist()
        for j, band in enumerate(BANDS):
            rows.append(
                dict(
                    source_group=f"source-{i:02d}",
                    split="train" if i < 24 else "dev",
                    candidate_id=band,
                    task_id=band,
                    target=(i + j) % 2,
                    initial_latent=initial,
                    candidate_latent="poison post-action payload must never be inspected",
                    observed_at_us=[10_000, 10_000 + 1000 * (j + 1)],
                    replay_exposure_us=[0, 1000 * (j + 1)],
                    receipt_sha256s=[f"{i:064x}", f"{i + 100:064x}"],
                    document_sha256=f"{i:064x}",
                    feature_profile_sha256="f" * 64,
                )
            )
    return dict(
        schema="hepta.cell.cord-retained-replay.v1",
        feature_dim=64,
        records=rows,
        fixture_only=True,
        fresh_confirmation=0,
        source_independence_verified=False,
        historical_costs={
            "scope": "synthetic integration fixture; no scientific evidence"
        },
    )


class CreditStudyTests(unittest.TestCase):
    def test_five_arm_real_subprocess_and_train_only_feedback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "DATASET.json"
            dataset.write_text(json.dumps(fixture()))
            report = run_credit_study(
                dataset, root / "run", seeds=(1101,), taus_us=(10_000_000,), passes=1
            )
            self.assertEqual(report["failed_attempts"], 0)
            self.assertTrue(report["controls"][0]["same_vector_derangement_verified"])
            self.assertEqual(len(report["attempts"]), 5)
            for row in report["attempts"]:
                self.assertTrue(row["cold_exact"])
                self.assertEqual(row["feedback_count"], 24)
                self.assertEqual(row["updates"], 0 if row["arm"] == "frozen" else 24)
                self.assertEqual(row["local_restored_predictions"], 8)
                self.assertEqual(row["ordinary_daemon_adoptions"], 0)
                folder = root / "run" / f"s1101-t10000000-{row['arm']}"
                events = [
                    json.loads(s)
                    for s in (folder / "EVENTS.jsonl").read_text().splitlines()
                ]
                feedback = [e for e in events if e["kind"] == "feedback"]
                self.assertEqual(
                    {e["source_group"] for e in feedback},
                    {f"source-{i:02d}" for i in range(24)},
                )
                for e in events:
                    if e["kind"] == "decision":
                        self.assertNotIn("targets", e["row"])
                        self.assertEqual(e["row"]["reference_logits"], [0, 0, 0])
                cold = json.loads((folder / "COLD_REQUEST.json").read_text())
                self.assertEqual(set(cold["dev_docs"][0]), {"source_group", "initial"})
            self.assertTrue((root / "run" / "MANIFEST.json").is_file())

    def test_label_conflicts_and_cross_split_document_aliases_are_refused(self):
        data = fixture()
        self.assertEqual(len(_documents(data)), 32)
        broken = copy.deepcopy(data)
        broken["records"][1]["initial_latent"] = list(
            broken["records"][1]["initial_latent"]
        )
        broken["records"][1]["initial_latent"][0] = 99
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            _documents(broken)
        broken = copy.deepcopy(data)
        for row in broken["records"][72:75]:
            row["document_sha256"] = broken["records"][0]["document_sha256"]
        with self.assertRaisesRegex(ValueError, "reused"):
            _documents(broken)
        broken = copy.deepcopy(data)
        broken["records"][1]["replay_exposure_us"][1] += 1
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            _documents(broken)

    def test_failed_fit_keeps_started_cost_and_recoverable_pending_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "DATASET.json"
            dataset.write_text(json.dumps(fixture()))
            with patch.object(
                ReadoutCredit,
                "feedback",
                side_effect=ValueError("injected fit failure"),
            ):
                report = run_credit_study(
                    dataset,
                    root / "run",
                    seeds=(1101,),
                    taus_us=(10_000_000,),
                    passes=1,
                )
            self.assertEqual(report["failed_attempts"], 5)
            for row in report["attempts"]:
                self.assertGreater(row["attempted_readout_mac"], 0)
                self.assertEqual(row["attempted_feedback_calls"], 1)
                folder = root / "run" / f"s1101-t10000000-{row['arm']}"
                checkpoint = json.loads((folder / "FAILED_STATE.json").read_text())
                self.assertEqual(len(checkpoint["pending"]), 1)
                self.assertEqual(checkpoint["optimizer"]["updates"], 0)
                self.assertEqual(row["error"], "injected fit failure")


if __name__ == "__main__":
    unittest.main()
