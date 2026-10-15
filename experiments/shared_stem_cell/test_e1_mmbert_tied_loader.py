"""Offline mmBERT tied-weight integrity tests; actual safetensors, no model network."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import torch
from safetensors.torch import save_file
from e1_mmbert_tied_loader import verify_tied_pretrained_table, Invalid


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

    def test_exact_source_bytes_and_tied_real_tensor(self):self.run_case(expect_pass=True)
    def test_mlm_decoder_not_tied(self):self.run_case(tied=False)
    def test_newly_initialized_embedding_detected(self):
        def edit(m,s):
            with torch.no_grad():m.model.embeddings.tok_embeddings.weight[0]+=2
        self.run_case(edit)
    def test_checkpoint_bytes_tampered(self):
        self.run_case(lambda m,s:s.__setitem__((0,0),-9))
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
