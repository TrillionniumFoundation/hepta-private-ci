"""Fail-closed synthetic fixtures; NEVER evidence of real multimodal advantage."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
import numpy as np

from terminal_risk import ARMS, SCHEMA, digest, evaluate_frozen, fit, load_json, surrogate_portfolio, validate


def fixture(split='train', start=0, n=40, model=None, proposals=None):
    model=model or digest('frozen-checkpoint')
    proposals=proposals or {arm:digest('immutable-proposal:'+arm) for arm in ARMS}
    rng=np.random.default_rng(19+start)
    source_noise=rng.normal(0,.12,(n,4))
    rows=[]
    for source in range(start,start+n):
        for seed in (11,29):
            base=max(0.,min(1., 0.55 + 0.1*np.sin(source) + 0.03*(seed==29)))
            for arm_index,arm in enumerate(ARMS):
                gain=0. if arm_index==0 else .1 + .02*(arm_index-1) + source_noise[source-start,arm_index-1]
                loss=float(round(max(0., min(1., base-gain)),8))
                rows.append({'source_id':f'source-{source}', 'image_digest':digest(f'image-{source}'),
                             'seed':seed, 'arm':arm,'proposal_digest':proposals[arm],
                             'loss':loss,'covered':True,'wall_seconds':0.2+arm_index*0.02,'overrun':False})
    return {'schema':SCHEMA,'split':split,'cohort_digest':digest(f'cohort-{split}-{start}'),
            'model_digest':model,'objective_digest':digest('task-loss-scoring-v1'),
            'budget_seconds':10.,'rows':rows}


class TerminalRiskTests(unittest.TestCase):
    def setUp(self):
        self.train=fixture()

    def test_realized_covariance_psd_and_stable_identity(self):
        data=fit(self.train)
        cov=np.asarray(data['terminal_gain_covariance'])
        self.assertEqual(cov.shape,(4,4))
        self.assertGreaterEqual(np.linalg.eigvalsh(cov).min(),-1e-12)
        self.assertTrue((np.diag(cov)>0).all())
        self.assertEqual(data,fit(copy.deepcopy(self.train)))
        self.assertEqual(data['source_groups'],40)
        self.assertEqual(data['production_authority'],'DENY_ALL')
        self.assertFalse(data['real_model_quality_claim'])
        self.assertIn('not measured mixture',data['portfolio_model'])

    def test_heldout_is_observational_and_keeps_fit_fixed(self):
        frozen=fit(self.train)
        dev=fixture('dev',start=100,proposals={arm:digest('immutable-proposal:'+arm) for arm in ARMS})
        snapshot=copy.deepcopy(frozen)
        result=evaluate_frozen(frozen,dev)
        self.assertEqual(result['sources'],40)
        self.assertEqual(result['role'],'dev')
        self.assertFalse(result['regeneration_performed'])
        self.assertEqual(snapshot,frozen)
        self.assertTrue(np.isfinite(result['covariance_frobenius_error']))
        dev['rows'][0]['image_digest']=self.train['rows'][0]['image_digest']
        with self.assertRaisesRegex(ValueError,'image overlap|relabelled image|multiple image'):
            evaluate_frozen(frozen,dev)

    def test_fitting_on_test_is_denied_even_if_fields_look_valid(self):
        self.train['split']='test'
        with self.assertRaisesRegex(ValueError,'TRAIN ONLY'):
            fit(self.train)

    def test_row_field_and_duplicate_custody(self):
        bad=copy.deepcopy(self.train)
        bad['rows'][0]['unknown_authority']='approve'
        with self.assertRaisesRegex(ValueError,'hidden or missing'):
            validate(bad)
        bad=copy.deepcopy(self.train)
        bad['rows'].append(copy.deepcopy(bad['rows'][0]))
        with self.assertRaisesRegex(ValueError,'duplicate source'):
            validate(bad)
        bad=copy.deepcopy(self.train)
        bad['rows'][0]['proposal_digest']=bad['rows'][1]['proposal_digest']
        with self.assertRaisesRegex(ValueError,'same immutable proposal|changed immutable proposal'):
            validate(bad)
        bad=copy.deepcopy(self.train)
        bad['rows'].pop()
        with self.assertRaisesRegex(ValueError,'incomplete paired'):
            validate(bad)

    def test_soft_timeout_and_refusal_are_full_losses(self):
        bad=copy.deepcopy(self.train)
        bad['rows'][0]['covered']=False
        with self.assertRaisesRegex(ValueError,'full loss'):
            validate(bad)
        bad['rows'][0]['loss']=1.
        validate(bad)
        bad['rows'][0]['wall_seconds']=11.
        with self.assertRaisesRegex(ValueError,'overrun'):
            validate(bad)
        bad['rows'][0]['overrun']=True
        validate(bad)
        bad['rows'][0]['loss']=0.
        with self.assertRaisesRegex(ValueError,'full loss'):
            validate(bad)

    def test_hard_identity_and_overlap_guards(self):
        frozen=fit(self.train)
        dev=fixture('dev',100)
        for field in ('model_digest','objective_digest'):
            other=copy.deepcopy(dev)
            other[field]=digest('different')
            with self.assertRaisesRegex(ValueError,'changed objective'):
                evaluate_frozen(frozen,other)
        other=copy.deepcopy(dev)
        other['rows'][0]['source_id']='source-0'
        with self.assertRaises(ValueError):
            evaluate_frozen(frozen,other)
        frozen['mean_gains'][0] += 0.2
        with self.assertRaisesRegex(ValueError,'tampered'):
            evaluate_frozen(frozen,dev)

    def test_json_loader_denies_duplicate_members_and_nonfinite(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'bad.json'
            path.write_text('{"schema":"a", "schema":"b"}')
            with self.assertRaisesRegex(ValueError,'duplicate JSON member'):
                load_json(path)
            path.write_text('{"p":NaN}')
            with self.assertRaisesRegex(ValueError,'nonfinite'):
                load_json(path)

    def test_once_per_selected_cell_switching_charge(self):
        frozen=fit(self.train)
        frozen['mean_gains']=[0.01,0.02,0.03,0.04]
        frozen['terminal_gain_covariance']=np.eye(4).tolist()
        frozen['digest']=digest({k:v for k,v in frozen.items() if k != 'digest'})
        cheap=surrogate_portfolio(frozen,risk_weight=0.,switch_cost=0.)
        expensive=surrogate_portfolio(frozen,risk_weight=0.,switch_cost=0.05)
        self.assertGreater(sum(cheap['weights']),0)
        self.assertEqual(expensive['weights'],[0.,0.,0.,0.])
        self.assertEqual(expensive['baseline_residual'],1.)
        self.assertFalse(expensive['is_empirical_efficient_frontier'])

    def test_absent_seed_or_insufficient_independent_sources(self):
        with self.assertRaisesRegex(ValueError,'insufficient'):
            fit(fixture(n=12))
        bad=copy.deepcopy(self.train)
        bad['rows']=[r for r in bad['rows'] if not (r['seed']==29 and r['source_id']=='source-2')]
        with self.assertRaisesRegex(ValueError,'repeated seeds'):
            validate(bad)


if __name__=='__main__':
    unittest.main()
