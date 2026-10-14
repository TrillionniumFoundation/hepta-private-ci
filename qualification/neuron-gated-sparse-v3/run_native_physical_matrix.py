#!/usr/bin/env python3
"""Execute all 20 physically learned private temporal weight files using Rust Q24.

The real Rust kernel is invoked by a pinned native executable (never a mock
when used for evidence). This is a SHADOW MECHANISM test: not a trained Head,
NDU benefit, production Cell owner, device attestation or crash recovery.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from candidate_inventory import verify_artifact
from native_float_gap import compare as floating_gap
from head_q24_oracle import verify_native_head
from matched_train import (CAPS, ARMS, sha_file, unique_json, require,
                           require_selected_owner_a0)

SCHEMA = 'hepta.neuron.twenty-physical-q24-mechanism-matrix.v1'
RUN_SCHEMA = 'hepta.neuron.physical-trained-q24-mechanism-replay.v2'
MAX_STDOUT = 16 << 20


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def independently_recheck_a0_for_native_use(
        receipt: dict, *, synthetic_canary: bool,
        selected_v1: Path | None = None, selected_v1_sha256: str | None = None,
        a0_evidence_root: Path | None = None, a0_trusted_public_key: Path | None = None,
        a0_expected_host_id: str | None = None,
        a0_max_age_seconds: int = 300) -> dict:
    # The untrusted training receipt is not independent A0 evidence. Native
    # replay must recheck current signed owner records instead of inheriting a
    # claimed evidence_class string. Synthetic runs remain explicit and denied.
    if synthetic_canary:
        require(all(x is None for x in (
            selected_v1, selected_v1_sha256, a0_evidence_root,
            a0_trusted_public_key, a0_expected_host_id)),
            'synthetic canary cannot be passed as a live selected owner')
        return {'a0_rechecked': False, 'a0_evidence_class': 'SYNTHETIC_FIXTURE_ONLY'}
    require(all(x is not None for x in (
        selected_v1, selected_v1_sha256, a0_evidence_root,
        a0_trusted_public_key, a0_expected_host_id)),
        'fresh signed A0 owner, public key and selected physical V1 required for native replay')
    require(type(a0_max_age_seconds) is int and 1 <= a0_max_age_seconds <= 86_400,
            'A0 signed owner evidence freshness cap invalid')
    require(receipt.get('evidence_class') == 'SIGNED_A0_FORMAT_ONLY_NOT_HOST_EXECUTION',
            'not a signed-format A0 training receipt')
    require(selected_v1_sha256 == receipt.get('no_change_v1_selected_sha256'),
            'selected V1 baseline digest differs from frozen research train receipt')
    sha_file(selected_v1, selected_v1_sha256)
    from argparse import Namespace
    namespace = Namespace(
        synthetic_canary=False, a0_evidence_root=str(a0_evidence_root),
        a0_trusted_public_key=str(a0_trusted_public_key),
        a0_expected_host_id=a0_expected_host_id,
        a0_max_age_seconds=a0_max_age_seconds)
    current = require_selected_owner_a0(
        namespace, receipt['cell_id'], selected_v1_sha256)
    for field in (
        'a0_registry_sha256', 'a0_host_id',
        'a0_checkpoint_digest_claimed', 'a0_generation_claimed',
    ):
        require(current[field] == receipt.get(field),
                f'current A0 owner evidence drift: {field}')
    return {'a0_rechecked': True,
            'a0_evidence_class': 'SIGNED_A0_FORMAT_ONLY_NOT_HOST_EXECUTION',
            'live_host_execution_independently_attested': False}


def evaluate(binary: Path, binary_sha: str, root: Path, receipt_sha: str,
             trace: Path, trace_sha: str, *, synthetic_canary: bool = False,
             selected_v1: Path | None = None, selected_v1_sha256: str | None = None,
             a0_evidence_root: Path | None = None,
             a0_trusted_public_key: Path | None = None,
             a0_expected_host_id: str | None = None,
             a0_max_age_seconds: int = 300) -> dict:
    require(not binary.is_symlink() and not trace.is_symlink() and not root.is_symlink(),
            'symlinked benchmark input is not a frozen source')
    sha_file(binary, binary_sha)
    sha_file(trace, trace_sha)
    frozen_trace = unique_json(trace.read_bytes())
    require(type(frozen_trace) is dict and
            frozen_trace.get('schema') == 'hepta.neuron.physical-q24-shadow-trace.v1'
            and type(frozen_trace.get('events')) is list,
            'unknown original Q24 test trace')
    source = root / 'training-receipt.json'
    sha_file(source, receipt_sha)
    receipt = unique_json(source.read_bytes())
    require(type(receipt) is dict and
            receipt.get('schema') == 'hepta.neuron.five-arm-differentiable-shadow-train.v1',
            'unknown training receipt version')
    cls = receipt.get('evidence_class')
    require(cls == ('SYNTHETIC_FIXTURE_ONLY' if synthetic_canary else
                    'SIGNED_A0_FORMAT_ONLY_NOT_HOST_EXECUTION'),
            'missing actual A0 format or explicit synthetic canary')
    require(receipt.get('native_q24_parity_verified') is False and
            receipt.get('no_change_optimizer_steps') == 0 and
            receipt.get('production_qualification') is False,
            'training receipt has fabricated production/native qualification')
    current_a0 = independently_recheck_a0_for_native_use(
        receipt, synthetic_canary=synthetic_canary,
        selected_v1=selected_v1, selected_v1_sha256=selected_v1_sha256,
        a0_evidence_root=a0_evidence_root,
        a0_trusted_public_key=a0_trusted_public_key,
        a0_expected_host_id=a0_expected_host_id,
        a0_max_age_seconds=a0_max_age_seconds)
    models = receipt.get('models')
    require(type(models) is list and len(models) == 20, '20 physical trained arms required')
    bound = {}
    for m in models:
        require(type(m) is dict and type(m.get('cap')) is int and m['cap'] in CAPS
                and m.get('arm') in ARMS and (m['cap'], m['arm']) not in bound,
                'duplicate or unexpected trained model')
        cap, arm = m['cap'], m['arm']
        relative = f'{cap}/{arm}.safetensors'
        require(m.get('weight_file') == relative and type(m.get('optimizer_steps')) is int
                and m['optimizer_steps'] == receipt.get('candidate_optimizer_steps')
                and m.get('quantization_saturations') == 0,
                'trained file/steps/Q24 publication clamp changed')
        path = root / relative
        require(not path.is_symlink() and not path.parent.is_symlink(),
                'symlinked Cell model path')
        physical = verify_artifact(
            path, m['weight_sha256'], arm=arm, width=m['width'], rank=m['rank'],
            expected_count=m['parameter_count'])
        require(physical['private_parameter_count'] <= cap, 'private cap exceeded')
        bound[cap,arm] = m
    require(set(bound) == {(cap, arm) for cap in CAPS for arm in ARMS},
            'missing full 5x4 trained candidate matrix')

    results = []
    for cap in CAPS:
        for arm in ARMS:
            m = bound[cap, arm]
            path = root / m['weight_file']
            command = [
                str(binary), '--arm', arm, '--model', str(path),
                '--model-sha256', m['weight_sha256'],
                '--trace', str(trace), '--trace-sha256', trace_sha,
                '--cap', str(cap)]
            if arm == 'min_gru':
                command.extend(('--rank', str(m['rank'])))
            started = time.perf_counter_ns()
            try:
                completed = subprocess.run(command, stdin=subprocess.DEVNULL,
                                           stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE,
                                           timeout=30, check=False)
            except subprocess.TimeoutExpired as exc:
                raise ValueError(f'{cap}/{arm}: native Rust Q24 timed out') from exc
            elapsed_us = (time.perf_counter_ns() - started) // 1000
            require(completed.returncode == 0 and
                    0 < len(completed.stdout) <= MAX_STDOUT and
                    len(completed.stderr) <= (1 << 16),
                    f'{cap}/{arm}: native Q24 failed or output was oversized: '
                    + completed.stderr[:1500].decode('utf-8', errors='replace'))
            parsed = unique_json(completed.stdout)
            require(type(parsed) is dict and parsed.get('schema') == RUN_SCHEMA
                    and parsed.get('arm') == arm
                    and parsed.get('selected_private_weight_sha256') == m['weight_sha256']
                    and parsed.get('trace_sha256') == trace_sha
                    and parsed.get('private_parameter_cap') == cap
                    and parsed.get('private_parameter_count') == m['parameter_count']
                    and parsed.get('width') == m['width']
                    and parsed.get('native_q24_kernel_invoked') is True
                    and parsed.get('independent_empty_state_replay_equal') is True
                    and parsed.get('f32_head_executed') is False
                    and parsed.get('quantized_q24_head_executed_in_rust') is True
                    and parsed.get('f32_to_q24_head_round_ties_even_profile') == 'hepta.neuron.f32-q24-head.v1'
                    and parsed.get('torch_f32_native_q24_prediction_parity_verified') is False
                    and parsed.get('crash_recovery_verified') is False
                    and parsed.get('production_qualification') is False
                    and parsed.get('ndu_eligible') is False
                    and parsed.get('decision') == 'NO_PROMOTION',
                    f'{cap}/{arm}: native receipt identity/authority drift')
            frontier = parsed.get('frontier')
            require(type(frontier) is list and
                    len(frontier) == parsed.get('original_tick_count') and len(frontier) > 0,
                    f'{cap}/{arm}: native frontier missing')
            for ix, row in enumerate(frontier):
                require(type(row) is dict and row.get('sequence') == ix+1 and
                        type(row.get('checkpoint_sha256')) is str and
                        len(row['checkpoint_sha256']) == 64,
                        f'{cap}/{arm}: malformed ordered Q24 receipt')
                if ix:
                    require(row.get('predecessor_sha256') ==
                            frontier[ix-1]['checkpoint_sha256'],
                            f'{cap}/{arm}: broken native checkpoint chain')
            # Independently start the *same* frozen native executable in a
            # second OS process. In-process cold replay alone can miss process-
            # global initialization, allocation or runtime nondeterminism.
            sha_file(path, m['weight_sha256'])
            sha_file(binary, binary_sha)
            sha_file(trace, trace_sha)
            try:
                second = subprocess.run(command, stdin=subprocess.DEVNULL,
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, timeout=30, check=False)
            except subprocess.TimeoutExpired as exc:
                raise ValueError(f'{cap}/{arm}: second native Q24 process timed out') from exc
            require(second.returncode == 0 and
                    0 < len(second.stdout) <= MAX_STDOUT and
                    len(second.stderr) <= (1 << 16),
                    f'{cap}/{arm}: second native process failed or produced oversized output')
            second_receipt = unique_json(second.stdout)
            require(second_receipt == parsed,
                    f'{cap}/{arm}: independent-process native Q24 receipt/frontier mismatch')
            sha_file(path, m['weight_sha256'])
            sha_file(binary, binary_sha)
            sha_file(trace, trace_sha)
            integer_head_oracle = verify_native_head(path, parsed)
            gap = floating_gap(path, arm=arm, width=m['width'], rank=m['rank'],
                               native_trace=frozen_trace, native_result=parsed)
            require(gap['bitwise_float_to_q24_prediction_parity_proven'] is False and
                    gap['production_qualification'] is False,
                    'float/native gap analyzer forged model qualification')
            results.append({
                'q24_head_integer_oracle':integer_head_oracle,
                'float_surrogate_vs_native_q24_state_gap':gap,
                'arm': arm, 'private_parameter_cap': cap,
                'fresh_process_count': 2,
                'independent_rust_processes_bit_identical': True,
                'second_process_raw_stdout_sha256': sha(second.stdout),
                'native_process_wall_micros_not_target_host_slo': elapsed_us,
                'physical_artifact_sha256': m['weight_sha256'],
                'q24_checkpoint_chain_final': frontier[-1]['checkpoint_sha256'],
                'q24_replay_evidence_sha256': sha(
                    json.dumps(parsed, sort_keys=True, separators=(',', ':')).encode()),
                'native_receipt': parsed,
            })
    return {
        'schema': SCHEMA, 'evidence_class': ('SYNTHETIC_NATIVE_RESEARCH_ONLY' if synthetic_canary
                                            else 'SIGNED_A0_FORMAT_NATIVE_RESEARCH_ONLY'),
        'selected_executable_sha256': binary_sha,
        'same_frozen_trace_sha256': trace_sha,
        'training_receipt_sha256': receipt_sha,
        'frozen_a0_owner_revalidation': current_a0,
        'twenty_native_physical_model_executions': len(results),
        'forty_fresh_native_process_invocations': len(results)*2,
        'cross_process_q24_frontier_and_head_receipts_equal': len(results)==20,
        'native_q24_temporal_replay_executed': True,
        'diagnostic_native_vs_float_gap_rows': len(results),
        'quantized_native_head_integer_oracle_matches': len(results),
        'full_selected_model_head_executed': False,
        'floating_torch_native_q24_prediction_parity_verified': False,
        'real_target_host_attested': False, 'crash_durable_recovery_verified': False,
        'ndu_eligible': False, 'production_qualification': False,
        'decision': 'NO_MODEL_PROMOTION', 'results': results,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    for x in ('binary','binary-sha256','trained-root','receipt-sha256','trace',
              'trace-sha256','report'):
        p.add_argument('--'+x, required=True)
    p.add_argument('--synthetic-canary', action='store_true')
    p.add_argument('--selected-v1', type=Path)
    p.add_argument('--selected-v1-sha256')
    p.add_argument('--a0-evidence-root', type=Path)
    p.add_argument('--a0-trusted-public-key', type=Path)
    p.add_argument('--a0-expected-host-id')
    p.add_argument('--a0-max-age-seconds', type=int, default=300)
    args = p.parse_args()
    try:
        result = evaluate(
            Path(args.binary), args.binary_sha256,
            Path(args.trained_root), args.receipt_sha256,
            Path(args.trace), args.trace_sha256,
            synthetic_canary=args.synthetic_canary,
            selected_v1=args.selected_v1,
            selected_v1_sha256=args.selected_v1_sha256,
            a0_evidence_root=args.a0_evidence_root,
            a0_trusted_public_key=args.a0_trusted_public_key,
            a0_expected_host_id=args.a0_expected_host_id,
            a0_max_age_seconds=args.a0_max_age_seconds)
        with Path(args.report).open('x',encoding='utf-8') as f:
            json.dump(result, f, sort_keys=True, indent=2)
            f.write('\n')
        print(json.dumps({'status':'NATIVE_Q24_TEMPORAL_RESEARCH_ONLY',
                          'physical_models':20, 'production_qualification':False,
                          'native_head_parity_verified':False}))
        return 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as e:
        print(json.dumps({'status':'BLOCKED_NATIVE_Q24_PHYSICAL_MATRIX',
                          'reason':str(e),'production_qualification':False}),
              file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
