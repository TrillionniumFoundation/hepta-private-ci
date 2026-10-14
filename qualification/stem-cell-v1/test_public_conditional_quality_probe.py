"""Score-only owner path does not load weights, run training or reselect arms."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import torch
from safetensors.torch import save_file

from conditioned_panel_study import build_panel, train_panel
from matrix_materials import file_sha256
from matrix_runtime import write_json_exclusive
from next_round_matrix import _digest
from public_conditional_quality_probe import score
import test_conditioned_panel_study as fixtures


class SealedConditionalScoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.root=tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.root.cleanup)
        cls.folder=Path(cls.root.name)
        train,eval_rows,_=build_panel('a'*64,train_groups=2,eval_groups=1)
        obs,banks=train_panel(train,eval_rows,evidence_encoder=fixtures.ToyEncoder(),
                              query_encoder=fixtures.ToyQuery(),checkpoint_sha256='a'*64,
                              steps=32,policy=fixtures.POLICY)
        write_json_exclusive(cls.folder/'predictions.json',obs)
        write_json_exclusive(cls.folder/'execution.json',{'test_only':True})
        for name,bank in banks.items():
            save_file({k:v.detach().contiguous() for k,v in bank.state_dict().items()},
                      str(cls.folder/(name+'.safetensors')))
        names=('predictions.json','execution.json')+tuple(name+'.safetensors' for name in banks)
        manifest=dict(schema='hepta.public-two-fact-prediction-seal.v1',
                observation_id=obs['observation_id'],files={name:file_sha256(cls.folder/name) for name in names},
                score_not_yet_computed=True,production_authorized=False)
        manifest['seal_id']=_digest(manifest)
        write_json_exclusive(cls.folder/'COMMITTED.json',manifest)
        cls.seal=manifest['seal_id']

    def test_scores_only_after_exact_prediction_seal_and_without_retraining(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('conditional_evidence.fit_reader',side_effect=AssertionError('must not train')):
                result=score(self.folder,expected_seal_id=self.seal,output=Path(tmp)/'scores')
            self.assertEqual(result['schema'],'hepta.conditioned-facts-evaluation.v1')
            self.assertFalse(result['statistical_superiority_established'])
            self.assertEqual(result['label_source'],'deterministic_public_synthetic_oracle_not_independent_human_annotations')
            self.assertTrue((Path(tmp)/'scores'/'COMMITTED.json').is_file())
            with self.assertRaises(FileExistsError):
                score(self.folder,expected_seal_id=self.seal,output=Path(tmp)/'scores')

    def test_mismatched_externally_retained_identity_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                score(self.folder,expected_seal_id='f'*64,output=Path(tmp)/'no-output')
            self.assertFalse((Path(tmp)/'no-output').exists())

    def test_changed_bank_weights_refused_before_label_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp)/'run'
            import shutil
            shutil.copytree(self.folder,run)
            weight=run/'conditioned.safetensors'
            weight.write_bytes(weight.read_bytes()+b' ')
            with self.assertRaises(ValueError):
                score(run,expected_seal_id=self.seal,output=Path(tmp)/'no-output')
            self.assertFalse((Path(tmp)/'no-output').exists())

    def test_partial_or_failed_seal_not_considered_successful(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp)/'run'
            import shutil
            shutil.copytree(self.folder,run)
            (run/'FAILED.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'failed model run'):
                score(run,expected_seal_id=self.seal,output=Path(tmp)/'no-output')

    def test_cli_help_is_available_without_transformers(self):
        import subprocess,sys
        root=Path(__file__).with_name('public_conditional_quality_probe.py')
        for args in (['--help'],['run','--help'],['score','--help']):
            result=subprocess.run([sys.executable,str(root),*args],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
