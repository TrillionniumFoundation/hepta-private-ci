from __future__ import annotations
import unittest
from hashlib import sha256
from reference import *

H=lambda s:sha256(s.encode()).hexdigest()

class ReferenceTests(unittest.TestCase):
    def test_valid_body_graph_has_deterministic_order(self):
        g=BodyGraph(1,default_reference_organs()); a=g.validate(); b=g.validate(); self.assertEqual(a,b); self.assertEqual(set(a), {organ.organ_id for organ in default_reference_organs()})
    def test_cycle_is_rejected(self):
        rows=(OrganManifest('a',1,'x',dependencies=('b',)),OrganManifest('b',1,'x',dependencies=('a',)))
        with self.assertRaises(ValidationError):BodyGraph(1,rows).validate()
    def test_essential_organ_requires_fallback(self):
        rows=(OrganManifest('constitutional.kernel',1,'constitutional_kernel',essential=True),OrganManifest('x',1,'x',dependencies=('constitutional.kernel',),essential=True))
        with self.assertRaises(ValidationError):BodyGraph(1,rows).validate()
    def test_local_hot_path_cannot_require_central_rpc(self):
        with self.assertRaises(ValidationError):OrganManifest('x',1,'x',local_hot_path=True,central_rpc_required=True).validate()
    def test_lifecycle_requires_independent_acceptance(self):
        x=OrganInstance(OrganManifest('x',1,'x')); x.transition(OrganState.BUILT); x.transition(OrganState.SIMULATED)
        with self.assertRaises(ValidationError):x.transition(OrganState.QUALIFIED,artifact='a',generator='g',evaluator='g')
        x.transition(OrganState.QUALIFIED,artifact='a',generator='g',evaluator='e'); x.transition(OrganState.CANARY); x.transition(OrganState.ACTIVE)
    def test_homeostasis_never_exceeds_budget(self):
        out=HomeostasisController.allocate(10,[ResourceRequest('a',2,8,2),ResourceRequest('b',3,9,1)])
        self.assertLessEqual(sum(out.values()),10); self.assertGreaterEqual(out['a'],2); self.assertGreaterEqual(out['b'],3)
    def test_stale_or_uncalibrated_sensor_fails_closed(self):
        x=SensorObservation('o','s',10,2,3,H('p'),5,'u')
        with self.assertRaises(ValidationError):x.validate(now_micros=100,maximum_age_micros=20,calibration_generation=2,body_generation=3,scope='u')
        with self.assertRaises(ValidationError):x.validate(now_micros=10,maximum_age_micros=20,calibration_generation=1,body_generation=3,scope='u')
    def test_reflex_veto_precedes_actuation(self):
        i=ActuationIntent('i',H('o'),1,'arm',H('p'),100,'k',H('a')); b=BodyStateEstimate(1,50,900000,10000,H('s'))
        self.assertTrue(ReflexController.evaluate(i,b,now_micros=60,maximum_state_age_micros=20,minimum_integrity_ppm=950000,maximum_uncertainty_ppm=50000).veto)
        self.assertFalse(ReflexController.evaluate(i,b,now_micros=60,maximum_state_age_micros=20,minimum_integrity_ppm=800000,maximum_uncertainty_ppm=50000).veto)
    def test_queue_ack_is_not_terminal_success(self):
        i=ActuationIntent('i',H('o'),1,'arm',H('p'),100,'k',H('a')); l=ActuationLedger()
        self.assertEqual(l.accept(i),EffectState.ACCEPTED); self.assertEqual(l.dispatch('k'),EffectState.DISPATCHED)
        self.assertEqual(l.acknowledgement_lost('k'),EffectState.INDETERMINATE); self.assertEqual(l.observe_terminal('k',EffectState.APPLIED),EffectState.APPLIED)
    def test_intent_id_reuse_with_different_payload_conflicts(self):
        l=ActuationLedger(); l.accept(ActuationIntent('i',H('o'),1,'arm',H('p1'),100,'k',H('a')))
        with self.assertRaises(ConflictError):l.accept(ActuationIntent('i',H('o'),1,'arm',H('p2'),100,'k',H('a')))
    def test_cns_selects_only_feasible_candidate_deterministically(self):
        rows=[PlanCandidate('b',10,3),PlanCandidate('a',10,3),PlanCandidate('x',100,1,('veto',)),PlanCandidate('over',50,20)]
        self.assertEqual(CNSController.select(rows,10).candidate_id,'a')
    def test_topology_is_next_snapshot_only(self):
        TopologyProposal('p',3,4,'add','g','e').validate(3)
        with self.assertRaises(ValidationError):TopologyProposal('p',3,3,'add','g','e').validate(3)
        with self.assertRaises(ValidationError):TopologyProposal('p',3,4,'add','g','g').validate(3)
        with self.assertRaises(ValidationError):TopologyProposal('p',3,4,'add','g','e',True).validate(3)
    def test_consolidation_excludes_revoked_rows(self):
        self.assertEqual(consolidation_candidate([EpisodeRow('b',False,1),EpisodeRow('a',True,2),EpisodeRow('c',False,3)]),('b','c'))

if __name__=='__main__':unittest.main()
