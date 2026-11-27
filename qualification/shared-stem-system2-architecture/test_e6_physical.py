"""Adversarial E6 physical/fan-out contracts, deliberately NO pretrained tests."""
from __future__ import annotations

import dataclasses
import hashlib
import unittest

import numpy as np

from budget import CellUse
from e6_physical import Source, bench, build_sources, execute, make_bank


class E6Physical(unittest.TestCase):
    def sample(self, n=16, groups=4, split=False):
        uses,sources=build_sources(n,groups,split_scope=split)
        return uses,sources,make_bank(n)

    def test_exact_distinct_physical_tensor_geometry(self):
        uses,sources,bank=self.sample(32)
        self.assertEqual(sum(getattr(bank,name).size for name in ('down','gate','gb','up','out','ob')),32*9744)
        self.assertEqual(bank.down.dtype,np.float32)
        self.assertEqual(bank.down.shape,(32,8,384))
        self.assertEqual(bank.out.shape,(32,8,384))
        self.assertEqual(bank.state.shape,(32,64))

    def test_same_logits_and_head_calls_across_real_synthetic_forward_count(self):
        uses,sources,bank=self.sample(16)
        no=execute(uses,sources,bank,reuse=False,authorize=lambda _k: True)
        yes=execute(uses,sources,bank,reuse=True,authorize=lambda _k: True)
        self.assertEqual(no['logits_sha256'],yes['logits_sha256'])
        self.assertEqual(no['synthetic_encoder_invocations'],16)
        self.assertEqual(yes['synthetic_encoder_invocations'],4)
        self.assertEqual(yes['real_cell_head_forwards'],16)
        self.assertEqual(yes['actual_pretrained_encoder_invocations'],0)
        self.assertIs(yes['production_accepted'],False)

    def test_every_cache_hit_requires_fresh_check(self):
        uses,sources,bank=self.sample()
        approvals=[]
        def approve(key):
            approvals.append(key)
            return True
        out=execute(uses,sources,bank,reuse=True,authorize=approve)
        self.assertEqual(len(approvals),16)
        self.assertEqual(out['separately_authorized_cell_uses'],16)

    def test_revocation_denies_even_when_source_already_encodable(self):
        uses,sources,bank=self.sample()
        calls=[0]
        def revoke(_):
            calls[0]+=1
            return calls[0]<4
        with self.assertRaises(PermissionError):
            execute(uses,sources,bank,reuse=True,authorize=revoke)
        self.assertEqual(calls[0],4)

    def test_identical_source_bytes_cannot_cross_scope(self):
        uses,sources,bank=self.sample(16,1,split=True)
        out=execute(uses,sources,bank,reuse=True,authorize=lambda _: True)
        self.assertEqual(out['unique_scoped_sources'],2)
        self.assertEqual(out['synthetic_encoder_invocations'],2)

    def test_reject_raw_source_mutation_without_digest_change(self):
        uses,sources,bank=self.sample()
        key=uses[0].identity
        mutated=dict(sources)
        old=mutated[key]
        tampered=bytes([old.raw_float32[0] ^ 0x01])+old.raw_float32[1:]
        mutated[key]=Source(key,tampered)
        with self.assertRaises(ValueError):
            execute(uses,mutated,bank,reuse=True,authorize=lambda _: True)

    def test_reject_missing_source_and_wrong_binding(self):
        uses,sources,bank=self.sample()
        mutated=dict(sources)
        mutated.pop(uses[0].identity)
        with self.assertRaises(ValueError):
            execute(uses,mutated,bank,reuse=False,authorize=lambda _: True)
        bad=dict(sources)
        bad[uses[0].identity]=Source(uses[1].identity,b'bad')
        with self.assertRaises(ValueError):
            execute(uses,bad,bank,reuse=True,authorize=lambda _: True)

    def test_reject_nan_in_raw_float32_even_when_digest_matches(self):
        uses,sources,bank=self.sample(8)
        key=uses[0].identity
        inp=bytearray(sources[key].raw_float32)
        inp[:4]=np.float32(np.nan).tobytes()
        from budget import FeatureIdentity
        k=dataclasses.replace(key,source_sha256=hashlib.sha256(inp).hexdigest())
        new_uses=[CellUse(x.cell_id,k if x.identity==key else x.identity) for x in uses]
        new_sources={x:y for x,y in sources.items() if x!=key}
        new_sources[k]=Source(k,bytes(inp))
        with self.assertRaises(ValueError):
            execute(new_uses,new_sources,bank,reuse=True,authorize=lambda _: True)

    def test_wrong_tensor_geometry_detected_before_any_execution(self):
        uses,sources,bank=self.sample()
        bad=dataclasses.replace(bank,down=bank.down[:15])
        with self.assertRaises(ValueError):
            execute(uses,sources,bad,reuse=True,authorize=lambda _: True)

    def test_zero_mode_false_final_use_is_not_bool_true(self):
        uses,sources,bank=self.sample(8)
        for v in (None,1,False,'yes'):
            with self.subTest(v=v),self.assertRaises(PermissionError):
                execute(uses,sources,bank,reuse=True,authorize=lambda _: v)

    def test_duplicate_cell_identity_rejected(self):
        uses,sources,bank=self.sample()
        uses[1]=dataclasses.replace(uses[1],cell_id=uses[0].cell_id)
        with self.assertRaises(ValueError):
            execute(uses,sources,bank,reuse=True,authorize=lambda _: True)

    def test_cost_observation_separates_head_work_from_model_work(self):
        report=bench(32,4,2,False)
        self.assertEqual(report['head_bank_trainable_weight_bytes'],32*9744*4)
        self.assertEqual(report['arms']['cached']['synthetic_encoder_invocations_per_trial'],4)
        self.assertEqual(report['arms']['no_feature_reuse']['synthetic_encoder_invocations_per_trial'],32)
        self.assertTrue(report['all_observed_outputs_identical'])
        self.assertFalse(report['full_end_to_end_cost_qualified'])
        self.assertFalse(report['p95_p99_latency_qualified'])

    def test_noncanonical_profile_and_invalid_modes_rejected(self):
        uses,sources,bank=self.sample()
        for flag in (None,0,1,'cached'):
            with self.subTest(flag=flag),self.assertRaises(ValueError):
                execute(uses,sources,bank,reuse=flag,authorize=lambda _: True)
        for n in (0,4097,True):
            with self.subTest(n=n),self.assertRaises(ValueError):
                make_bank(n)
        with self.assertRaises(ValueError):
            bench(32,4,0,False)

    def test_nonfalse_functional_semantics_and_pretrained_absence(self):
        result=bench(32,32,1,False)
        self.assertEqual(result['arms']['cached']['synthetic_encoder_invocations_per_trial'],32)
        self.assertEqual(result['arms']['no_feature_reuse']['synthetic_encoder_invocations_per_trial'],32)
        self.assertEqual(result['real_pretrained_forward_count'],0)
        self.assertEqual(result['authority'],'DENY_ALL')


if __name__=='__main__':
    unittest.main()
