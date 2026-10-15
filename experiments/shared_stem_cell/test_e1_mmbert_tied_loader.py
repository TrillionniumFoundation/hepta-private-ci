"""Offline mmBERT tied-weight integrity tests; actual safetensors, no model network."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import torch
from safetensors.torch import save_file
from e1_mmbert_tied_loader import verify_tied_pretrained_table, verify_complete_pretrained_state, Invalid


def synthetic(tied=True):
    torch.manual_seed(123)
    weights=torch.arange(9*384,dtype=torch.float32).reshape(9,384).clone()/100
    source=weights.clone()
    embedding=torch.nn.Parameter(weights)
    decoder=embedding if tied else torch.nn.Parameter(weights.clone())
    model=SimpleNamespace(
        model=SimpleNamespace(embeddings=SimpleNamespace(tok_embeddings=SimpleNamespace(weight=embedding))),
        decoder=SimpleNamespace(weight=decoder))
    return model,source


class TestMMBertSourceTie(unittest.TestCase):
    def run_case(self, change=None, tied=True, expect_pass=False):
        model,source=synthetic(tied)
        if change is not None:
            change(model,source)
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'model.safetensors'
            save_file({'decoder.weight':source},str(target))
            if expect_pass:
                actual=verify_tied_pretrained_table(torch,model,target)
                self.assertTrue(actual['actual_local_full_tied_embedding_checkpoint_verified'])
                self.assertFalse(actual['publisher_signature_independently_verified'])
                self.assertEqual(len(actual['complete_table_sha256']),64)
            else:
                with self.assertRaises(Invalid):
                    verify_tied_pretrained_table(torch,model,target)

    def check_complete_state(self, tamper=None, expect_success=False):
        class TinyMLM(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.model=torch.nn.Module()
                self.model.embeddings=torch.nn.Module()
                self.model.embeddings.tok_embeddings=torch.nn.Embedding(9,384)
                self.decoder=torch.nn.Linear(384,9,bias=False)
                self.decoder.weight=self.model.embeddings.tok_embeddings.weight
                self.head=torch.nn.Linear(384,384)
        model=TinyMLM()
        saved={k:v.detach().clone() for k,v in model.state_dict().items()
               if k!='decoder.weight'}
        if tamper:tamper(model,saved)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'model.safetensors'
            save_file(saved,str(path))
            if expect_success:
                result=verify_complete_pretrained_state(torch,model,path)
                self.assertTrue(result['all_serialized_pretrained_tensor_bytes_verified'])
                self.assertEqual(result['source_tensor_count'],len(saved))
            else:
                with self.assertRaises(Invalid):verify_complete_pretrained_state(torch,model,path)
    def test_full_checkpoint_covers_all_non_alias_weights(self):
        self.check_complete_state(expect_success=True)
    def test_full_checkpoint_rejects_modified_hidden_layer(self):
        self.check_complete_state(lambda model,saved:saved['head.weight'].__setitem__((0,0),99.))
    def test_full_checkpoint_rejects_unsaved_random_layer(self):
        self.check_complete_state(lambda model,saved:saved.pop('head.weight'))
    def test_full_checkpoint_rejects_extra_unmapped_weight(self):
        self.check_complete_state(lambda model,saved:saved.update({'unexpected.weight':torch.ones(2)}))
    def test_exact_source_bytes_and_tied_real_tensor(self):self.run_case(expect_pass=True)
    def test_mlm_decoder_not_tied(self):self.run_case(tied=False)
    def test_newly_initialized_embedding_detected(self):
        def edit(m,s):
            with torch.no_grad():m.model.embeddings.tok_embeddings.weight[0]+=2
        self.run_case(edit)
    def test_checkpoint_bytes_tampered(self):
        self.run_case(lambda m,s:s.__setitem__((0,0),-9))
    def test_middle_vocabulary_byte_corruption_is_not_ignored(self):
        self.run_case(lambda m,s:s.__setitem__((5,123),-42))
    def test_wrong_embedding_width(self):
        def edit(m,s):
            m.model.embeddings.tok_embeddings.weight=torch.nn.Parameter(torch.ones(9,128))
        self.run_case(edit)
    def test_zero_embedding_is_not_pretraining(self):
        def edit(m,s):
            with torch.no_grad():m.model.embeddings.tok_embeddings.weight.zero_()
            s.zero_()
        self.run_case(edit)


if __name__=='__main__':unittest.main()
