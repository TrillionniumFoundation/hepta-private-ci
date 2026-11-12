import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from hepta_cells.stem_plastic_study import prepare, run, TASKS


def fixture(path):
    rng = np.random.default_rng(5)
    records = []
    for split, count in (("train", 24), ("dev", 8)):
        for i in range(count):
            initial = rng.normal(size=64).tolist()
            for task in TASKS:
                records.append(
                    dict(
                        source_group=f"{split}-{i:02}",
                        candidate_id=task,
                        split=split,
                        initial_latent=initial,
                        candidate_latent=[1e20] * 64,
                        target=int(initial[0] > 0),
                        document_sha256=hashlib.sha256(
                            f"{split}-{i}".encode()
                        ).hexdigest(),
                        feature_profile_sha256="a" * 64,
                        receipt_sha256s=[
                            hashlib.sha256(f"initial-{split}-{i}".encode()).hexdigest(),
                            "b" * 64,
                        ],
                    )
                )
    path.write_text(
        json.dumps(
            dict(
                schema="hepta.cell.cord-retained-replay.v1",
                feature_dim=64,
                fresh_confirmation=0,
                source_independence_verified=False,
                records=records,
            )
        )
    )


class PlasticStudyTests(unittest.TestCase):
    def test_information_is_pre_action_and_sources_are_grouped(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "data.json"
            fixture(path)
            first, _ = prepare(path)
            data = json.loads(path.read_text())
            for row in data["records"]:
                row["candidate_latent"] = [-1e20] * 64
            path.write_text(json.dumps(data))
            second, _ = prepare(path)
            for key in first:
                np.testing.assert_array_equal(first[key][0], second[key][0])
            for row in data["records"][-3:]:
                row["document_sha256"] = data["records"][0]["document_sha256"]
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                prepare(path)
            fixture(path)
            data = json.loads(path.read_text())
            data["records"][0]["source_group"] = "dev-00"
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                prepare(path)

    def test_real_training_owner_consumption_and_subprocess_recovery(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            path = root / "data.json"
            fixture(path)
            result = run(path, root / "out", seeds=(1,), ranks=(1,), updates=1)
            self.assertEqual(result["promotion"], "NoUpdate")
            self.assertEqual(len(result["outcomes"]), 4)
            self.assertEqual(sum(r["updates"] for r in result["outcomes"]), 18)
            self.assertTrue(all(r["cold_process_equal"] for r in result["outcomes"]))
            for r in result["outcomes"]:
                report = json.loads(
                    (root / "out" / r["run"] / "RESULT.json").read_text()
                )
                self.assertTrue(report["fresh_post_recovery_inference_equal"])
                if r["config"]["arm"] in ("independent", "frozen_backbone"):
                    self.assertTrue(
                        all(
                            v == 0
                            for p in report["phase_interference"]
                            for v in p["other_task_max_change"].values()
                        )
                    )

    def test_declared_large_rank_has_explicit_owner_budget(self):
        from hepta_cells.lifecycle import CellOwner
        from hepta_cells.plastic_bank import PlasticBank
        from hepta_cells.stem_plastic_study import serve

        with tempfile.TemporaryDirectory() as root:
            owner = CellOwner(Path(root) / "owner.sqlite")
            try:
                bank = PlasticBank("shared_plastic", 64, 12, TASKS)
                prediction, receipt = serve(
                    owner, bank, "upper", np.ones((8, 64)), "source", "budget-probe"
                )
                self.assertEqual(prediction.shape, (8, 1))
                self.assertGreater(receipt["work_units"], 10000)
            finally:
                owner.close()
            with self.assertRaises(ValueError):
                run(Path(root) / "absent", Path(root) / "not-created", updates=70)


if __name__ == "__main__":
    unittest.main()
