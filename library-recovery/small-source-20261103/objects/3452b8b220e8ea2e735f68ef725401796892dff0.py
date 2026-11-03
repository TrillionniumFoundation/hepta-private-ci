"""Pure PyTorch and safetensors stress tests: synthetic fixtures only."""
import hashlib
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

import torch
from torch import nn
from safetensors.torch import save_file

from multimodal_exact_tied_alias_v11 import EMBEDDING, DECODER, same_physical_view
from multimodal_saved_tie_recovery_v18 import (
    OriginalTieRecoveryError, recover_saved_tie,
)
from public_stem_material_v8 import PINNED_RELEASES


class ModernBertForMaskedLM(nn.Module):
    """Class-name fixture, NOT genuine Transformers model/material evidence."""
    def __init__(self, vocab=12, width=4):
        super().__init__()
        self.config = SimpleNamespace(model_type='modernbert', tie_word_embeddings=True,
                                      vocab_size=vocab, hidden_size=width)
        self.model = nn.Module()
        self.model.embeddings = nn.Module()
        self.model.embeddings.tok_embeddings = nn.Embedding(vocab, width, device='meta')
        self.decoder = nn.Linear(width, vocab, bias=False, device='meta')
    def get_input_embeddings(self):
        return self.model.embeddings.tok_embeddings


# A hostile Python interpreter could forge a class name, but downloaded weights
# are never allowed to execute code. This fixture only tests the internal CPU
# tensor mechanics; the hosted test uses genuine installed Transformers class.
ModernBertForMaskedLM.__module__ = 'transformers.models.modernbert.modeling_modernbert'


class OriginalSavedAliasTests(unittest.TestCase):
    def setUp(self):
        self.tdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tdir.cleanup)
        self.root = Path(self.tdir.name)
        self.model = ModernBertForMaskedLM()
        self.tensor = torch.arange(48, dtype=torch.float32).reshape(12,4)
        self.info = dict(missing_keys=[], unexpected_keys=[], mismatched_keys=[], error_msgs=[])
    def snapshot(self, values, revision=None):
        path=self.root/'model.safetensors'
        save_file(values,path)
        sha=hashlib.sha256(path.read_bytes()).hexdigest()
        return {'revision':revision or PINNED_RELEASES['mmbert-small'],
                'kind':'masked_lm','files':{'model.safetensors':sha}}

    def test_embedding_only_restores_immutable_original_shared_storage(self):
        manifest=self.snapshot({EMBEDDING:self.tensor})
        result=recover_saved_tie(self.model,self.info,self.root,manifest)
        self.assertEqual(result['saved_tensor_name'],EMBEDDING)
        self.assertFalse(result['production_accepted'])
        state=self.model.state_dict()
        self.assertTrue(torch.equal(state[EMBEDDING],self.tensor))
        self.assertTrue(same_physical_view(state[EMBEDDING],state[DECODER]))
        self.assertIsNone(recover_saved_tie(self.model,self.info,self.root,manifest))

    def test_decoder_only_is_original_source_not_random_fallback(self):
        manifest=self.snapshot({DECODER:self.tensor})
        result=recover_saved_tie(self.model,self.info,self.root,manifest)
        self.assertEqual(result['saved_tensor_name'],DECODER)
        self.assertTrue(torch.equal(self.model.get_input_embeddings().weight,self.tensor))
        self.assertTrue(same_physical_view(self.model.decoder.weight,self.model.get_input_embeddings().weight))

    def test_both_saved_aliases_must_match_bitwise(self):
        manifest=self.snapshot({EMBEDDING:self.tensor, DECODER:self.tensor.clone()})
        self.assertEqual(recover_saved_tie(self.model,self.info,self.root,manifest)['saved_alias_count'],2)
        self.model = ModernBertForMaskedLM()
        manifest=self.snapshot({EMBEDDING:self.tensor, DECODER:self.tensor + 1})
        with self.assertRaisesRegex(OriginalTieRecoveryError,'disagree'):
            recover_saved_tie(self.model,self.info,self.root,manifest)
        self.assertTrue(self.model.decoder.weight.is_meta)

    def test_no_saved_alias_and_corrupt_or_wrong_revision_fail_closed(self):
        manifest=self.snapshot({'unrelated.weight':torch.ones(2,2)})
        with self.assertRaisesRegex(OriginalTieRecoveryError,'no original serialized'):
            recover_saved_tie(self.model,self.info,self.root,manifest)
        manifest=self.snapshot({EMBEDDING:self.tensor})
        with self.assertRaisesRegex(OriginalTieRecoveryError,'revision'):
            recover_saved_tie(self.model,self.info,self.root,{**manifest,'revision':'f'*40})
        (self.root/'model.safetensors').write_bytes(b'corrupted')
        with self.assertRaisesRegex(OriginalTieRecoveryError,'checksum'):
            recover_saved_tie(self.model,self.info,self.root,manifest)

    def test_wrong_source_geometry_and_unapproved_meta_fail(self):
        manifest=self.snapshot({EMBEDDING:torch.zeros(13,4)})
        with self.assertRaisesRegex(OriginalTieRecoveryError,'geometry'):
            recover_saved_tie(self.model,self.info,self.root,manifest)
        self.model.register_buffer('other',torch.ones(3,device='meta'))
        manifest=self.snapshot({EMBEDDING:self.tensor})
        with self.assertRaisesRegex(OriginalTieRecoveryError,'unapproved Meta tensors'):
            recover_saved_tie(self.model,self.info,self.root,manifest)

    def test_unexpected_loader_failures_and_no_weight_model_rejected(self):
        manifest=self.snapshot({EMBEDDING:self.tensor})
        for bad in (dict(self.info,unexpected_keys=['mystery']),dict(self.info,missing_keys=['mlp.weight'])):
            with self.subTest(bad=bad),self.assertRaisesRegex(OriginalTieRecoveryError,'loading report'):
                recover_saved_tie(self.model,bad,self.root,manifest)
        class Fake(nn.Module):
            def __init__(self):
                super().__init__()
                self.weight=nn.Parameter(torch.empty(1,device='meta'))
        with self.assertRaisesRegex(OriginalTieRecoveryError,'unapproved Meta tensors'):
            recover_saved_tie(Fake(),self.info,self.root,manifest)


if __name__=='__main__':unittest.main()
