"""Learned tiny prefix generation -> capture -> objective -> frozen-critic plumbing.

Three memorized colour prompts are deliberately INSUFFICIENT fitting support.
No semantic duplicates are relabeled as many independent calibration examples.
"""
import copy
import json
import tempfile
import subprocess
import sys
import unittest
from dataclasses import asdict
from pathlib import Path

from empirical_continuation import FrozenPairedCritic, case_fingerprint
from execution_meter import WorkLedger
from generation_test_support import adapter, structural_verifier, train_tiny
from matrix_materials import file_sha256
from matrix_runtime import write_json_exclusive
from ndu_continuation import freeze_policy, PROFILE
from next_round_matrix import _digest
from paired_capture import PairCollector, create_capture, freeze_capture
from paired_capture_export import OBSERVER_SCHEMA, read_pair, assemble_pairs, fit_collected
from paired_critic import freeze_protocol
from system2_execution import PublicTask, run_reasoning
from test_paired_capture import Clock
from test_reasoning_baselines import policy_inputs


def build_neural_capture(root, model, codec):
    root=Path(root);proposer=adapter(model,codec)
    callback_profile=_digest([proposer.receipt()['policy'],'format-only-verifier.v1'])
    boundaries,pairs,origins=[],[],[]
    for group,colour in (('fit_red','red'),('cal_green','green'),('cal_blue','blue')):
        task=PublicTask('colour '+colour,5)
        candidate=proposer(task,None,None)
        origin=proposer.receipt()['last_generation'];origins.append(origin)
        checked=structural_verifier(task,candidate)
        pairs.append(dict(pair_id=group,group_id=group,case_sha256=case_fingerprint(task,candidate,checked.feedback),
                          candidate_bytes=len(candidate.encode()),feedback_bytes=len(checked.feedback.encode())))
        boundaries.append(dict(pair_id=group,task=json.loads(json.dumps(asdict(task))),candidate=candidate,
                               feedback=checked.feedback,available_at_ns=9,initial_verifier_accepted=checked.accepted,
                               origin_receipt_sha256=_digest(origin)))
    p=freeze_protocol(objective_sha256='a'*64,subject_id='episode:neural-fixture',
         callback_profile_sha256=callback_profile,observer_sha256='c'*64,
         registered_at_ns=10,cutoff_ns=10**12,expires_at_ns=10**15,
         fit_groups=['fit_red'],calibration_groups=['cal_blue','cal_green'],pairs=pairs,
         candidate_edges=[32],feedback_edges=[32],alpha=.05,minimum_groups=2,max_calibration_gap=.25,
         duration_upper_ns=5*10**9,formula_work_upper=1_000_000,
         coefficients=dict(discount_rate_per_second=0.,cost_per_formula_flop=0.,cost_per_latency_ns=0.))
    wp,caps=policy_inputs()
    registration=freeze_capture(p,expected_protocol_id=p['protocol_id'],boundaries=boundaries,meter_policy=wp,phase_caps=caps)
    create_capture(root,registration)
    collector=PairCollector(root,expected_capture_id=registration['capture_id'],callback_profile_sha256=callback_profile,
                            propose=proposer,verify=structural_verifier)
    clock=Clock()
    seals=[collector.run_pair(q['pair_id'],clock=clock) for q in pairs]
    rows=[]
    for i,(b,seal) in enumerate(zip(boundaries,seals,strict=True)):
        record,_=read_pair(root,registration,i,seal['terminal_id'])
        # A separate exact-output oracle; never derived from verifier.accepted.
        target=b['task']['prompt'].split()[-1]+' done'
        rows.append(dict(pair_id=b['pair_id'],stop_candidate_sha256=_digest(record['stop_candidate']),
                         continue_candidate_sha256=_digest(record['continue_candidate']),
                         stop_utility=int(record['stop_candidate']==target),
                         continue_utility=int(record['continue_candidate']==target),observed_at_ns=9*10**11))
    score=dict(schema=OBSERVER_SCHEMA,capture_id=registration['capture_id'],protocol_id=p['protocol_id'],
                objective_sha256=p['objective_sha256'],observer_sha256=p['observer_sha256'],
                created_at_ns=9*10**11,terminal_ids=[s['terminal_id'] for s in seals],rows=rows)
    score_path=root/'test-only-objective.json';write_json_exclusive(score_path,score)
    protocol,rows,lineage=assemble_pairs(root,expected_capture_id=registration['capture_id'],observer_path=score_path,
                                         expected_observer_sha256=file_sha256(score_path))
    artifact,fit_work=fit_collected(protocol,rows,lineage)
    write_json_exclusive(root/'critic.json',artifact)
    write_json_exclusive(root/'normalized-rows.json',rows)
    write_json_exclusive(root/'initial-generation-observations.json',origins)
    return registration,artifact,proposer,rows,fit_work


class NeuralCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup)
        m,t,cls.training=train_tiny()
        cls.root=Path(cls.tmp.name)/'capture'
        cls.registration,cls.artifact,cls.proposer,cls.rows,cls.fit_work=build_neural_capture(cls.root,m,t)

    def test_neural_outputs_not_a_procedural_proposer_feed_existing_capture(self):
        self.assertEqual([r['continue_utility'] for r in self.rows],[1,1,1])
        self.assertEqual([r['stop_utility'] for r in self.rows],[0,0,0])
        for i,b in enumerate(self.registration['boundaries']):
            marker=json.loads((self.root/'pairs'/f'{i:05d}'/'TERMINAL.json').read_text())
            record,_=read_pair(self.root,self.registration,i,marker['terminal_id'])
            g=record['execution']['trace'][0]['generation']
            self.assertEqual((g['forward_attempts'],g['generated_tokens']),(3,2))
            self.assertEqual(g['profile_id'],self.proposer.receipt()['policy']['profile_id'])
            self.assertGreater(record['execution']['work_observation']['phase_flops']['search'],0)

    def test_small_memorized_panel_does_not_manufacture_critic_support(self):
        entry=self.artifact['table']['0:0']
        self.assertEqual((entry['fit_groups'],entry['calibration_groups']),(1,2))
        self.assertFalse(entry['supported'])
        self.assertFalse(self.artifact['final_efficacy_established'])
        self.assertFalse(self.training['generalization_evaluated'])

    def test_captured_critic_controls_real_adapter_without_new_outcome_access(self):
        p=self.artifact['protocol'];wp,caps=policy_inputs()
        critic=FrozenPairedCritic(self.artifact,expected_id=self.artifact['artifact_id'],
                 callback_profile_sha256=p['callback_profile_sha256'],propose=self.proposer,verify=structural_verifier)
        pol=freeze_policy(objective_sha256=p['objective_sha256'],subject_id=p['subject_id'],
                critic_sha256=self.artifact['artifact_id'],critic_cutoff_ns=p['cutoff_ns'],expires_at_ns=p['expires_at_ns'],
                **p['coefficients'],minimum_margin=0.,max_estimate_age_ns=10**14,
                execution=dict(max_calls=5,max_rounds=2,meter_policy=wp,phase_caps=caps),empirical_protocol_id=p['protocol_id'])
        # Permuted known vocabulary is NOT used as generalization evidence.
        report=run_reasoning(PublicTask('red colour',10**12+1),propose=self.proposer,verify=structural_verifier,
                continue_values=critic,value_profile=PROFILE,max_calls=5,max_rounds=2,ndu_policy=pol,
                meter=WorkLedger(wp,caps),clock=lambda:10**12+5)
        self.assertEqual((report['calls'],report['candidate']),(3,'unsure'))
        self.assertEqual(report['status'],'ndu_stop:unsupported_continuation')

    def test_source_binding_includes_generation_and_fixed_control_code(self):
        source=self.registration['source_files_sha256']
        for name in ('causal_generation.py','causal_snapshot.py','reasoning_baselines.py'):
            self.assertEqual(source[name],file_sha256(Path(__file__).with_name(name)))

    def test_unmetered_legacy_callbacks_do_not_gain_a_torch_dependency(self):
        code="""import sys
sys.modules['torch']=None
from system2_execution import PublicTask, Verification, run_reasoning
r=run_reasoning(PublicTask('legacy',1),propose=lambda *a:'answer',verify=lambda *a:Verification(True,'ok'),continue_values=None,value_profile='legacy',max_rounds=1,max_calls=2)
assert r['calls']==2
"""
        result=subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).parent,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
