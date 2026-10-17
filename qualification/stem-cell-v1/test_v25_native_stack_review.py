"""Negative controls and original-pretrained frozen feature replay for V25.

The source-only portion uses *authored synthetic* CPU tensors and receipts;
its passes are never counted as native Rust execution. Original cases require
an externally staged immutable original model/feature input.
"""
from __future__ import annotations

import ast
from copy import deepcopy
import os
from pathlib import Path
import tempfile
import unittest

import numpy as np

import v24_rust_original_review as frozen
import v25_native_stack_review as review


def fake_report(n=64, schema=review.V25_SCHEMA):
    names = ("scalar_full", "packed_full", "packed_active32")
    rows = list(range(1, 129))
    result = {"schema": schema, "authority": "DENY_ALL", "production_authorized": False,
        "rust_source_input_is_signature_authenticated": False,
        "worker_model_driver_integrated": False, "q24_policy_parity_verified": False,
        "original_encoder_forward_count": 0, "future_source_count": 0,
        "original_pretrained_cell_skills": 2, "physically_allocated_head_slots": n,
        "logical_active_heads": 32, "feature_width": 384, "original_train_probes": 4,
        "source_feature_sha256": frozen.SRC_SHA, "v16_model_sha256": frozen.MODEL_SHA,
        "v15_mean_sha256": "a"*64, "research_generation": 11, "research_fence": 17,
        "research_epoch": 23, "research_scope": 29, "research_principal": 31,
        "research_purpose": 37, "allocated_head_weight_bytes": n*1540*4,
        "selected_cache_head_weight_bytes": 32*1540*4,
        "shared_feature_bytes": 4*384*4, "timed_rounds": 128, "warmups": 8,
        "comparison_only_accumulation": "f64-of-original-f32",
        "max_reference_packed_logit_abs_error": 0.0,
        "rolling_consumed_output": 42.0,
        "whole_process_rss_after_bank_bytes": 60000000,
        "whole_process_peak_rss_bytes": 61000000,
        "stack_tile_scratch_bytes": 512,
        "tile_heap_scratch_buffers_per_invocation": 0,
        "tile_width": 16, "measured_hardware_memory_bandwidth": False,
        "production_q24_backend_executed": False}
    for name in names:
        result[name+"_wall_samples_ns"] = rows
    result.update(scalar_p99_ms=frozen.quantile(rows,.99),
        packed_p99_ms=frozen.quantile(rows,.99),
        active32_p99_ms=frozen.quantile(rows,.99))
    return result


def simulated_fused(feature, weights, bias, slots):
    """Independent Python translation, *not* a Rust proof or timing run."""
    output = np.empty((slots,4),dtype=np.float32)
    for begin in range(0,slots,16):
        size=min(16,slots-begin)
        accum=np.stack([bias[(begin+i)%2].astype(np.float64) for i in range(size)])
        for dim in range(384):
            x=float(feature[dim])
            for local in range(size):
                idx=(begin+local)%2
                accum[local] += weights[idx,:,dim].astype(np.float64)*x
        output[begin:begin+size]=accum.astype(np.float32)
    return output


class SourceOnly(unittest.TestCase):
    def test_source_is_independent_of_fused_producer(self):
        src = ast.parse(Path(review.__file__).read_text())
        imports=[]
        for node in ast.walk(src):
            if isinstance(node,ast.Import):imports.extend(n.name for n in node.names)
            if isinstance(node,ast.ImportFrom):imports.append(node.module or '')
        self.assertNotIn('native_v25_stack_tile', imports)
        self.assertFalse(any(n.startswith('torch') for n in imports))

    def test_standalone_rust_source_declares_fixed_tile_and_denies_authority(self):
        data=Path(review.__file__).with_name('native_v25_stack_tile.rs').read_text()
        self.assertIn('let mut accumulators = [[0f64; CLASSES]; 16];',data)
        self.assertIn('for dimension in 0..WIDTH',data)
        self.assertIn('let shared_x = feature[dimension] as f64',data)
        self.assertNotIn('vec![[0f64; CLASSES]; tile.len()]',data)
        self.assertIn('"production_authorized\\":false',data)
        self.assertIn('#![forbid(unsafe_code)]',data)
        self.assertIn('fn stack_tiled_kernel_matches_scalar_bitwise_with_actual_nonzero_values()',data)

    def test_reference_report_complete_and_p99_recomputed(self):
        p=fake_report()
        self.assertEqual(review.require_common(p,64,'a'*64,review.V25_SCHEMA)['packed_full']['samples'],128)

    def test_all_hard_authority_or_provenance_drift_denied(self):
        keys={"production_authorized":True,"rust_source_input_is_signature_authenticated":True,
            "worker_model_driver_integrated":True,"q24_policy_parity_verified":True,
            "original_encoder_forward_count":1,"future_source_count":1,
            "original_pretrained_cell_skills":4096,"allocated_head_weight_bytes":1234,
            "research_generation":99,"v16_model_sha256":"0"*64,
            "max_reference_packed_logit_abs_error":1e-7}
        for key,value in keys.items():
            with self.subTest(key=key):
                p=fake_report();p[key]=value
                with self.assertRaises(ValueError):
                    review.require_common(p,64,'a'*64,review.V25_SCHEMA)

    def test_fake_time_samples_or_extra_numerical_data_denied(self):
        cases=[("packed_p99_ms", 99.),("scalar_full_wall_samples_ns",[1,2,3]),
               ("packed_active32_wall_samples_ns",[0]*128),
               ("whole_process_peak_rss_bytes",59000000)]
        for key,value in cases:
            with self.subTest(key=key):
                p=fake_report();p[key]=value
                with self.assertRaises(ValueError):
                    review.require_common(p,64,'a'*64,review.V25_SCHEMA)

    def test_compare_binary_original_logits_and_tamper(self):
        output=np.ones((4,64,4),dtype='<f4')
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)/'native.bin';dest.write_bytes(output.tobytes())
            data,error=review.read_proof(dest,64,output,schema=review.V25_SCHEMA)
            self.assertEqual(error,0.)
            self.assertEqual(len(data),4*64*4*4)
            dest.write_bytes(b'0'*len(data))
            with self.assertRaises(ValueError):
                review.read_proof(dest,64,output,schema=review.V25_SCHEMA)

    def test_duplicate_or_missing_native_output_bytes_denied(self):
        original_data=np.ones((4,64,4),dtype='<f4')
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)/'native.bin'
            for data in (original_data.tobytes()[:-4],original_data.tobytes()+b'X'):
                dest.write_bytes(data)
                with self.assertRaises(ValueError):
                    review.read_proof(dest,64,original_data,schema=review.V25_SCHEMA)

    def test_reused_feature_fused_vs_independent_baseline_on_authored_fixture(self):
        rng=np.random.default_rng(250)
        feature=rng.normal(0,.03,384).astype('<f4')
        weights=rng.normal(0,.05,(2,4,384)).astype('<f4')
        bias=rng.normal(0,.05,(2,4)).astype('<f4')
        n=64
        fused=simulated_fused(feature,weights,bias,n)
        independent=np.stack([(weights[i%2].astype(np.float64)@feature.astype(np.float64)
                              +bias[i%2].astype(np.float64)).astype(np.float32)
                             for i in range(n)])
        self.assertTrue(np.allclose(fused,independent,rtol=0,atol=1e-7))
        self.assertTrue(np.array_equal(fused[::2],fused[:1].repeat(32,axis=0)))

    def test_no_assert_dependent_validation(self):
        src=Path(review.__file__).read_text()
        self.assertNotIn('assert ',src)


@unittest.skipUnless(os.environ.get('HEPTA_V25_INPUTS') and os.environ.get('HEPTA_V25_V15') and os.environ.get('HEPTA_V25_V16'),
                     'Exact original model and feature archive not staged')
class OriginalEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs=Path(os.environ['HEPTA_V25_INPUTS'])
        cls.v15=Path(os.environ['HEPTA_V25_V15'])
        cls.v16=Path(os.environ['HEPTA_V25_V16'])

    def test_exact_original_v16_model_source_checked(self):
        source,split,mean_sha=frozen.read_original(self.inputs,self.v15,self.v16)
        self.assertEqual(source.shape,(4,384))
        self.assertEqual(len(mean_sha),64)
        self.assertEqual(set(split),{'centers','heads.0.weight','heads.0.bias','heads.1.weight','heads.1.bias'})

    def test_simulated_fused_math_on_original_training_case(self):
        original_features,split,_=frozen.read_original(self.inputs,self.v15,self.v16)
        w=np.stack([split[f'heads.{i}.weight'] for i in (0,1)])
        b=np.stack([split[f'heads.{i}.bias'] for i in (0,1)])
        output=simulated_fused(original_features[0],w,b,64)
        expected=frozen.independent_logits(original_features,split,64)[0]
        self.assertLess(float(np.max(np.abs(output-expected))),2e-6)
        self.assertTrue(np.array_equal(output.argmax(1),expected.argmax(1)))
        self.assertNotEqual(float(output[0].max()),float(output[1].max()))

if __name__=='__main__':unittest.main()
