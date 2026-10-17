"""Source-only model-loader integrity negatives, no physical pretrained model claims."""
import copy
import sys
import types
import unittest
from pathlib import Path

for name in ('paired_review_v5','selective_route_v8','stem_candidate_v1'):
    if name not in sys.modules and not any((Path(__file__).resolve().parents[1]/d/(name+'.py')).exists()
            for d in ('stem-optimal-v1','stem-optimal-v5','stem-optimal-v8')):
        sys.modules[name]=types.ModuleType(name)
import pretrained_load_diag_v12 as d


class LoaderSafetyTests(unittest.TestCase):
    def test_loader_failure_metadata_is_explicit_and_incomplete(self):
        data=d.failed_loading_info(
            RuntimeError('meta tensor'), loader_class='AutoModelForMaskedLM',
            base_model_class='unavailable')
        self.assertFalse(data['model_base_weights_complete'])
        self.assertEqual(data['error_count'],1)
        self.assertEqual(data['complete_model_resident_parameter_scalars'],0)
        self.assertEqual(data['loader_class'],'AutoModelForMaskedLM')

    def test_empty_full_base_loader_metadata(self):
        data=d.loading_info({'missing_keys':[], 'unexpected_keys':[],
                             'mismatched_keys':[], 'error_msgs':[]})
        self.assertTrue(data['model_base_weights_complete'])
        self.assertEqual(data['missing_key_count'],0)

    def test_original_mmbert_missing_embedding_must_disqualify(self):
        data=d.loading_info({'missing_keys':['embeddings.tok_embeddings.weight'],
                             'unexpected_keys':['head.dense.weight'],
                             'mismatched_keys':[], 'error_msgs':[]})
        self.assertFalse(data['model_base_weights_complete'])
        self.assertEqual(data['missing_keys'],['embeddings.tok_embeddings.weight'])
        self.assertEqual(data['unexpected_key_count'],1)

    def test_mismatched_size_or_error_also_disqualifies(self):
        for field,payload in (('mismatched_keys',[('a',(1,2),(2,1))]),
                              ('error_msgs',['pretrained parameter failed'])):
            info={'missing_keys':[], 'unexpected_keys':[],
                  'mismatched_keys':[], 'error_msgs':[]}
            info[field]=payload
            result=d.loading_info(info)
            self.assertFalse(result['model_base_weights_complete'])
            self.assertTrue(result[field.replace('error_msgs','error_messages')] if field!='mismatched_keys'
                            else result['mismatched_keys'])

    def test_unverified_or_malformed_loading_info_fails_closed(self):
        for value in (None,[],{}, {'missing_keys':'embeddings.weight'},
                      {'missing_keys':[0]}, {'unexpected_keys':[None]}):
            if value == {}: continue  # empty dict is equivalent to an all-empty loading-info receipt
            with self.assertRaises(ValueError):d.loading_info(value)

    def test_truncation_never_hides_missing_key_count(self):
        data=d.loading_info({'missing_keys':['parameter'+str(i) for i in range(37)]})
        self.assertEqual(data['missing_key_count'],37)
        self.assertEqual(len(data['missing_keys']),30)
        self.assertFalse(data['model_base_weights_complete'])

    def test_only_registered_checkpoint_profiles(self):
        self.assertEqual(d.PROFILES['granite47'],('auto_model',))
        self.assertEqual(d.PROFILES['granite97'],('auto_model',))
        self.assertEqual(d.PROFILES['mmbert140'],('auto_model','full_mlm'))
        self.assertNotIn('auto_model_full_random_embedding',d.PROFILES['mmbert140'])

    def test_byte_check_stream_matches_hashlib(self):
        import tempfile,hashlib
        with tempfile.TemporaryDirectory() as dpath:
            p=Path(dpath)/'model.safetensors'
            p.write_bytes(b'synthetic-only, never real material')
            self.assertEqual(d.sha256_path(p),hashlib.sha256(p.read_bytes()).hexdigest())


if __name__=='__main__':unittest.main()
