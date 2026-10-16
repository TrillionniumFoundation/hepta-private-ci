"""Original-archive-backed numerical tests plus explicit adversarial contracts."""
import copy
import os
import tempfile
import unittest
from fractions import Fraction as Q
from pathlib import Path
from unittest.mock import patch

from prefix import (ARMS, HORIZON, STEPS, choose, execute, prefix_fit,
                    public_rows, timed_prediction_and_score, spec, source_hashes)
from material import LOCKS, canonical, load_sources, prepare, sha, strict_loads
from learning import fit, predict, validate_fold
from audit_prefix import inspect, reference_fit, integer
from audit_real import ref_predict


class PrefixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assets={k:Path(os.environ['HEPTA_MERTON_ASSETS'])/f'{v[0]}.zip' for k,v in LOCKS.items()}
        cls.rows,cls.labels,cls.provenance=load_sources(cls.assets)
        cls.tmp=tempfile.TemporaryDirectory();cls.material=Path(cls.tmp.name)/'material'
        prepare(cls.assets,cls.material)
        cls.fold=strict_loads((cls.material/'fold-0.json').read_bytes())
        cls.bank=prefix_fit(cls.fold['train'])
        cls.row=execute(cls.fold,'prefix_ndu')
        cls.independent=execute(cls.fold,'corrected_independent')

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def reject(self,mutate):
        row=copy.deepcopy(self.row);mutate(row)
        with self.assertRaises((ValueError,KeyError)):
            inspect(row,self.fold,self.labels)

    def test_01_original_denominators(self):
        self.assertEqual((len(self.rows),len({r['group'] for r in self.rows}),len({(r['group'],r['question']) for r in self.rows})),(33,4,8))

    def test_02_source_integrity(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'tampered.zip';p.write_bytes(self.assets['reader'].read_bytes()+b'bad')
            with self.assertRaises(ValueError):load_sources(dict(self.assets,reader=p))

    def test_03_all_checkpoints_bit_equal_restarted(self):
        for n in STEPS:
            head,_=fit(self.fold['train'],n)
            self.assertEqual(head,self.bank['heads'][str(n)])

    def test_04_independent_scalar_SGD(self):
        for n in STEPS:
            head,trace=reference_fit(canonical(self.fold['train']),n)
            for x,y in zip(head['weights'],self.bank['heads'][str(n)]['weights']):self.assertAlmostEqual(x,y,places=12)
            for x,y in zip(trace,self.bank['loss_trace'][:n]):self.assertAlmostEqual(x,y,places=12)

    def test_05_prefix_is_128_not_168_steps(self):
        self.assertEqual(self.bank['optimizer_steps'],128)
        self.assertEqual(self.bank['train_row_updates'],128*len(self.fold['train']))
        self.assertEqual(sum(STEPS)-self.bank['optimizer_steps'],40)

    def test_06_checkpoint_copies_do_not_alias(self):
        b=copy.deepcopy(self.bank);old=b['heads']['32']['weights'][0]
        b['heads']['8']['weights'][0]+=100
        self.assertEqual(b['heads']['32']['weights'][0],old)

    def test_07_positive_checkpoints_have_train_only_scale(self):
        self.assertEqual(self.bank['heads']['8']['scales'],self.bank['heads']['128']['scales'])
        self.assertEqual(self.bank['heads']['0']['scales'],[1.0]*4)

    def test_08_zero_step_exact_baseline(self):
        head,_=fit([],0)
        self.assertEqual(predict(head,self.fold['held_inputs']),predict(self.bank['heads']['0'],self.fold['held_inputs']))

    def test_09_prefix_meter_monotone(self):
        ns=[self.bank['cumulative_cpu_ns'][str(n)] for n in STEPS]
        self.assertEqual(ns,sorted(ns));self.assertLessEqual(ns[-1],self.bank['cpu_ns'])

    def test_10_missing_labels_rejected(self):
        with self.assertRaises(ValueError):prefix_fit(self.fold['held_inputs'])

    def test_11_public_predict_input_excludes_labels(self):
        pp=public_rows(self.fold['train'])
        self.assertTrue(all('label' not in r for r in pp))
        self.assertEqual(predict(self.bank['heads']['32'],pp),predict(self.bank['heads']['32'],self.fold['train']))

    def test_12_meter_does_not_charge_score_as_inference(self):
        # Explicit mock clock contract; these numbers are not model observations.
        with patch('prefix.time.process_time_ns',side_effect=[0,10,20,50]):
            _,_,inf,score=timed_prediction_and_score(self.bank['heads']['32'],self.fold['train'])
        self.assertEqual((inf,score),(10,30))

    def test_13_true_prediction_ignores_labels(self):
        changed=copy.deepcopy(self.fold['train'])
        for r in changed:r['label']=1-r['label']
        aa=timed_prediction_and_score(self.bank['heads']['32'],self.fold['train'])
        bb=timed_prediction_and_score(self.bank['heads']['32'],changed)
        self.assertEqual(aa[0],bb[0])

    def test_14_corrected_quote_is_shared(self):
        self.assertEqual(len({v['inference_ns_per_question'] for v in self.row['quotes'].values()}),1)
        expected=sum((Q(r['prediction_cpu_ns'],len(r['questions'])) for r in self.row['calibration']),Q(0))/12
        self.assertEqual(Q(self.row['quotes']['0']['inference_ns_per_question']),expected)

    def test_15_equal_quality_chooses_smaller_prefix(self):
        quotes={str(n):{'passage_success':['1/2']*3,'refit_ns':str(n*1000),'inference_ns_per_question':'100'} for n in STEPS}
        self.assertEqual(choose(quotes,Q(1,2))[0],0)
        quotes['0']['passage_success']=['0']*3
        self.assertEqual(choose(quotes,Q(1,2))[0],8)

    def test_16_lucky_clock_quote_cannot_favor128(self):
        quotes=copy.deepcopy(self.row['quotes']);quotes['128']['inference_ns_per_question']='0'
        with self.assertRaises(ValueError):choose(quotes,Q(1,2))

    def test_17_invalid_choice_inputs(self):
        for p in (True,0.5,Q(-1),Q(3,4)):
            with self.assertRaises(ValueError):choose(self.row['quotes'],p)
        q=copy.deepcopy(self.row['quotes']);q['8']['refit_ns']='-1'
        with self.assertRaises(ValueError):choose(q,Q(0))

    def test_18_same_recorded_cost_exact_reference(self):
        result=inspect(self.row,self.fold,self.labels)
        self.assertEqual(result['checkpoints'],12)
        self.assertEqual(result['alpha'],'1/2')

    def test_19_prefix_independent_full_bank_exact(self):
        for a,b in zip(self.row['banks'],self.independent['banks']):
            self.assertEqual(a['heads'],b['heads'])
        inspect(self.independent,self.fold,self.labels)

    def test_20_baseline_controls_really_no_search(self):
        for arm in ARMS[:4]:
            row=execute(self.fold,arm);inspect(row,self.fold,self.labels)
            self.assertEqual(row['banks'],[]);self.assertEqual(row['calibration'],[])
            self.assertEqual(row['actual_optimizer_steps'],row['selected_steps'])

    def test_21_held_label_smuggling(self):
        f=copy.deepcopy(self.fold);f['held_inputs'][0]['label']=0
        with self.assertRaises(ValueError):execute(f,'prefix_ndu')

    def test_22_bank_weight_tamper(self):
        self.reject(lambda r:r['banks'][0]['heads']['8']['weights'].__setitem__(0,999.0))

    def test_23_bank_step_count_tamper(self):
        self.reject(lambda r:r['banks'][0].update(optimizer_steps=8))

    def test_24_resource_cost_tamper(self):
        self.reject(lambda r:r['stages'].update(pilot_cpu_ns=0))

    def test_25_missing_calibration(self):
        self.reject(lambda r:r['calibration'].pop())

    def test_26_prediction_tamper(self):
        self.reject(lambda r:r['held_predictions'][0].update(p=0.123456789))

    def test_27_source_hash_tamper(self):
        self.reject(lambda r:r.update(source_fold_sha256='0'*64))

    def test_28_inference_quote_contamination(self):
        self.reject(lambda r:r['quotes']['0'].update(inference_ns_per_question='99999'))

    def test_29_saturation_is_reported_not_dynamic_learning(self):
        for i in range(4):
            f=strict_loads((self.material/f'fold-{i}.json').read_bytes())
            r=execute(f,'prefix_ndu');result=inspect(r,f,self.labels)
            self.assertEqual(result['alpha'],'1/2');self.assertTrue(result['all_candidate_minima_zero'])

    def test_30_new_work_does_not_claim_new_sources(self):
        self.assertEqual(spec()['new_sources'],0)
        self.assertFalse(spec()['neural_preference_learning'])
        self.assertEqual(spec()['authority'],'DENY_ALL')
        self.assertEqual(len(source_hashes()),7)

    def test_31_counter_type_strict(self):
        for v in (True,-1,1.0):
            with self.assertRaises(ValueError):integer(v)

    def test_32_backwards_prefix_time_refused(self):
        self.reject(lambda r:r['banks'][0]['cumulative_cpu_ns'].__setitem__('32',0))


if __name__=='__main__':unittest.main()
