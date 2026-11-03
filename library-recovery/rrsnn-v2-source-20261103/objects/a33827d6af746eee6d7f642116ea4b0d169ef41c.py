"""Run source-integrity, contract, and quantization checks for the offline adapter."""
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
import unittest

import numpy as np

from shadow_contract import (
    Q24, Q24_LIMIT, SOURCE_COMMIT, ZERO, decode_tick_input,
    feature_digest_q24, make_shadow_proposal, quantize_q24, tick_semantic_digest,
)

ROOT = Path(__file__).resolve().parent


def source_protocol_fixture():
    """Numerical/identity fixture from upstream protocol_tests.rs, not production data."""
    vector = [Q24, 0, -Q24]
    digest = lambda x: hashlib.sha256(x).hexdigest()
    return {
        'tickId': 'tick.input.protocol.1', 'subjectId': 'subject.protocol.1',
        'logicalSequence': 1, 'monotonicTimeMicros': 42,
        'checkpointDigest': ZERO, 'inputFeatureDigest': feature_digest_q24(vector),
        'featureVectorQ24': vector, 'objectiveDigest': digest(b'objective'),
        'nduSnapshotDigest': digest(b'ndu'), 'bodyGeneration': 7,
        'modulatorDigest': digest(b'modulator'),
    }


class ContractChecks(unittest.TestCase):
    def decode(self, tick):
        return decode_tick_input(json.dumps(tick).encode())

    def test_source_fixture_roundtrip_and_byte_binding(self):
        tick = source_protocol_fixture()
        self.assertEqual(self.decode(tick), tick)
        self.assertEqual(len(tick_semantic_digest(tick)), 64)
        changed = copy.deepcopy(tick)
        changed['featureVectorQ24'][0] += 1
        with self.assertRaises(ValueError):
            self.decode(changed)
        changed['inputFeatureDigest'] = feature_digest_q24(changed['featureVectorQ24'])
        self.assertNotEqual(tick_semantic_digest(tick), tick_semantic_digest(changed))

    def test_unknown_and_duplicate_fields_rejected(self):
        tick = source_protocol_fixture()
        tick['unknownCritical'] = True
        with self.assertRaises(ValueError):
            self.decode(tick)
        with self.assertRaises(ValueError):
            decode_tick_input(b'{"tickId":"a","tickId":"b"}')

    def test_scope_clock_and_identity_affect_semantics(self):
        tick = source_protocol_fixture()
        baseline = tick_semantic_digest(tick)
        for key, value in [('subjectId','subject.protocol.2'),('tickId','tick.input.protocol.2'),
                           ('monotonicTimeMicros',43),('bodyGeneration',8),
                           ('objectiveDigest',hashlib.sha256(b'other').hexdigest())]:
            changed = dict(tick)
            changed[key] = value
            self.assertNotEqual(baseline,tick_semantic_digest(changed))

    def test_invalid_dimensions_numbers_and_digests(self):
        for vec in [[], [0]*513, [Q24_LIMIT+1], [True], [1.0]]:
            with self.assertRaises(ValueError):
                feature_digest_q24(vec)
        for key, value in [('logicalSequence',0),('monotonicTimeMicros',0),
                           ('logicalSequence',True),('logicalSequence',2),
                           ('objectiveDigest',ZERO),('inputFeatureDigest','A'*64),
                           ('subjectId','space not allowed')]:
            changed = source_protocol_fixture()
            changed[key] = value
            with self.assertRaises(ValueError):
                self.decode(changed)

    def test_q24_ties_and_reject_instead_of_clipping(self):
        expected=[0,2,2,0,-2,-2]
        values=[0.5/Q24,1.5/Q24,2.5/Q24,-0.5/Q24,-1.5/Q24,-2.5/Q24]
        self.assertEqual(quantize_q24(values), expected)
        for value in [math.nan,math.inf,-math.inf,8.0001,-8.0001,True]:
            with self.assertRaises(ValueError):
                quantize_q24([value])

    def test_candidate_cannot_look_like_product_receipt(self):
        tick=source_protocol_fixture()
        candidate=make_shadow_proposal(tick,[0,.25,.5,.75,1],hashlib.sha256(b'candidate').hexdigest(),output_width=5)
        self.assertFalse(candidate['productionActivationAllowed'])
        self.assertFalse(candidate['checkpointPublished'])
        self.assertIsNone(candidate['officialRuntimeReceipt'])
        self.assertEqual(candidate['authority'],'NONE')
        self.assertNotIn('runtimeReceipt', candidate)
        with self.assertRaises(ValueError):
            make_shadow_proposal(tick,[0]*4096,hashlib.sha256(b'candidate').hexdigest(),output_width=4096)


def validate():
    provenance=json.loads((ROOT/'provenance.json').read_text())
    integrity=[]
    for item in provenance['source_files']:
        p=ROOT/'sources'/item['path']
        data=p.read_bytes()
        git_sha=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        if git_sha!=item['blob_sha']:
            raise AssertionError('frozen source bytes do not match Git blob '+item['path'])
        item['bytes_utf8']=len(data)
        item['sha256']=hashlib.sha256(data).hexdigest()
        integrity.append({'path':item['path'],'git_blob_verified':True})
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(ContractChecks)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    rng=np.random.default_rng(101)
    raw=rng.uniform(-8,8,100_000)
    q=np.asarray(quantize_q24(raw),dtype=np.int64)
    restored=q.astype(float)/Q24
    max_error=float(np.max(np.abs(restored-raw)))
    assert max_error<=.5/Q24+1e-15
    report={
      'source_commit':SOURCE_COMMIT,'source_blob_checks':integrity,
      'source_fixture':'protocol_tests.rs::canonical_tick_input_roundtrip_rejects_unknown_fields',
      'fixture_is_production_observation':False,
      'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
      'quantization_samples':len(raw),'max_abs_roundtrip_error':max_error,
      'half_quantum':.5/Q24,'scope':'Python offline contract transposition and Q24 conversion only',
      'rust_compiled':False,'official_owner_executed':False,'real_encoder_forward':False,
      'actual_hepta_outcomes_used':False,'production_activation_allowed':False,
      'source_fixture_feature_digest':feature_digest_q24(source_protocol_fixture()['featureVectorQ24']),
      'source_fixture_semantic_digest':tick_semantic_digest(source_protocol_fixture()),
    }
    (ROOT/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    (ROOT/'source_protocol_fixture.json').write_text(json.dumps(source_protocol_fixture(),indent=2)+'\n')
    (ROOT/'shadow_validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='source_blob_checks'},indent=2))
    return report


if __name__=='__main__':
    validate()
