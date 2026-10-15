"""Synthetic contract/adversarial tests. The separately pinned archive is audited outside fixtures."""
import hashlib
import io
import json
import unittest
import zipfile
from e3_original_archive_critical_review import (
    AuditReject, BASE, ARMS, SOURCE_HEAD, DATASET_REVISION,
    GRANITE_REVISION, DINO_REVISION, review_archive, exact_p, holm, decode, sha,
)

def canon(v):
    return (json.dumps(v, sort_keys=True, separators=(',',':'),allow_nan=False)+'\n').encode()

def fake_zip(mutate=None):
    probs=[.26,.25,.25,.24]
    train_probs=[.25,.26,.25,.24]
    rows=[{'id':f'id_{i:03}', 'group':f'group_{i:03}', 'split':'test',
           'source_input_sha256':sha(f'in_{i}'.encode()),
           'arms':{arm:(train_probs if arm=='train_gate' else probs) for arm in ARMS}}
          for i in range(64)]
    source_sha=sha(b'source')
    held=sha(b'held')
    fit=sha(b'fit')
    predictions={'schema':BASE+'.sealed-predictions','arms':list(ARMS),
                 'predictions':rows,'source_sha256':source_sha,'fit_labels_sha256':fit,
                 'stem_model':{'revision':GRANITE_REVISION},
                 'vision_model':{'revision':DINO_REVISION},
                 'held_labels_visible_to_inference':False,'production_accepted':False,
                 'physical_text_forward_batches':60,'physical_vision_forward_batches':24,
                 'fit':{'private_cell_head_parameters':769,'cell_optimizer_updates':80,
                        'organ_bridge_parameter_count':147840,
                        'train_cases':96,'calibration_cases':32,'holdout_cases':64,
                        'calibration_selected_weight':0.0}}
    report={'schema':BASE+'.independent-heldout-review','source_sha256':source_sha,
            'holdout_targets_sha256':held,'original_heldout_cases':64,
            'arms':{a:{'correct':16,'accuracy':.25,'cases':64} for a in ARMS},
            'paired_vs_text_only':{a:{'rescued_errors_vs_text':0,
                  'new_errors_vs_text':0,'discordant_cases':0,
                  'mcnemar_unadjusted_exact_p':1.0}
                    for a in ARMS if a not in ('text_only','image_masked')},
            'historical_scienceqa_release_not_future':True,
            'visual_necessity_ground_truth_adjudicated':False,
            'production_accepted':False,'authority':'DENY_ALL','stem_winner':None}
    report['sealed_predictions_sha256']=sha(canon(predictions))
    stage={'source_sha256':source_sha,'fit_labels_sha256':fit,
           'private_test_labels_sha256':held,
           'dataset_revision':DATASET_REVISION}
    files={'source-head.txt':SOURCE_HEAD.encode()+b'\n',
           'source-tree.txt':b'fixture-tree\n',
           'source-seals.json':canon(stage),
           'sealed-source-bound-predictions.json':canon(predictions),
           'independent-descriptive-review.json':canon(report),
           'offline-tests.txt':b'fake fixture only\n',
           'optimized-tests.txt':b'fake fixture only\n',
           'versions.txt':b'fake fixture only\n',
           'source-blobs-SHA256':b'fixture identity\n'}
    files['predictions-before-labels.sha256']=(sha(files['sealed-source-bound-predictions.json'])+'  predictions\n').encode()
    if mutate:mutate(files,predictions,report,stage)
    files['SHA256SUMS']=''.join(sha(data)+'  ./'+name+'\n' for name,data in sorted(files.items())).encode()
    buff=io.BytesIO()
    with zipfile.ZipFile(buff,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in files.items():z.writestr(name,data)
    raw=buff.getvalue()
    return raw,sha(raw)

class ArchiveCriticalTests(unittest.TestCase):
    def test_fixture_not_real_model(self):
        raw,s=fake_zip()
        out=review_archive(raw,s)
        self.assertFalse(out['independently_recomputed_accuracy_from_labels'])
        self.assertFalse(out['external_model_or_ground_truth_attested'])
        self.assertIsNone(out['stem_winner'])
        self.assertFalse(out['production_accepted'])
        self.assertEqual(out['observed_predictions'],64)

    def test_invalid_zip_sha_rejected(self):
        raw,s=fake_zip()
        with self.assertRaises(AuditReject):review_archive(raw,'0'*64)

    def test_removed_member_rejected(self):
        def rm(files,*_):files.pop('source-seals.json')
        raw,s=fake_zip(rm)
        with self.assertRaises(AuditReject):review_archive(raw,s)

    def test_bad_source_pair_rejected(self):
        def drift(files,_,report,stage):
            report['source_sha256']=sha(b'drift')
            files['independent-descriptive-review.json']=canon(report)
        raw,s=fake_zip(drift)
        with self.assertRaises(AuditReject):review_archive(raw,s)

    def test_calibration_mask_mismatch_rejected(self):
        def drift(files,pred,*_):
            pred['predictions'][0]['arms']['calibrated_fusion']=[.24,.25,.25,.26]
            files['sealed-source-bound-predictions.json']=canon(pred)
            files['predictions-before-labels.sha256']=(sha(files['sealed-source-bound-predictions.json'])+'  predictions\n').encode()
        raw,s=fake_zip(drift)
        with self.assertRaises(AuditReject):review_archive(raw,s)

    def test_incorrect_p_rejected(self):
        def change(files,_pred,score,*_rest):
            score['paired_vs_text_only']['train_gate']['mcnemar_unadjusted_exact_p']=0.001
            files['independent-descriptive-review.json']=canon(score)
        raw,s=fake_zip(change)
        with self.assertRaises(AuditReject):review_archive(raw,s)

    def test_false_authority_rejected(self):
        def change(files,_pred,score,*_rest):
            score['authority']='ALLOW'
            files['independent-descriptive-review.json']=canon(score)
        raw,s=fake_zip(change)
        with self.assertRaises(AuditReject):review_archive(raw,s)

    def test_wrong_source_head_rejected(self):
        def change(files,*_):files['source-head.txt']=b'wrong-sha\n'
        raw,s=fake_zip(change)
        with self.assertRaises(AuditReject):review_archive(raw,s)

    def test_nonfinite_json_rejected(self):
        with self.assertRaises(AuditReject):decode(b'{"x":NaN}')

    def test_duplicate_json_key_rejected(self):
        with self.assertRaises(AuditReject):decode(b'{"x":1,"x":2}')

    def test_mcnemar_symmetry(self):
        self.assertEqual(exact_p(14,7),exact_p(7,14))
        self.assertEqual(exact_p(0,0),1.0)
        self.assertLess(exact_p(0,12),.01)

    def test_holm_is_monotone(self):
        adj=holm({'a':0.01,'b':0.02,'c':0.6})
        self.assertAlmostEqual(adj['a'],.03)
        self.assertAlmostEqual(adj['b'],.04)
        self.assertAlmostEqual(adj['c'],.6)

if __name__=='__main__':unittest.main()
