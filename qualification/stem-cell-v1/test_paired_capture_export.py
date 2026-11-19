import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from empirical_continuation import FrozenPairedCritic
from execution_meter import WorkLedger
from matrix_materials import file_sha256, strict_json
from matrix_runtime import write_json_exclusive
from ndu_continuation import PROFILE as NDU_PROFILE, freeze_policy
from next_round_matrix import _digest
from paired_capture_export import OBSERVER_SCHEMA, assemble_pairs, read_pair, fit_collected
from paired_critic import fit_critic
from paired_execution import PHASES
from system2_execution import PublicTask, run_reasoning
import test_paired_capture as fixtures


def observe(root, registration, seals):
    """TEST-ONLY independent arithmetic oracle, not the verifier's acceptance bit."""
    labels = []
    for i, (boundary, seal) in enumerate(zip(registration['boundaries'], seals, strict=True)):
        record, _ = read_pair(root, registration, i, seal['terminal_id'])
        answer = str(sum(map(int, boundary['task']['observations'][0][0].split(','))))
        labels.append(dict(pair_id=boundary['pair_id'], stop_candidate_sha256=_digest(record['stop_candidate']),
                           continue_candidate_sha256=_digest(record['continue_candidate']),
                           stop_utility=int(record['stop_candidate'] == answer),
                           continue_utility=int(record['continue_candidate'] == answer), observed_at_ns=9*10**11))
    p = registration['protocol']
    receipt = dict(schema=OBSERVER_SCHEMA, capture_id=registration['capture_id'], protocol_id=p['protocol_id'],
                   objective_sha256=p['objective_sha256'], observer_sha256=p['observer_sha256'],
                   created_at_ns=9*10**11, terminal_ids=[s['terminal_id'] for s in seals], rows=labels)
    path = Path(root) / 'external-test-oracle.json'; write_json_exclusive(path, receipt)
    return path


def build(root, *, failure=False, wrong=False, ncal=4):
    r, cb, collector, propose, verify = fixtures.setup_capture(root, failure=failure, wrong=wrong, ncal=ncal)
    cb.accept_all = wrong
    clock = fixtures.Clock()
    seals = [collector.run_pair(pair['pair_id'], clock=clock) for pair in r['protocol']['pairs']]
    path = observe(root, r, seals)
    return r, cb, seals, path, propose, verify


class CaptureExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.reference.cleanup)
        cls.base = Path(cls.reference.name) / 'campaign'
        cls.r, _, cls.seals, _, _, _ = build(cls.base)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'copy'; shutil.copytree(self.base, self.root)
        self.op = self.root / 'external-test-oracle.json'

    def export(self):
        return assemble_pairs(self.root, expected_capture_id=self.r['capture_id'], observer_path=self.op,
                              expected_observer_sha256=file_sha256(self.op))

    def test_actual_capture_to_rows_to_fitted_critic(self):
        p, rows, lineage = self.export()
        artifact, work = fit_collected(p, rows, lineage)
        self.assertEqual(artifact['schema'], 'hepta.ndu.frozen-paired-critic.v2')
        self.assertEqual(len(rows), 6)
        self.assertEqual([r['formula_work'] for r in rows], [6]*6)
        self.assertEqual([r['continue_utility'] for r in rows], [1]*6)
        self.assertEqual({r['outcome_receipt_sha256'] for r in rows}, {file_sha256(self.op)})
        self.assertEqual(artifact['table']['0:0']['fit_mean'], 1)
        self.assertFalse(lineage['owner_authenticity_verified'])
        self.assertFalse(artifact['final_efficacy_established'])

    def test_verifier_acceptance_is_not_external_utility(self):
        root = Path(self.tmp.name) / 'wrong'
        r, _, seals, path, _, _ = build(root, wrong=True)
        first, _ = read_pair(root, r, 0, seals[0]['terminal_id'])
        self.assertEqual(first['execution']['status'], 'verifier_accepted_not_independent_eval')
        _, rows, _ = assemble_pairs(root, expected_capture_id=r['capture_id'], observer_path=path,
                                    expected_observer_sha256=file_sha256(path))
        self.assertEqual([r['continue_utility'] for r in rows], [0]*6)

    def test_failed_attempts_retained_and_incomplete_cost_blocks_whole_fit(self):
        root = Path(self.tmp.name) / 'failed'
        r, _, _, path, _, _ = build(root, failure=True)
        p, rows, lineage = assemble_pairs(root, expected_capture_id=r['capture_id'], observer_path=path,
                                         expected_observer_sha256=file_sha256(path))
        self.assertEqual([row['status'] for row in rows], ['failed']*6)
        self.assertEqual(len(lineage['incomplete_cost_pairs']), 6)
        with self.assertRaises(ValueError):
            fit_critic(p, rows, expected_protocol_id=p['protocol_id'], expected_dataset_sha256=_digest(rows))

    def test_missing_and_partial_pair_not_inferred_as_failure(self):
        (self.root/'pairs/00000/TERMINAL.json').unlink()
        with self.assertRaisesRegex(ValueError, 'unresolved'): self.export()

    def test_all_pairs_must_seal_before_any_external_scores(self):
        labels = strict_json(self.op); labels['rows'][0]['observed_at_ns'] = self.seals[0]['sealed_at_ns']
        self.op.write_text(json.dumps(labels))
        with self.assertRaisesRegex(ValueError, 'all paired outputs'): self.export()

    def test_objective_observer_and_endpoint_substitution_reject(self):
        original = strict_json(self.op)
        for field in ('objective_sha256', 'observer_sha256', 'capture_id'):
            changed = copy.deepcopy(original); changed[field] = 'f'*64
            self.op.write_text(json.dumps(changed))
            with self.subTest(field=field), self.assertRaises(ValueError): self.export()
        changed = copy.deepcopy(original); changed['rows'][0]['continue_candidate_sha256'] = 'f'*64
        self.op.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, 'actual sealed endpoints'): self.export()

    def test_missing_or_reordered_scores_reject(self):
        original = strict_json(self.op)
        for how in ('missing', 'reorder', 'duplicate'):
            changed = copy.deepcopy(original)
            if how == 'missing': changed['rows'].pop()
            elif how == 'reorder': changed['rows'].reverse()
            else: changed['rows'][1] = copy.deepcopy(changed['rows'][0])
            self.op.write_text(json.dumps(changed))
            with self.subTest(how=how), self.assertRaises(ValueError): self.export()

    def test_sealed_candidate_bytes_cannot_be_changed(self):
        p = self.root/'pairs/00000/pair.json'; original=p.read_bytes();p.write_bytes(original+b' ')
        with self.assertRaisesRegex(ValueError, 'bytes changed'): self.export()

    def test_rehashed_false_complete_cost_rejected_semantically(self):
        root=self.root/'pairs/00000'; path=root/'pair.json'
        record=strict_json(path); work=record['execution']['work_observation']
        work['scopes'][0]['unknown_operators'] += 1
        work['operators']['aten.sin.default'] = 1;work['unknown_operators']['aten.sin.default'] = 1
        path.write_text(json.dumps(record))
        seal=strict_json(root/'TERMINAL.json');seal['files']['pair.json']=file_sha256(path)
        seal['terminal_id']=_digest({k:v for k,v in seal.items() if k!='terminal_id'})
        (root/'TERMINAL.json').write_text(json.dumps(seal))
        labels=strict_json(self.op);labels['terminal_ids'][0]=seal['terminal_id'];self.op.write_text(json.dumps(labels))
        with self.assertRaisesRegex(ValueError, 'cannot claim complete'): self.export()

    def test_scoring_never_calls_models(self):
        with patch('system2_execution.run_reasoning', side_effect=AssertionError('must not execute')):
            _, rows, _ = self.export()
        self.assertEqual(len(rows), 6)

    def test_observer_raw_byte_pin_is_required(self):
        sha=file_sha256(self.op);self.op.write_text(self.op.read_text()+' ')
        with self.assertRaises(ValueError):
            assemble_pairs(self.root, expected_capture_id=self.r['capture_id'], observer_path=self.op,
                           expected_observer_sha256=sha)

    def test_capture_fit_freeze_live_control_integration(self):
        root=Path(self.tmp.name)/'larger'
        r, _, _, op, propose, verify=build(root,ncal=40)
        p,rows,lineage=assemble_pairs(root,expected_capture_id=r['capture_id'],observer_path=op,expected_observer_sha256=file_sha256(op))
        artifact,_=fit_collected(p,rows,lineage)
        critic=FrozenPairedCritic(artifact,expected_id=artifact['artifact_id'],callback_profile_sha256='b'*64,
                                 propose=propose,verify=verify)
        budget=dict(max_rounds=2,max_calls=5,meter_policy=r['meter_policy'],phase_caps=r['phase_caps'])
        policy=freeze_policy(objective_sha256=p['objective_sha256'],subject_id=p['subject_id'],
                             critic_sha256=artifact['artifact_id'],critic_cutoff_ns=p['cutoff_ns'],
                             expires_at_ns=p['expires_at_ns'],**p['coefficients'],minimum_margin=0.,
                             max_estimate_age_ns=10**15,execution=budget,empirical_protocol_id=p['protocol_id'])
        task=PublicTask('unseen heldout diagnostic case',10**12+1,(('11,12',10**12),))
        report=run_reasoning(task,propose=propose,verify=verify,continue_values=critic,value_profile=NDU_PROFILE,
                             max_rounds=2,max_calls=5,ndu_policy=policy,
                             meter=WorkLedger(r['meter_policy'],r['phase_caps']),clock=lambda:10**12+2)
        self.assertEqual(report['calls'],5)
        self.assertEqual(report['candidate'],'23')
        self.assertFalse(report['independent_success_established'])
        self.assertEqual(report['empirical_critic']['capture_binding']['capture_id'],r['capture_id'])
        from transformer_work import PROFILE as transformer_profile
        wrong=copy.deepcopy(policy)
        wrong['execution']['meter_policy'].update(schema='hepta.execution-meter-policy.v2',arithmetic_profile=transformer_profile)
        with self.assertRaisesRegex(ValueError,'arithmetic profile'):
            critic.validate_binding(wrong,propose,verify)

    def test_expensive_continuation_is_not_filtered_before_fit(self):
        root=Path(self.tmp.name)/'expensive'
        r,cb,collector,_,_=fixtures.setup_capture(root)
        cb.extra_work=101
        clock=fixtures.Clock()
        seals=[collector.run_pair(q['pair_id'],clock=clock) for q in r['protocol']['pairs']]
        op=observe(root,r,seals)
        p,rows,lineage=assemble_pairs(root,expected_capture_id=r['capture_id'],observer_path=op,
                                     expected_observer_sha256=file_sha256(op))
        self.assertEqual(len(rows),6)
        self.assertEqual([row['formula_work'] for row in rows],[107]*6)
        with self.assertRaisesRegex(ValueError,'envelope violation'):
            fit_collected(p,rows,lineage)

    def test_capture_binding_cannot_name_a_different_dataset(self):
        from paired_critic import validate_artifact
        p,rows,lineage=self.export()
        artifact,_=fit_collected(p,rows,lineage)
        artifact['capture_binding']['dataset_sha256']='f'*64
        artifact['artifact_id']=_digest({k:v for k,v in artifact.items() if k!='artifact_id'})
        with self.assertRaisesRegex(ValueError,'capture linkage'):
            validate_artifact(artifact,artifact['artifact_id'])

    def test_capture_and_scoring_receipts_must_agree_after_normalization(self):
        p,rows,lineage=self.export()
        lineage['observer_receipt_sha256']='f'*64
        with self.assertRaisesRegex(ValueError,'observation linkage'):
            fit_collected(p,rows,lineage)

    def test_cli_releases_fit_or_retains_incomplete_failure(self):
        script=Path(__file__).with_name('paired_capture_export.py')
        out=Path(self.tmp.name)/'release'
        args=[sys.executable,str(script),'--capture-dir',str(self.root),'--capture-id',self.r['capture_id'],
              '--observer',str(self.op),'--observer-sha256',file_sha256(self.op),'--output',str(out)]
        result=subprocess.run(args,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue((out/'COMMITTED.json').is_file())
        before=(out/'critic.json').read_bytes()
        self.assertNotEqual(subprocess.run(args,capture_output=True,timeout=20).returncode,0)
        self.assertEqual(before,(out/'critic.json').read_bytes())
        root=Path(self.tmp.name)/'failed-cli';r,_,_,op,_,_=build(root,failure=True)
        out=Path(self.tmp.name)/'failed-release'
        args=[sys.executable,str(script),'--capture-dir',str(root),'--capture-id',r['capture_id'],
              '--observer',str(op),'--observer-sha256',file_sha256(op),'--output',str(out)]
        result=subprocess.run(args,capture_output=True,text=True,timeout=20)
        self.assertNotEqual(result.returncode,0)
        self.assertTrue((out/'paired-rows.json').is_file())
        self.assertEqual(len(strict_json(out/'paired-rows.json')),6)
        self.assertTrue((out/'FAILED.json').is_file())
        self.assertFalse((out/'COMMITTED.json').exists())


if __name__ == '__main__':
    unittest.main()
