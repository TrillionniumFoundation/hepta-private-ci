"""Qualification-only tests: analytic rules and current native bindings."""
import json
import re
import unittest
from copy import deepcopy
from fractions import Fraction as F
from pathlib import Path
from unittest import mock
import implementation_contracts as c

BASE=Path(__file__).resolve().parent

class ImplementationProfileVocabularyTests(unittest.TestCase):
    def setUp(self):
        self.read=c.read_json
        self.profiles=self.read(BASE/'IMPLEMENTATION_PROFILES.json')
        self.schema=self.read(BASE/'IMPLEMENTATION_PROFILES.schema.json')

    def verify(self, profiles=None, schema=None):
        def read(path):
            if path.name=='IMPLEMENTATION_PROFILES.json':
                return self.profiles if profiles is None else profiles
            if path.name=='IMPLEMENTATION_PROFILES.schema.json':
                return self.schema if schema is None else schema
            return self.read(path)
        with mock.patch.object(c,'read_json',side_effect=read):
            return c.verify_bundle(c.ROOT)

    def test_versioned_owner_states_preserve_document_only_claims(self):
        self.assertEqual(c.implementation_state_values(c.ROOT),{
            'specified_not_product_evidence',
            'source_implemented_product_composed_requires_candidate_evidence',
            'durable_source_implemented_product_execution_pending',
            'source_owner_implemented_not_product_evidence',
        })
        report=self.verify()
        self.assertEqual(report['modules'],40)
        for flag in ('nativeProductTestsExecuted','independentReview','allGapsClosed'):
            self.assertIs(report[flag],False)

    def test_unknown_and_non_string_states_cannot_self_certify(self):
        for state in ('unknown_source_state','production_ready',True,['specified_not_product_evidence']):
            profiles=deepcopy(self.profiles)
            profiles['modules'][0]['implementationState']=state
            with self.subTest(state=state), self.assertRaisesRegex(c.Invalid,'false source or deployment closure'):
                self.verify(profiles=profiles)

    def test_every_source_state_remains_independent_of_qualification_flags(self):
        for state in c.implementation_state_values(c.ROOT):
            for flag,value in (('nativeMappingRequired',False),('productTestsExecuted',True),('deploymentQualified',True)):
                profiles=deepcopy(self.profiles)
                profiles['modules'][0]['implementationState']=state
                profiles['modules'][0][flag]=value
                with self.subTest(state=state,flag=flag), self.assertRaises(c.Invalid):
                    self.verify(profiles=profiles)

    def test_owner_schema_identity_missing_duplicate_and_typed_enum_reject(self):
        for mutation in ('id','version','missing','duplicate','type'):
            schema=deepcopy(self.schema)
            state=schema['properties']['modules']['items']['properties']['implementationState']
            if mutation=='id':
                schema['$id']='urn:unregistered:profile:v1'
            elif mutation=='version':
                schema['properties']['schemaVersion']['const']=2
            elif mutation=='missing':
                del state['enum']
            elif mutation=='duplicate':
                state['enum'].append(state['enum'][0])
            else:
                state['enum'].append(True)
            with self.subTest(mutation=mutation), self.assertRaisesRegex(c.Invalid,'owner schema identity/vocabulary'):
                self.verify(schema=schema)

class NumericTests(unittest.TestCase):
    def test_signed_half_ties(self):
        self.assertEqual([c.rescale(v,2,1) for v in (5,7,-5,-7)],[2,4,-2,-4])
    def test_toward_zero_is_not_nearest(self):
        self.assertEqual(c.rescale(-7,2,1,'toward_zero'),-3)
    def test_overflow_rejects(self):
        with self.assertRaises(c.Invalid): c.rescale((1<<63)-1,1,2)
    def test_unknown_rounding_rejects(self):
        with self.assertRaises(c.Invalid): c.rescale(1,1,1,'ambient')
    def test_boolean_is_not_counter(self):
        with self.assertRaises(c.Invalid): c.next_sequence(True)
    def test_exhaustion_before_mutation(self):
        state={'sequence':7,'record':'old'}
        with self.assertRaises(c.Invalid): state['sequence']=c.next_sequence(state['sequence'],7)
        self.assertEqual(state,{'sequence':7,'record':'old'})
    def test_advance_sequence(self): self.assertEqual(c.next_sequence(8),9)
    def test_correlated_covariance(self): self.assertEqual(c.covariance_2d((2,1,2),(5,1)),(3,-1))
    def test_identity_covariance(self): self.assertEqual(c.covariance_2d((1,0,1),(3,-1)),(3,-1))
    def test_singular_covariance(self):
        with self.assertRaises(c.Invalid): c.covariance_2d((1,1,1),(2,2))
    def test_indefinite_covariance(self):
        with self.assertRaises(c.Invalid): c.covariance_2d((1,2,1),(2,2))
    def test_nonzero_mean_centered(self): self.assertEqual(c.centered_scalar([(1,8),(2,11),(3,14)]),3)
    def test_constant_driver_unsupported(self):
        with self.assertRaises(c.Invalid): c.centered_scalar([(1,2),(1,3)])
    def test_scaled_driver(self): self.assertEqual(c.covariance_2d((2,0,2),(6,0)),(3,0))
    def test_joint_ess_floor(self): self.assertEqual(c.ess_floor(5000,[200]),500)
    def test_minimum_ess(self): self.assertEqual(c.ess_floor(1000,[200]),400)
    def test_stricter_ess(self): self.assertEqual(c.ess_floor(1000,[900]),900)
    def test_threshold_intersection(self):
        a={'unit':'m','estimand':'single','scope':'pilot','lower':0,'upper':2}
        b=dict(a,lower=1,upper=3)
        self.assertEqual(c.threshold_intersection([a,b]),(1,2))
    def test_threshold_unit_mismatch(self):
        a={'unit':'m','estimand':'single','scope':'pilot','lower':0,'upper':2}
        with self.assertRaises(c.Invalid): c.threshold_intersection([a,dict(a,unit='seconds')])
    def test_threshold_empty_intersection(self):
        a={'unit':'m','estimand':'single','scope':'pilot','lower':0,'upper':1}
        with self.assertRaises(c.Invalid): c.threshold_intersection([a,dict(a,lower=2,upper=3)])
    def test_sequential_dr(self):
        rows=[dict(v=F(1,4),q=F(1,4),reward=F(1,5),behavior=F(1),evaluation=F(1,2),discount=F(9,10)),dict(v=F(1,2),q=F(1,2),reward=F(1),behavior=F(1,2),evaluation=F(1),discount=F(1))]
        self.assertEqual(c.sequential_dr(rows),F(9,10))
    def test_zero_propensity(self):
        with self.assertRaises(c.Invalid): c.sequential_dr([dict(v=0,q=0,reward=1,behavior=0,evaluation=1,discount=1)])
    def test_terminal_not_double_counted(self):
        self.assertEqual(c.sequential_dr([dict(v=0,q=0,reward=1,behavior=1,evaluation=1,discount=1)],F(0)),1)
    def test_duplicate_json_keys(self):
        with self.assertRaises(c.Invalid): json.loads('{"x":1,"x":2}',object_pairs_hook=c.pairs)

class NativeBindingCoverageTests(unittest.TestCase):
    def merged_native_observations(self):
        native=c.read_json(BASE/'NATIVE_BINDINGS.json')
        lane_a=c.read_json(BASE/'NATIVE_BINDINGS_LANE_A.json')
        self.assertEqual(lane_a['moduleCoverage'],7)
        override={row['module']:row for row in lane_a['observations']}
        self.assertEqual(len(override),7)
        self.assertEqual(set(override),set(lane_a['closedWorldModules']))
        return native, [override.get(row['module'],row) for row in native['observations']]

    def test_native_binding_module_closed_world(self):
        profiles=c.read_json(BASE/'IMPLEMENTATION_PROFILES.json')
        native, observations=self.merged_native_observations()
        self.assertEqual(native['moduleCoverage'],40)
        self.assertFalse(native['consumerCallsitesProved'])
        self.assertFalse(native['productExecutionProved'])
        self.assertEqual(
            [row['module'] for row in observations],
            [row['module'] for row in profiles['modules']],
        )

    def test_native_binding_blobs_and_exports_bind_the_current_checkout(self):
        _, historical = self.merged_native_observations()
        actual = c.current_native_bindings(c.ROOT)
        self.assertEqual(actual['sourceSha'], c.git(c.ROOT, 'rev-parse', 'HEAD').decode().strip())
        self.assertEqual(actual['sourceTree'], c.git(c.ROOT, 'rev-parse', 'HEAD^{tree}').decode().strip())
        for observed, registered in zip(actual['observations'], historical, strict=True):
            data = (c.ROOT / registered['path']).read_bytes()
            self.assertEqual(observed, dict(registered, blobSha=c.blob(data), historicalBlobSha=registered['blobSha']))
        self.assertFalse(actual['consumerCallsitesProved'])
        self.assertFalse(actual['productExecutionProved'])

class GraphAndEvolutionTests(unittest.TestCase):
    def test_stable_topology(self): self.assertEqual(c.topo(['b','a','c'],[('a','c'),('b','c')]),['a','b','c'])
    def test_cycle_rejects(self):
        with self.assertRaises(c.Invalid): c.topo(['a','b'],[('a','b'),('b','a')])
    def test_unknown_edge(self):
        with self.assertRaises(c.Invalid): c.topo(['a'],[('a','x')])
    def test_duplicate_edge(self):
        with self.assertRaises(c.Invalid): c.topo(['a','b'],[('a','b'),('a','b')])
    def test_total_disjoint_split(self): c.partition(['a','b','c'],{'left':['a'],'right':['b','c']})
    def test_duplicate_writer_partition(self):
        with self.assertRaises(c.Invalid): c.partition(['a','b'],{'left':['a'],'right':['a','b']})
    def test_omitted_fact_partition(self):
        with self.assertRaises(c.Invalid): c.partition(['a','b'],{'left':['a']})
    def test_all_handoff_phases(self):
        for i,phase in enumerate(c.PHASES): c.handoff(phase,i<3,i>=7,i==0,i>=8,4,5)
    def test_two_valid_writers(self):
        with self.assertRaises(c.Invalid): c.handoff('new_writer_fenced',True,True,False,False,4,5)
    def test_new_admission_before_route(self):
        with self.assertRaises(c.Invalid): c.handoff('new_writer_fenced',False,True,False,True,4,5)
    def test_stale_fence(self):
        with self.assertRaises(c.Invalid): c.handoff('prepared',True,False,True,False,4,4)
    def test_unknown_effect_blocks_cutover(self):
        with self.assertRaises(c.Invalid): c.handoff('old_writer_fenced',False,False,False,False,4,5,1)
    def test_rollback_preserves_delta(self): c.rollback_required_delta(3,3,True,False)
    def test_rollback_old_snapshot_loses_delta(self):
        with self.assertRaises(c.Invalid): c.rollback_required_delta(3,0,True,False)
    def test_revoked_rollback_rejects(self):
        with self.assertRaises(c.Invalid): c.rollback_required_delta(0,0,True,True)
    def test_current_epoch_admission(self): c.admit(4,4,'a'*64,'a'*64)
    def test_revoke_blocks_later_admission(self):
        with self.assertRaises(c.Invalid): c.admit(4,5,'a'*64,'a'*64)
    def test_clamp_requires_new_binding(self):
        with self.assertRaises(c.Invalid): c.admit(4,4,'a'*64,'b'*64)
    def test_path_escape_rejects(self):
        with self.assertRaises(c.Invalid): c.inside(BASE,'../../escape')
