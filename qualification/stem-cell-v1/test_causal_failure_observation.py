"""A failed neural call cannot inherit a previous successful decode receipt."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_causal_generator as fixtures
from hf_causal_generator import DecodeLimits, LocalCausalProposer
from hf_encoder_kernel import snapshot_digest
from system2_execution import PublicTask


class CausalFailureObservationTests(unittest.TestCase):
    def test_failed_call_clears_prior_success_observation(self):
        model, tokenizer = fixtures.learned_model(), fixtures.TokenizerFixture()
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / 'fixture').write_text('test only')
            with patch('hf_causal_generator.load_local_causal', return_value=(model, tokenizer, {})), \
                 patch('hf_causal_generator.verify_loaded_safetensors', return_value={}):
                proposer = LocalCausalProposer(td, expected_snapshot_sha256=snapshot_digest(td),
                                              limits=DecodeLimits(new_tokens=4))
                task = PublicTask('test prompt', 10)
                self.assertEqual(proposer(task, None, None), 'ab')
                self.assertIsNotNone(proposer.last_observation)
                with patch('hf_causal_generator.greedy_decode', side_effect=ValueError('failed decode')):
                    with self.assertRaises(ValueError):
                        proposer(task, None, None)
                self.assertIsNone(proposer.last_observation)


if __name__ == '__main__':
    unittest.main()
