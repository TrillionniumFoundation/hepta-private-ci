"""Offline contract tests; toy tensors are never published as model evidence."""
import hashlib
import tempfile
import unittest
from pathlib import Path

import replacement_physical as p


class ReplacementPhysicalTests(unittest.TestCase):
    def test_file_hash_and_symlink_denial(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            good = root / "a"
            good.write_bytes(b"real-byte-exact")
            self.assertEqual(p.file_sha256(good), hashlib.sha256(b"real-byte-exact").hexdigest())
            link = root / "b"
            link.symlink_to(good)
            with self.assertRaisesRegex(ValueError, "symlink"):
                p.file_sha256(link)

    def test_checkpoint_digest_must_match_loaded_bytes(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            (root / "config.json").write_text("{}")
            (root / "tokenizer.json").write_text("{}")
            (root / "model.safetensors").write_bytes(b"test-real-bytes")
            spec = {"repository": "Snowflake/snowflake-arctic-embed-m-v2.0",
                    "revision": "a" * 40, "weight_file": "model.safetensors",
                    "weight_sha256": hashlib.sha256(b"test-real-bytes").hexdigest()}
            self.assertEqual(p.verify_checkpoint("arctic_305m", spec, root)["loaded_weight_sha256"],
                             spec["weight_sha256"])
            (root / "model.safetensors").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "differ"):
                p.verify_checkpoint("arctic_305m", spec, root)

    def test_full_policy_requires_nested_artifacts(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            (root / "config.json").write_text("{}")
            (root / "model.safetensors").write_bytes(b"test")
            spec = {"repository": "convaiinnovations/laya", "revision": "a" * 40,
                    "weight_file": "model.safetensors",
                    "weight_sha256": hashlib.sha256(b"test").hexdigest()}
            with self.assertRaisesRegex(ValueError, "rl_agent_config"):
                p.verify_checkpoint("laya_english_421m", spec, root)

    def test_fixed_class_balanced_subsampling(self):
        rows = {k: [dict(source_id=f"{k}-{i}", label=i % 4, timestamp_ms=i,
                         source_row_sha256="0" * 64) for i in range(40)]
                for k in p.SPLITS}
        selected = p.choose_rows(rows, 8)
        self.assertTrue(all(len(v) == 8 for v in selected.values()))
        self.assertEqual([x["label"] for x in selected["ood"]], [0, 1, 2, 3, 0, 1, 2, 3])
        with self.assertRaises(ValueError):
            p.choose_rows(rows, 7)
        with self.assertRaises(ValueError):
            p.choose_rows(rows, 4096)

    def test_equal_budget_training_is_deterministic(self):
        import torch
        torch.set_num_threads(2)
        features = torch.eye(4).repeat(4, 1).float()
        labels = torch.arange(4).repeat(4)
        a, temp, report = p.train_task_head(features, labels, features, labels)
        b, temp2, report2 = p.train_task_head(features, labels, features, labels)
        self.assertEqual(report["head_trained_sha256"], report2["head_trained_sha256"])
        self.assertNotEqual(report["head_trained_sha256"], report["head_initial_sha256"])
        self.assertEqual((temp, report["steps"]), (temp2, p.TRAIN_STEPS))
        self.assertFalse(any(param.requires_grad for param in a.parameters()))
        self.assertFalse(any(param.requires_grad for param in b.parameters()))


if __name__ == "__main__":
    unittest.main()
