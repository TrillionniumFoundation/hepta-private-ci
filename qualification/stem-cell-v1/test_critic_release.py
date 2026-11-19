import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from paired_critic import validate_artifact, fit_critic
from next_round_matrix import _digest
from test_paired_critic import fixture,fit
from test_empirical_continuation import ready,run


class CriticReleaseTests(unittest.TestCase):
    def test_cli_release_and_no_overwrite(self):
        p,rows=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);pf=root/'protocol.json';rf=root/'rows.json';output=root/'result'
            pf.write_text(json.dumps(p));rf.write_text(json.dumps(rows))
            cmd=[sys.executable,str(Path(__file__).with_name('paired_critic.py')),'--protocol',str(pf),
                 '--protocol-id',p['protocol_id'],'--rows',str(rf),'--dataset-id',_digest(rows),'--output',str(output)]
            first=subprocess.run(cmd,capture_output=True,text=True,timeout=15)
            self.assertEqual(first.returncode,0,first.stderr)
            data=(output/'critic.json').read_bytes();artifact=json.loads(data)
            validate_artifact(artifact,artifact['artifact_id'])
            self.assertTrue((output/'COMMITTED.json').exists())
            self.assertNotEqual(subprocess.run(cmd,capture_output=True,timeout=15).returncode,0)
            self.assertEqual(data,(output/'critic.json').read_bytes())

    def test_incomplete_dataset_cannot_release_success(self):
        p,rows=fixture();rows.pop()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);pf=root/'p.json';rf=root/'r.json';out=root/'out'
            pf.write_text(json.dumps(p));rf.write_text(json.dumps(rows))
            result=subprocess.run([sys.executable,str(Path(__file__).with_name('paired_critic.py')),
                        '--protocol',str(pf),'--protocol-id',p['protocol_id'],'--rows',str(rf),
                        '--dataset-id',_digest(rows),'--output',str(out)],capture_output=True,timeout=15)
            self.assertNotEqual(result.returncode,0)
            self.assertTrue((out/'FAILED.json').exists());self.assertFalse((out/'COMMITTED.json').exists())

    def test_fit_work_is_python_timed_not_fabricated_flops(self):
        p,rows=fixture()
        _,r=fit_critic(p,rows,expected_protocol_id=p['protocol_id'],expected_dataset_sha256=_digest(rows))
        self.assertGreater(r['elapsed_ns'],0);self.assertGreater(r['cpu_ns'],0)
        self.assertIsNone(r['arithmetic_work']);self.assertIsNone(r['energy_joules'])

    def test_observer_cannot_precede_segment_completion(self):
        p,rows=fixture();rows[0]['observed_at_ns']=101
        with self.assertRaisesRegex(ValueError,'chronology'):fit(p,rows)

    def test_extra_fields_and_aggregate_denominator_reject_even_rehashed(self):
        original=fit(*fixture())
        for how in ('extra','attempts','group','duplicated'):
            a=copy.deepcopy(original)
            if how=='extra':a['override']=True
            if how=='attempts':a['groups'][0]['attempts']=True
            if how=='group':a['groups'][0]['group_id']='not-a-registered-group'
            if how=='duplicated':a['groups'][1]=copy.deepcopy(a['groups'][0])
            a['artifact_id']=_digest({k:v for k,v in a.items() if k!='artifact_id'})
            with self.subTest(how=how),self.assertRaises(ValueError):validate_artifact(a,a['artifact_id'])

    def test_data_change_cannot_reuse_external_protocol_identity(self):
        p,rows=fixture();identity=p['protocol_id']
        p['alpha']=.1;p['protocol_id']=_digest({k:v for k,v in p.items() if k!='protocol_id'})
        with self.assertRaisesRegex(ValueError,'registration'):
            fit_critic(p,rows,expected_protocol_id=identity,expected_dataset_sha256=_digest(rows))

    def test_cost_paid_once_in_net_gain_decision(self):
        b=ready(coefficient=.001);r=run(b)
        d=r['ndu_decisions'][0]
        self.assertAlmostEqual(d['net_gain_lower'],b[0]['table']['0:0']['net_gain_lower'])
        self.assertFalse(d['sunk_critic_cost_subtracted_again'])
        self.assertFalse(d['segment_cost_subtracted_again'])
        self.assertEqual(r['calls'],5)

    def test_legacy_policy_identity_is_byte_compatible(self):
        from test_ndu_continuation import policy
        from ndu_continuation import freeze_policy
        p=policy();args={k:v for k,v in p.items() if k not in ('schema','utility_profile','policy_id')}
        self.assertEqual(p,freeze_policy(**args,empirical_protocol_id=None))
        self.assertNotIn('empirical_protocol_id',p)


if __name__=='__main__':unittest.main()
