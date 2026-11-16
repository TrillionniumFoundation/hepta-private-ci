"""Small mathematical/custody regressions; these are not measured calibration."""

import copy
from pathlib import Path
import struct
import tempfile
import unittest

from .neuron_calibration import ACTIONS, Q24, canonical, completed_registration, metrics, project, scores, sha, summarize


def bits(value):
    return struct.unpack("<I", struct.pack("<f", value))[0]


def seal(row):
    row["row_sha256"] = sha(canonical({k: v for k, v in row.items() if k != "row_sha256"}))
    return row


def rows():
    result = []
    for index in range(640, 768):
        ordinal = (index - 640) % 64
        row = {"pair_index": index, "cohort": "calibration" if index < 704 else "verification",
               "action": ACTIONS[ordinal % 4], "predeclared_ood": ordinal >= 32,
               "source_ids": [f"source:{2 * index}", f"source:{2 * index + 1}"],
               "pixel_hashes": [sha(str(2 * index).encode()), sha(str(2 * index + 1).encode())],
               "previous_state": {"values_f32": [0] * 384}, "current_state": {"values_f32": [0] * 384},
               "joint_success": True, "metrics": {"caption_valid": True, "text_fact": 0, "relation": 0,
                                                   "image_fact": 0, "crossmodal_disagreement": 0},
               **scores([0] * 384, [0] * 384)}
        result.append(seal(row))
    return result


class NeuronCalibrationTests(unittest.TestCase):
    def test_projection_uses_each_block_and_preserves_sign(self):
        expected = project([bits(1.)] * 384)
        self.assertTrue(all(0 < value < Q24 for value in expected))
        for block in range(4):
            value = [0] * 384
            value[96 * block] = bits(4.)
            self.assertEqual(project(value), [expected[0]] + [0] * 95)
        self.assertEqual(project([bits(-1.)] * 384), [-v for v in expected])
        for bad in ([0] * 383, [bits(float("nan"))] * 384, [bits(8.1)] * 384, [True] * 384):
            with self.assertRaises(ValueError):
                project(bad)

    def test_ood_far_uses_ood_denominator_not_semantic_error_or_selection(self):
        value = metrics([
            {"confidence_ppm": 1_000_000, "ood_ppm": 0, "joint_success": True, "predeclared_ood": False},
            {"confidence_ppm": 500_000, "ood_ppm": 500_000, "joint_success": False, "predeclared_ood": True},
        ])
        self.assertEqual((value["ece_ppm"], value["ood_false_acceptance_ppm"]), (250_000, 1_000_000))
        self.assertEqual((value["coverage"], value["semantic_false_acceptance_among_incorrect"]), (.5, 0.))
        with self.assertRaisesRegex(ValueError, "nonempty"):
            metrics([{"confidence_ppm": 1, "ood_ppm": 1, "joint_success": True, "predeclared_ood": False}])

    def test_complete_census_keeps_negative_ood_result(self):
        result = summarize(rows())
        self.assertFalse(result["point_gates_passed"])
        self.assertEqual((result["native_measured_ece_ppm"], result["native_measured_false_acceptance_ppm"]), (0, 1_000_000))
        self.assertEqual(set(result["stratum_counts"].values()), {8})

    def test_missing_duplicate_pair_and_source_are_rejected(self):
        base = rows()
        candidates = [base[:-1], base[:-1] + [base[0]]]
        reused = copy.deepcopy(base)
        reused[-1]["source_ids"] = reused[0]["source_ids"]
        candidates.append(reused)
        for candidate in candidates:
            seal(candidate[-1])
            with self.assertRaises(ValueError):
                summarize(candidate)

    def test_resealed_score_and_label_tamper_are_rejected(self):
        for field, value in (("confidence_ppm", 999_999), ("joint_success", False), ("predeclared_ood", True)):
            candidate = rows()
            candidate[0][field] = value
            seal(candidate[0])
            with self.assertRaises(ValueError):
                summarize(candidate)

    def test_original_completion_rejects_renamed_or_replaced_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model, reward = b"original model", b"original reward"
            protocol = {"source": {"dirty": False, "git_commit": "b98961ceb71414490e1c6ae397cf635bca3093f4"},
                        "seeds": [17, 29, 43], "study_id": "conditioned-heteroskedastic-002",
                        "dataset_manifest": {"manifest_sha256": "a" * 64}}
            summary = {"source": protocol["source"], "protocol_sha256": sha(canonical(protocol)),
                       "checkpoint_files": {"seed-17-terminal_entropic_ndu": {"snapshot_file_sha256": sha(model)}},
                       "observer_binding": {"reward_artifact_sha256": sha(reward)},
                       "observer": {"weights_sha256": {"reward": sha(reward)}}}
            expected = sha(canonical(summary))
            status = {"state": "completed", "rows": 7560, "summary_sha256": expected}
            for name, value in (("protocol", protocol), ("summary", summary), ("status", status)):
                (root / f"{name}.json").write_bytes(canonical(value))
            (root / "seed-17-terminal_entropic_ndu.pt").write_bytes(model)
            (root / "reward-observer.pt").write_bytes(reward)
            self.assertEqual(completed_registration(root, expected)["model_file_sha256"], sha(model))
            (root / "seed-17-terminal_entropic_ndu.pt").write_bytes(b"same name, another model")
            with self.assertRaisesRegex(ValueError, "bytes changed"):
                completed_registration(root, expected)
            with self.assertRaisesRegex(ValueError, "preregistered"):
                completed_registration(root)


if __name__ == "__main__":
    unittest.main()
