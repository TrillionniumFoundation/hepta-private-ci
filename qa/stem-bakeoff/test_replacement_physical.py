"""Offline contract tests; toy tensors are never published as model evidence."""
import hashlib
import tempfile
import unittest
from pathlib import Path

import replacement_physical as p


class ReplacementPhysicalTests(unittest.TestCase):
    def test_arctic_cpu_custom_attention_is_explicit_and_fail_closed(self):
        from types import SimpleNamespace
        config = SimpleNamespace(use_memory_efficient_attention="true",
                                 unpad_inputs="true")
        observed = p.configure_arctic_cpu(config)
        self.assertEqual(observed, {"use_memory_efficient_attention": "true",
                                    "unpad_inputs": "true"})
        self.assertIs(config.use_memory_efficient_attention, False)
        self.assertIs(config.unpad_inputs, False)
        for invalid in (None, 1, "yes", [], object()):
            with self.subTest(invalid=repr(invalid)):
                bad = SimpleNamespace(use_memory_efficient_attention=invalid,
                                      unpad_inputs="true")
                with self.assertRaisesRegex(ValueError, "unexpected pinned Arctic"):
                    p.configure_arctic_cpu(bad)


    def test_arctic_nonpersistent_rope_buffer_reconstruction_strict(self):
        from types import SimpleNamespace
        import torch

        class RotaryEmbedding(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.dim = 64
                self.base = 160000
                self.max_position_embeddings = 8192
                self.max_seq_len_cached = 8192
                self.register_buffer("inv_freq", torch.full((32,), float("nan")), persistent=False)
                self.register_buffer("cos_cached", torch.full((8192, 64), float("nan")), persistent=False)
                self.register_buffer("sin_cached", torch.full((8192, 64), float("nan")), persistent=False)

        class GteEmbeddings(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.register_buffer("position_ids", torch.full(
                    (8192,), 9223372036854775807, dtype=torch.long), persistent=False)
                self.rotary_emb = RotaryEmbedding()

        class GteModel(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.config = SimpleNamespace(
                    max_position_embeddings=8192, hidden_size=768, num_attention_heads=12,
                    rope_theta=160000, rope_scaling=None, position_embedding_type="rope",
                    use_memory_efficient_attention=False, unpad_inputs=False)
                self.embeddings = GteEmbeddings()
                self.weight = torch.nn.Parameter(torch.tensor([3.0]))

        model = GteModel()
        before = p.tensor_digest(model)
        receipt = p.restore_arctic_nonpersistent_buffers(model)
        self.assertEqual(receipt["method"], "pinned_gte_runtime_buffers_v1")
        self.assertFalse(receipt["original_position_buffer_valid"])
        self.assertFalse(receipt["original_rope_cache_valid"])
        self.assertIs(receipt["production_qualified"], False)
        self.assertEqual(before, p.tensor_digest(model))
        self.assertEqual(model.embeddings.position_ids[:13].tolist(), list(range(13)))
        rotary = model.embeddings.rotary_emb
        self.assertTrue(torch.all(torch.isfinite(rotary.cos_cached)))
        self.assertTrue(torch.all(torch.isfinite(rotary.sin_cached)))
        self.assertTrue(torch.allclose(rotary.cos_cached[0], torch.ones(64)))
        self.assertTrue(torch.allclose(rotary.sin_cached[0], torch.zeros(64)))
        self.assertEqual(rotary.max_seq_len_cached, 8192)

        # Rerun is deterministic and never reclassifies a test as a real model execution.
        repeat = p.restore_arctic_nonpersistent_buffers(model)
        self.assertTrue(repeat["original_position_buffer_valid"])
        self.assertTrue(repeat["original_rope_cache_valid"])
        model.config.rope_scaling = {"type": "ntk", "factor": 2}
        with self.assertRaisesRegex(ValueError, "unexpected pinned Arctic"):
            p.restore_arctic_nonpersistent_buffers(model)
        self.assertEqual(before, p.tensor_digest(model))

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
