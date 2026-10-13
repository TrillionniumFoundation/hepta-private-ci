"""Required official HF/PEFT fixture parity. No skip if dependencies are absent."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
import torch
from peft import LoraConfig, get_peft_model
import test_five_reader_evidence_pairs as fixtures
import five_reader_response_learning as learning
import five_reader_evidence_pairs as pairs
import assistant_projection as p


class OfficialProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): torch.set_num_threads(1)
    def backend(self):
        backend=fixtures.backend(); backend.loaded.config._attn_implementation='eager'
        return backend
    def test_all_paired_lora_gradients_match(self):
        for objective in pairs.OBJECTIVES:
            with self.subTest(objective=objective),torch.random.fork_rng():
                torch.manual_seed(31); backend=self.backend()
                config=LoraConfig(r=4,lora_alpha=8,target_modules=['q_proj','v_proj'],task_type='CAUSAL_LM')
                full=get_peft_model(backend.loaded,config).eval()
                # Nonzero B ensures the comparison also exercises A gradients.
                with torch.no_grad():
                    for n,v in full.named_parameters():
                        if 'lora_B' in n: v.normal_(0,.02)
                selected=deepcopy(full); p.qualify_model(full); p.qualify_model(selected)
                batch,_=pairs.prepare(backend.tokenizer,fixtures.examples(),position_cap=128)[0]
                a,_=pairs.backward_pair(full,batch,objective)
                b,_=pairs.backward_pair(selected,batch,objective,projection_profile=p.ASSISTANT)
                torch.testing.assert_close(a,b,rtol=1e-5,atol=1e-6)
                for (n,x),(m,y) in zip(full.named_parameters(),selected.named_parameters()):
                    self.assertEqual(n,m)
                    if x.requires_grad: torch.testing.assert_close(x.grad,y.grad,rtol=2e-4,atol=2e-7)
    def test_existing_trainer_selected_path_saved_reload_and_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            a,b=self.backend(),self.backend()
            x=learning.fit_response_adapter(a,fixtures.examples(),Path(folder)/'full',epochs=1,loss_profile=pairs.MARGIN)
            with p.projection_meter(b.loaded) as metric:
                y=learning.fit_response_adapter(b,fixtures.examples(),Path(folder)/'selected',epochs=1,
                                                loss_profile=pairs.MARGIN,projection_profile=p.ASSISTANT)
            self.assertEqual(x['initial_adapter_sha256'],y['initial_adapter_sha256'])
            self.assertEqual(y['training_forwards'],8)
            self.assertEqual(metric['head_calls'],8)
            self.assertEqual(metric['projected_positions'],y['scored_response_tokens_processed'])
            self.assertTrue(y['checkpoint_reload_equal'] and y['base_unchanged'])
            self.assertNotIn('vocabulary_projection',x['loss_objective'])
            self.assertEqual(y['loss_objective']['vocabulary_projection'],p.ASSISTANT)
            for n,v in a.loaded.state_dict().items():
                torch.testing.assert_close(v,b.loaded.state_dict()[n],rtol=2e-4,atol=2e-6)
    def test_single_response_profile_rejected_before_output_or_wrap(self):
        backend=self.backend()
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'no'
            with self.assertRaises(ValueError):
                learning.fit_response_adapter(backend,fixtures.examples(),out,projection_profile=p.ASSISTANT)
            self.assertFalse(out.exists()); self.assertFalse(hasattr(backend.loaded,'peft_config'))
    def test_unknown_projection_rejected_before_call(self):
        backend=self.backend(); batch,_=pairs.prepare(backend.tokenizer,fixtures.examples(),position_cap=128)[0]
        with self.assertRaises(ValueError): pairs.sequence_score(backend.loaded,batch['variants'][0][0],'unknown')
    def test_training_mode_and_wrong_model_fail_closed(self):
        backend=self.backend(); backend.loaded.train()
        with self.assertRaises(ValueError): p.qualify_model(backend.loaded)
        with self.assertRaises(ValueError): p.qualify_model(torch.nn.Linear(2,2))


if __name__=='__main__': unittest.main()
