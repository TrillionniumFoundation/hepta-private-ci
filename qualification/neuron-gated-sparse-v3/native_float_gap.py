#!/usr/bin/env python3
"""Measure float-surrogate vs Rust-Q24-state differences on identical inputs.

Loads exactly the physical frozen Head/temporal tensors and applies the *same*
floating Head to native Rust Q24 sparse activations for a diagnostic comparison.
The Rust runner does NOT execute the Head. These numbers are not a qualification
of Q24 model parity, label accuracy or future NDU efficacy.
"""
from __future__ import annotations
import math
from pathlib import Path
from typing import Any

from matched_train import Q, make_model, require


def compare(path: Path, *, arm: str, width: int, rank: int | None,
            native_trace: dict[str,Any], native_result: dict[str,Any]) -> dict[str,Any]:
    import torch
    from safetensors.torch import load_file
    torch.set_num_threads(1)
    physical=load_file(str(path),device='cpu')
    model=make_model(arm,width,rank or 0,torch).cpu().eval()
    with torch.no_grad():
        for name, target in model.named_parameters():
            key = ('head.'+name.split('.',1)[1] if name.startswith('head.')
                   else 'temporal.'+name)
            require(key in physical, 'missing physical native/f32 study parameter')
            saved=physical[key]
            require(saved.shape==target.shape, 'float model tensor dimension drift')
            require(saved.dtype==(torch.float32 if name.startswith('head.') else torch.int64),
                    'frozen tensor precision drift')
            target.copy_(saved if name.startswith('head.') else saved.float()/Q)
        events=native_trace['events']
        steps=native_result['frontier']
        require(len(events)==len(steps) and 0<len(events)<=1024,
                'wrong number of Rust native Q24 events')
        for i,row in enumerate(steps):
            require(row['sequence']==i+1 and len(row['activation_q24'])==width,
                    'native Q24 activation order/dimension mismatch')
        x=torch.tensor([r['temporal_drive_q24'] for r in events],
                       dtype=torch.float32)/Q
        tm=[r['monotonic_micros'] for r in events]
        float_logits=model(x,tm).view(-1)
        activations=torch.tensor([r['activation_q24'] for r in steps],
                                 dtype=torch.float32)/Q
        native_state_float_head_logits=model.head(activations).view(-1)
        require(bool(torch.isfinite(float_logits).all()) and
                bool(torch.isfinite(native_state_float_head_logits).all()),
                'nonfinite float/native comparison')
        float_p=torch.sigmoid(float_logits)
        native_head_p=torch.sigmoid(native_state_float_head_logits)
        gap=(float_p-native_head_p).abs()
        max_p=float(gap.max())
        mean_p=float(gap.mean())
        logits_gap=float((float_logits-native_state_float_head_logits).abs().max())
        require(all(math.isfinite(v) for v in (max_p,mean_p,logits_gap)),
                'nonfinite quantitative gap')
        return {
            'schema':'hepta.neuron.native-vs-floating-surrogate-gap.v1',
            'arm':arm, 'width':width, 'compared_event_count':len(events),
            'max_probability_gap_ppm':round(max_p*1_000_000),
            'mean_probability_gap_ppm':round(mean_p*1_000_000),
            'maximum_logit_gap':logits_gap,
            'native_q24_state_provided_by_real_rust_kernel':True,
            'frozen_f32_head_applied_only_in_python':True,
            'causes_of_possible_gap':[
                'quantization-and-ties-even','homeostatic-threshold-and-eligibility',
                'native-local-global-top-k-versus-floating-detached-top-k',
                'SSM-elapsed-time-quantum','native-nonlinear-gate-saturation',
            ],
            'native_f32_head_execution_proven':False,
            'bitwise_float_to_q24_prediction_parity_proven':False,
            'labelled_outcome_quality_verified':False,
            'ndu_eligible':False,
            'production_qualification':False,
        }
