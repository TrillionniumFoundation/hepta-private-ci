"""Mandatory stock Transformers BERT buffer tests; no downloads or skipped cases.

These tests require the pinned HF environment used by the real-weight lane.
The tiny random BERT fixtures validate loading semantics, NOT pretrained quality.
"""
import tempfile
import unittest
from pathlib import Path

import torch
from safetensors.torch import save_file
from transformers import AutoModel, BertConfig, BertModel
from transformers.models.bert.modeling_bert import BertEmbeddings

from hf_joint_decision_runner import validate_encoder_loading_info, verify_loaded_safetensors
from hf_tensor_materialization_checks import cloned_state, snapshot_hashes


class BertBufferMaterializationChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        torch.manual_seed(315)
        self.config = BertConfig(vocab_size=29, hidden_size=8, num_hidden_layers=1,
                                 num_attention_heads=2, intermediate_size=16,
                                 max_position_embeddings=16, hidden_dropout_prob=0.0,
                                 attention_probs_dropout_prob=0.0)
        self.model = BertModel(self.config).eval()
        self.state = cloned_state(self.model)
        self.positions = self.model.embeddings.position_ids.detach().clone()
        self.key = "embeddings.position_ids"

    def save(self, positions=None, state=None):
        tensors = self.state.copy() if state is None else state.copy()
        tensors[self.key] = self.positions if positions is None else positions
        self.config.save_pretrained(str(self.root))
        save_file(tensors, str(self.root / "model.safetensors"), metadata={"format": "pt"})

    def verify(self, model=None):
        return verify_loaded_safetensors(torch, self.model if model is None else model,
                                         self.root)

    def load(self):
        return AutoModel.from_pretrained(str(self.root), local_files_only=True,
                                         trust_remote_code=False, use_safetensors=True,
                                         output_loading_info=True)

    def test_actual_nonpersistent_buffer_compared_without_rewriting(self):
        self.save()
        before = snapshot_hashes(self.root)
        receipt = self.verify()
        self.assertNotIn(self.key, self.model.state_dict())
        self.assertEqual(receipt["verified_nonpersistent_buffer_keys"], [self.key])
        self.assertEqual(receipt["tensor_count"], len(self.state) + 1)
        self.assertEqual(receipt["state_dict_tensor_count"], len(self.state))
        self.assertEqual(receipt["tensor_elements"], sum(x.numel() for x in self.state.values()) + 16)
        self.assertEqual(snapshot_hashes(self.root), before)
        self.assertFalse(receipt["production_authorization"])

    def test_real_from_pretrained_and_forward_match_original(self):
        self.save()
        loaded, info = self.load()
        validate_encoder_loading_info(info)
        self.assertTrue(self.verify(loaded)["complete"])
        ids = torch.tensor([[1, 2, 3, 0], [4, 5, 6, 7]])
        with torch.inference_mode():
            original = self.model(ids).last_hidden_state
            actual = loaded.eval()(ids).last_hidden_state
        self.assertTrue(torch.equal(original, actual))

    def test_clean_hf_report_does_not_hide_corrupted_position_bytes(self):
        self.save(self.positions + 1)
        loaded, info = self.load()
        validate_encoder_loading_info(info)
        with self.assertRaisesRegex(ValueError, "ordinal"):
            self.verify(loaded)

    def test_changed_loaded_buffer_rejected(self):
        self.save()
        self.model.embeddings.position_ids[0, 0] = 1
        with self.assertRaisesRegex(ValueError, "ordinal"):
            self.verify()

    def test_equal_but_noncanonical_source_and_loaded_values_rejected(self):
        changed = self.positions + 1
        self.save(changed)
        self.model.embeddings.position_ids.copy_(changed)
        with self.assertRaisesRegex(ValueError, "ordinal"):
            self.verify()

    def test_float_positions_not_silently_cast(self):
        self.save(self.positions.float())
        with self.assertRaisesRegex(ValueError, "dtype"):
            self.verify()

    def test_int32_positions_rejected(self):
        self.save(self.positions.int())
        with self.assertRaisesRegex(ValueError, "dtype"):
            self.verify()

    def test_one_dimensional_positions_rejected(self):
        self.save(self.positions[0])
        with self.assertRaisesRegex(ValueError, "shape"):
            self.verify()

    def test_truncated_positions_rejected(self):
        self.save(self.positions[:, :-1].contiguous())
        with self.assertRaisesRegex(ValueError, "shape"):
            self.verify()

    def test_loaded_float_buffer_rejected(self):
        self.save()
        self.model.embeddings.position_ids = self.positions.float()
        with self.assertRaisesRegex(ValueError, "dtype"):
            self.verify()

    def test_meta_position_buffer_rejected(self):
        self.save()
        self.model.embeddings.position_ids = torch.empty((1, 16), dtype=torch.int64, device="meta")
        with self.assertRaisesRegex(ValueError, "shape or dtype"):
            self.verify()

    def test_unregistered_position_attribute_rejected(self):
        self.save()
        del self.model.embeddings.position_ids
        self.model.embeddings.position_ids = self.positions
        with self.assertRaisesRegex(ValueError, "registered"):
            self.verify()

    def test_config_cannot_enlarge_actual_position_table(self):
        self.save()
        self.config.max_position_embeddings = 17
        with self.assertRaisesRegex(ValueError, "capacity"):
            self.verify()

    def test_capacity_is_bounded_before_ordinal_allocation(self):
        self.save()
        self.config.max_position_embeddings = 1 << 40
        with self.assertRaisesRegex(ValueError, "capacity"):
            self.verify()

    def test_buffer_does_not_cover_missing_learned_tensor(self):
        self.save(state={k: v for k, v in self.state.items() if k != "pooler.dense.weight"})
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.verify()

    def test_other_even_equal_nonpersistent_buffer_rejected(self):
        self.save(state={**self.state,
                         "embeddings.token_type_ids": self.model.embeddings.token_type_ids.clone()})
        with self.assertRaisesRegex(ValueError, "unexpected"):
            self.verify()

    def test_duplicate_position_buffer_across_shards_rejected(self):
        self.save()
        save_file({self.key: self.positions}, str(self.root / "duplicate.safetensors"))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.verify()

    def test_subclassed_model_is_not_implicitly_admitted(self):
        class OtherBert(BertModel):
            pass
        self.save()
        other = OtherBert(self.config)
        other.load_state_dict(self.state)
        with self.assertRaisesRegex(ValueError, "unexpected"):
            self.verify(other)

    def test_subclassed_embedding_is_not_implicitly_admitted(self):
        class OtherEmbeddings(BertEmbeddings):
            pass
        self.save()
        other = OtherEmbeddings(self.config)
        other.load_state_dict(self.model.embeddings.state_dict())
        self.model.embeddings = other
        with self.assertRaisesRegex(ValueError, "nonstandard"):
            self.verify()

    def test_float_weight_cast_keeps_integer_position_identity(self):
        self.save()
        self.model.to(dtype=torch.bfloat16)
        self.assertTrue(self.verify()["complete"])
        self.assertEqual(self.model.embeddings.position_ids.dtype, torch.int64)

    def test_modern_snapshot_without_legacy_buffer_remains_valid(self):
        save_file(self.state, str(self.root / "model.safetensors"))
        self.assertEqual(self.verify()["verified_nonpersistent_buffer_keys"], [])

    def test_failure_never_repairs_source_or_loaded_buffer(self):
        bad = self.positions + 1
        self.save(bad)
        before = snapshot_hashes(self.root)
        loaded_before = self.model.embeddings.position_ids.clone()
        with self.assertRaises(ValueError):
            self.verify()
        self.assertEqual(snapshot_hashes(self.root), before)
        self.assertTrue(torch.equal(self.model.embeddings.position_ids, loaded_before))


if __name__ == "__main__":
    unittest.main()
