"""Second authentic publisher panel; strict original source identity and nonclaims."""
from __future__ import annotations
import copy
import os
from pathlib import Path
import tempfile
import unittest
from fabric import Denied
from agnews_crossfamily import evaluate, read_original

ARCHIVE = os.getenv('AGNEWS_ORIGINAL_ARCHIVE')

class StaticCases(unittest.TestCase):
    def test_missing_source_denied(self):
        with self.assertRaises(Denied):read_original(Path('/impossible/no-agnews-original.zip'))

    def test_synthetic_no_original_cannot_claim(self):
        with self.assertRaises(Denied):evaluate({})

    def test_zip_byte_tamper_denied(self):
        with tempfile.TemporaryDirectory() as d:
            file=Path(d)/'malformed.zip';file.write_bytes(b'fake archive')
            with self.assertRaises(Denied):read_original(file)

    def test_symlink_to_archived_artifact_denied(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/'payload';target.write_bytes(b'invalid')
            (Path(d)/'link').symlink_to(target)
            with self.assertRaises(Denied):read_original(Path(d)/'link')

@unittest.skipUnless(ARCHIVE, 'requires byte-verified historical second-publisher Actions artifact')
class OriginalCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet=read_original(Path(ARCHIVE))

    def test_original_mmbert_head_vs_cheap_priors(self):
        report=evaluate(self.packet)
        self.assertEqual(report['original_feature_rows'],128)
        self.assertEqual(report['held_rows'],32)
        self.assertEqual(report['correct']['gated'],22)
        self.assertEqual(report['correct']['route_prior'],8)
        self.assertEqual(report['correct']['global_prior'],8)
        self.assertEqual(report['paired']['gated']['wins_vs_route_prior'],15)
        self.assertEqual(report['paired']['gated']['losses_vs_route_prior'],1)
        self.assertAlmostEqual(report['paired']['gated']['nominal_posthoc_exact_p'],0.000518798828125)
        self.assertFalse(report['independent_blind_heldout_custody'])
        self.assertFalse(report['cell_split_causal_gain_verified'])
        self.assertEqual((report['disposition'],report['authority']),('HOLD_NO_GO','DENY_ALL'))

    def test_altered_probability_is_denied(self):
        x=copy.deepcopy(self.packet)
        import json
        key='execution/predictions.json';data=json.loads(x[key]);data['predictions'][0]['probabilities']=[.99,0.,0.,.99]
        x[key]=json.dumps(data).encode()
        with self.assertRaises(Denied):evaluate(x)

    def test_changed_original_source_route_is_denied(self):
        x=copy.deepcopy(self.packet)
        import json
        key='dataset.jsonl';data=[json.loads(v) for v in x[key].splitlines()]
        data[0]['cell']=1-data[0]['cell']
        x[key]=('\n'.join(json.dumps(v) for v in data)).encode()
        with self.assertRaises(Denied):evaluate(x)

    def test_duplicate_prediction_is_denied(self):
        x=copy.deepcopy(self.packet)
        import json
        key='execution/predictions.json';data=json.loads(x[key]);data['predictions'][1]=data['predictions'][0]
        x[key]=json.dumps(data).encode()
        with self.assertRaises(Denied):evaluate(x)

if __name__=='__main__':unittest.main()
