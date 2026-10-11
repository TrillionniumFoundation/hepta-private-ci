import copy
from dataclasses import dataclass, replace
import unittest
from types import SimpleNamespace
from test_stem_projection import Request, d, feature, spec
from shadow_pipeline import ShadowStemHeadPipeline, validate_head, Q
from native_bridge import bundle_digest, tensor_digest


@dataclass(frozen=True)
class CellRequest(Request):
    cell_id: str = 'cell.alpha'


class FrozenFixture:
    def __init__(self):
        self.invocations = 0
    def run(self, requests, *, return_features):
        assert return_features
        self.invocations += 1
        frozen = tuple(feature((.5, -.25, .125)) for _ in requests)
        diag = SimpleNamespace(backend_calls=1, distinct_inputs=1,
                               cache_hits=0, simulated=True)
        return diag, frozen


def head(negative=False):
    weights = [-Q, 0, 0, -Q] if negative else [Q, 0, 0, Q]
    tensors = (weights, [], [], [0, 0], [0, 0], [Q, Q])
    digest = tensor_digest(2, 2, tensors)
    return {'schema': 'hepta.stem.q24-cpu-head-candidate.v1',
            'shadow_only': True, 'production_authorized': False,
            'encoder_digest': d('a'), 'input_width': 2, 'output_width': 2,
            'drive_weights_q24': weights,
            'prediction_weights_q24': [], 'gate_weights_q24': [],
            'drive_bias_q24': [0,0], 'prediction_bias_q24': [0,0],
            'gate_bias_q24': [Q,Q], 'head_digest': digest,
            'weights_digest': bundle_digest(d('a'),digest)}


class PipelineTests(unittest.TestCase):
    def test_one_actual_interface_batch_two_cell_heads(self):
        fake = FrozenFixture()
        pipeline = ShadowStemHeadPipeline(fake,spec(),{'cell.alpha':head(), 'cell.beta':head(True)})
        result = pipeline.run([CellRequest('r1'),CellRequest('r2',cell_id='cell.beta'),
                               CellRequest('r3')])
        self.assertEqual(fake.invocations,1)
        self.assertEqual(len(result.results),3)
        self.assertEqual(result.results[0].logits_q24,(Q//2,-Q//8))
        self.assertEqual(result.results[1].logits_q24,(-Q//2,Q//8))
        self.assertEqual(result.results[0].output_digest,result.results[2].output_digest)
        self.assertNotEqual(result.results[0].output_digest,result.results[1].output_digest)
        self.assertFalse(result.production_authorized)
        self.assertTrue(result.source_is_simulated)

    def test_cross_scope_and_unknown_head_fail_before_encoder(self):
        fake=FrozenFixture()
        pipeline=ShadowStemHeadPipeline(fake,spec(),{'cell.alpha':head()})
        with self.assertRaisesRegex(ValueError,'mixed runtime fence'):
            pipeline.run([CellRequest('r1'),CellRequest('r2',scope_digest=d('9'))])
        with self.assertRaisesRegex(ValueError,'duplicate/unknown'):
            pipeline.run([CellRequest('r1',cell_id='unknown')])
        self.assertEqual(fake.invocations,0)

    def test_changed_head_weights_and_unauthorized_metadata_fail(self):
        fake=FrozenFixture()
        pipeline=ShadowStemHeadPipeline(fake,spec(),{'cell.alpha':head()})
        pipeline.cell_heads['cell.alpha']['drive_weights_q24'][0]+=1
        with self.assertRaisesRegex(ValueError,'digest differs'):
            pipeline.run([CellRequest('r1')])
        self.assertEqual(fake.invocations,0)
        invalid=head()
        invalid['production_authorized']=True
        with self.assertRaisesRegex(ValueError,'unauthorized production'):
            ShadowStemHeadPipeline(fake,spec(),{'cell.alpha':invalid})

    def test_cache_reuse_keeps_output_identity(self):
        fake=FrozenFixture()
        pipeline=ShadowStemHeadPipeline(fake,spec(),{'cell.alpha':head()})
        a=pipeline.run([CellRequest('r1')]); b=pipeline.run([CellRequest('r2')])
        self.assertEqual(a.results[0].output_digest,b.results[0].output_digest)
        self.assertEqual(b.projection_cache_hits,1)
        self.assertFalse(b.production_authorized)


if __name__=='__main__':
    unittest.main()
