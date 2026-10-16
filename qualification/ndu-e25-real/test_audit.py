"""Original ZIP-backed, fail-closed and adversarial tests; no fake new-efficacy cases."""
import copy
import importlib.util
import json
import os
import pathlib
import tempfile
import unittest
import zipfile

P = pathlib.Path(__file__).with_name('audit.py')
spec=importlib.util.spec_from_file_location('ndu_e25_source_reviewer', P)
a=importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
EVIDENCE=os.environ.get('E25_ORIGINAL_INPUTS')
EXTRACTED=os.environ.get('E25_EXTRACTED_INPUTS')


class OriginalSourceAndMutations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if (EVIDENCE is None) == (EXTRACTED is None):
            raise RuntimeError('set exactly one original ZIP input or SHA-pinned extracted Actions input')
        root=pathlib.Path(EVIDENCE or EXTRACTED)
        def get(kind,name):
            if EXTRACTED:
                return a.read_automatic_unzip(root,kind,name)
            return a.zip_member(root/f'{kind}.zip',kind,name)
        cls.public=get('public','blind_slate.json')
        cls.src=get('public','source.json')
        cls.owner=get('owner','human-labels.json')
        cls.model=get('model','sealed-new-six-blind-model-predictions.json')
        cls.score=get('score','fixed-pretrained-new-six-original-human-question-score.json')
        cls.items=(cls.public,cls.src,cls.owner,cls.model,cls.score)

    def mutate(self,index,fn):
        o=copy.deepcopy(self.items)
        fn(o[index])
        with self.assertRaises((ValueError,KeyError,TypeError)):
            a.recount(*o)

    def test_real_original_score(self):
        report=a.recount(*self.items)
        self.assertEqual((report['unique_new_passage_groups'],report['unique_new_questions'],report['original_human_candidate_alternatives']), (6,12,51))
        self.assertEqual(report['methods']['question_softworst_tau_001']['complete_questions'],2)
        self.assertEqual(report['methods']['e16_scaled_brier_5']['complete_questions'],1)
        self.assertEqual(report['methods']['no_evidence']['complete_questions'],1)
        self.assertEqual(report['e24_vs_e16_whole_question_paired'],dict(wins=1,losses=0,ties=11))
        self.assertFalse(report['NDU_executed_on_new_six'])
        self.assertFalse(report['new_independent_dataset_family'])

    def test_original_zip_archive_refuses_false_sha(self):
        with tempfile.TemporaryDirectory() as d:
            out=pathlib.Path(d)/'bad.zip'
            out.write_bytes((pathlib.Path(EVIDENCE)/'owner.zip').read_bytes()+b'X' if EVIDENCE else b'not an original zip')
            with self.assertRaises(ValueError):a.zip_member(out,'owner','human-labels.json')

    def test_original_workflow_evidence_rerun(self):
        with tempfile.TemporaryDirectory() as d:
            path=pathlib.Path(d)/'result.json'
            r=a.run(EVIDENCE or EXTRACTED,path,extracted=bool(EXTRACTED))
            self.assertEqual(json.loads(path.read_text()),r)
            with self.assertRaises(FileExistsError):a.run(EVIDENCE or EXTRACTED,path,extracted=bool(EXTRACTED))

    def test_valid_extracted_member_path(self):
        with tempfile.TemporaryDirectory() as d:
            out=pathlib.Path(d)
            for kind,members in a.MEMBERS.items():
                (out/kind).mkdir()
                for n in members:
                    if EXTRACTED:
                        (out/kind/n).write_bytes((pathlib.Path(EXTRACTED)/kind/n).read_bytes())
                    else:
                        with zipfile.ZipFile(pathlib.Path(EVIDENCE)/f'{kind}.zip') as z:
                            (out/kind/n).write_bytes(z.read(n))
            result_path=out/'result.json'
            r=a.run(out,result_path,extracted=True)
            self.assertEqual(r['unique_new_questions'],12)
            (out/'owner'/'human-labels.json').write_bytes(b'{}')
            with self.assertRaises(ValueError):a.read_automatic_unzip(out,'owner','human-labels.json')

    def test_gold_label_change(self):
        k=next(iter(self.owner['labels']))
        self.mutate(2,lambda o:o['labels'].__setitem__(k,1-o['labels'][k]))

    def test_gold_bool_label(self):
        k=next(iter(self.owner['labels']))
        self.mutate(2,lambda o:o['labels'].__setitem__(k,True))

    def test_gold_extra(self):self.mutate(2,lambda o:o['labels'].__setitem__('unknown',0))
    def test_gold_removed(self):self.mutate(2,lambda o:o['labels'].pop(next(iter(o['labels']))))
    def test_missing_original_slate_question(self):self.mutate(0,lambda o:o['rows'][0]['questions'].pop())
    def test_missing_alternative(self):self.mutate(0,lambda o:o['rows'][0]['questions'][0]['candidates'].pop())
    def test_original_source_duplicate(self):self.mutate(0,lambda o:o['rows'].append(copy.deepcopy(o['rows'][0])))
    def test_changed_original_source_group(self):self.mutate(0,lambda o:o['rows'][0].__setitem__('source_group','fake'))
    def test_old_as_new(self):self.mutate(1,lambda o:o['old_source_groups'].__setitem__(0,o['new_source_groups'][0]))
    def test_incomplete_old_count(self):self.mutate(1,lambda o:o['old_source_groups'].pop())
    def test_fake_independent_family(self):self.mutate(1,lambda o:o.__setitem__('future_time_or_independent_family',True))
    def test_false_source_census(self):self.mutate(1,lambda o:o.__setitem__('full_unused_source_census_before_model',False))
    def test_fake_production_source(self):self.mutate(1,lambda o:o.__setitem__('production_accepted',True))
    def test_incomplete_candidate_census(self):self.mutate(1,lambda o:o.__setitem__('new_candidate_count',50))
    def test_model_dropped_candidate(self):self.mutate(3,lambda o:o['rows'].pop())
    def test_model_extra_candidate(self):self.mutate(3,lambda o:o['rows'].append(copy.deepcopy(o['rows'][0])))
    def test_model_changed_task_binding(self):self.mutate(3,lambda o:o['rows'][0].__setitem__('task_id','wrong'))
    def test_model_changed_candidate_binding(self):self.mutate(3,lambda o:o['rows'][0].__setitem__('candidate_id',-1))
    def test_missing_frozen_arm(self):self.mutate(3,lambda o:o['rows'][0]['probabilities'].pop('e16_scaled_brier_5'))
    def test_fabricated_ndu_arm(self):self.mutate(3,lambda o:o['rows'][0]['probabilities'].__setitem__('ndu_new',.5))
    def test_changed_frozen_probability(self):self.mutate(3,lambda o:o['rows'][0]['probabilities'].__setitem__('question_softworst_tau_001',0.01))
    def test_nonfinite_probability(self):self.mutate(3,lambda o:o['rows'][0]['probabilities'].__setitem__('no_evidence',float('nan')))
    def test_boolean_probability(self):self.mutate(3,lambda o:o['rows'][0]['probabilities'].__setitem__('no_evidence',True))
    def test_negative_probability(self):self.mutate(3,lambda o:o['rows'][0]['probabilities'].__setitem__('no_evidence',-0.01))
    def test_invalid_source_seal(self):self.mutate(3,lambda o:o.__setitem__('source_panel_id','wrong'))
    def test_label_read_before_original_seal(self):self.mutate(3,lambda o:o.__setitem__('human_validation_labels_read_before_seal',True))
    def test_false_reproduced_reader(self):self.mutate(3,lambda o:o.__setitem__('historical_reader_weights_reproduced',False))
    def test_zero_new_model_calls(self):self.mutate(3,lambda o:o.__setitem__('new_original_candidate_reader_forward_calls',0))
    def test_changed_human_score(self):self.mutate(4,lambda o:o['methods']['e16_scaled_brier_5'].__setitem__('complete_questions',12))
    def test_wrong_human_blind_hash(self):self.mutate(4,lambda o:o.__setitem__('blind_sha256','0'*64))
    def test_fabricated_statistical_superiority(self):self.mutate(4,lambda o:o.__setitem__('statistical_superiority_established',True))
    def test_fabricated_prospective_window(self):self.mutate(4,lambda o:o.__setitem__('prospective_time_window',True))
    def test_false_single_head(self):self.mutate(4,lambda o:o.__setitem__('fourfold_ensemble_not_five_scalar_single_head',False))

    def test_duplicate_json_key(self):
        with self.assertRaisesRegex(ValueError,'duplicate'):
            a.parse_json('{"x":1,"x":2}')

    def test_nonfinite_json_number(self):
        with self.assertRaisesRegex(ValueError,'nonfinite'):
            a.parse_json('{"x":NaN}')


if __name__=='__main__':unittest.main()
