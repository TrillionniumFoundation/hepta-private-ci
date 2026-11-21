#!/usr/bin/env python3
"""Read-only provenance and linear-capacity audit of captured private receipts.

This is an offline research reader. It does not contact a host, run a model,
execute captured source, establish broker authenticity, or authorize adoption.
"""
import argparse
import ast
import base64
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import struct
from zoneinfo import ZoneInfo


def strict(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError('DUPLICATE_JSON_KEY')
            out[key] = value
        return out
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('NONFINITE_JSON')))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unwrap(value):
    if 'readback' in value:
        value = value['readback']
    if 'content' in value:
        value = value.get('structuredContent') or strict(next(
            x['text'] for x in value['content'] if x['type'] == 'text'))
    return value


def read_receipt(path):
    result = unwrap(strict(path.read_bytes()))
    require(result.get('truncated') is False, 'INCOMPLETE_READBACK')
    out = {}
    for item in result['files']:
        raw = item['text'].encode('utf-8')
        require(item['eof'] is True and len(raw) == item['size'], 'READBACK_SIZE')
        require(sha(raw) == item['sha256'], 'READBACK_SHA256')
        require(item['path'] not in out, 'DUPLICATE_READBACK_PATH')
        out[item['path']] = item
    return out


def suffix(records, ending):
    matches = [v for k, v in records.items() if k.endswith(ending)]
    require(len(matches) == 1, 'AMBIGUOUS_RECEIPT_SUFFIX:' + ending)
    return matches[0]


def object_at(records, ending):
    return strict(suffix(records, ending)['text'])


def json_identity(value, key):
    require(sha(canonical({k:v for k,v in value.items() if k != key})) == value[key],
            'CANONICAL_IDENTITY:' + key)


def static_value(node):
    if isinstance(node, ast.Constant): return node.value
    if isinstance(node, (ast.List, ast.Tuple)): return [static_value(x) for x in node.elts]
    if isinstance(node, ast.Dict):
        return {static_value(k): static_value(v) for k,v in zip(node.keys, node.values)}
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -static_value(node.operand)
    if isinstance(node, ast.BinOp):
        left, right = static_value(node.left), static_value(node.right)
        require(type(left) in (int,float) and type(right) in (int,float), 'STATIC_NUMERIC')
        if isinstance(node.op, ast.Mult): return left * right
        if isinstance(node.op, ast.Add): return left + right
        if isinstance(node.op, ast.Sub): return left - right
        if isinstance(node.op, ast.Div): return left / right
    raise ValueError('UNSUPPORTED_STATIC_EXPRESSION')


def static_assignment(text, name):
    matches = [n.value for n in ast.parse(text).body if isinstance(n,ast.Assign)
               and any(isinstance(t,ast.Name) and t.id == name for t in n.targets)]
    require(len(matches) == 1, 'STATIC_ASSIGNMENT_COUNT')
    return static_value(matches[0])


def verify_chain(text, collector_sha, period):
    require(text.endswith('\n'), 'UNCOMMITTED_CAPTURE_TAIL')
    events = [strict(line) for line in text.splitlines()]
    previous = '0' * 64
    counts = Counter(); failures = Counter(); last = 0
    for i,event in enumerate(events):
        require(event['schema'] == 'heptatrader.laya-shadow-quotes.v1', 'CAPTURE_SCHEMA')
        require(event['sequence'] == i and event['previous'] == previous, 'CAPTURE_CHAIN')
        require(type(event['at_ms']) is int and event['at_ms'] >= last, 'CAPTURE_CLOCK')
        json_identity(event, 'sha256')
        previous = event['sha256']; last = event['at_ms']; kind = event['kind']
        require(kind in ('HEADER','FAILURE','QUOTE','END'), 'CAPTURE_KIND')
        require((kind == 'HEADER') == (i == 0), 'CAPTURE_HEADER_POSITION')
        require(kind != 'END' or i == len(events)-1, 'CAPTURE_END_POSITION')
        counts[kind] += 1
        if kind == 'FAILURE': failures[event['data']['reason']] += 1
    require(events[-1]['kind'] == 'END', 'CAPTURE_NOT_SEALED')
    header = events[0]['data']
    require(header['collector_sha256'] == collector_sha, 'COLLECTOR_SOURCE_BINDING')
    require(header['period_sha256'] == period and header['execution_domain'] == 'PAPER'
            and header['source'] == 'IB_TOOL_GATEWAY' and header['instrument'] == 'EUR.USD'
            and header['write_operations_allowed'] == [] and header['broker_orders_sent'] == 0,
            'CAPTURE_SCOPE')
    return dict(events=len(events), counts=dict(counts), failure_reasons=dict(failures),
                start_ms=events[0]['at_ms'], end_ms=last, chain_head=previous,
                quote_semantics_revalidated=False,
                scope='Structural chain audit; this selected segment has no QUOTE records')


def parse_head(raw, expected_sha):
    require(len(raw) <= 65536 and sha(raw) == expected_sha, 'HEAD_BYTES')
    require(len(raw) >= 8, 'HEAD_HEADER')
    header_size = struct.unpack('<Q', raw[:8])[0]
    require(0 < header_size < len(raw)-8, 'HEAD_HEADER_SIZE')
    header = strict(raw[8:8+header_size])
    require(set(header) == {'value.bias','value.weight'}, 'HEAD_TENSOR_NAMES')
    out = {}; intervals = []
    for name, shape in [('value.bias',[1]),('value.weight',[1,768])]:
        entry = header[name]; start,end = entry['data_offsets']
        require(entry['dtype'] == 'F32' and entry['shape'] == shape, 'HEAD_SHAPE')
        require(type(start) is int and type(end) is int and 0 <= start < end
                and end <= len(raw)-8-header_size, 'HEAD_OFFSETS')
        count = math.prod(shape)
        require(end-start == 4*count, 'HEAD_TENSOR_SIZE')
        vals = struct.unpack('<' + 'f'*count, raw[8+header_size+start:8+header_size+end])
        require(all(math.isfinite(v) for v in vals), 'HEAD_NONFINITE')
        out[name] = vals; intervals.append((start,end))
    intervals.sort()
    require(intervals[0][0] == 0 and intervals[0][1] == intervals[1][0]
            and intervals[1][1] == len(raw)-8-header_size, 'HEAD_COVERAGE')
    return out


def ny(ms):
    return datetime.fromtimestamp(ms/1000, timezone.utc).astimezone(
        ZoneInfo('America/New_York')).isoformat()


def audit(root):
    status = read_receipt(root/'status_readback.json')
    collector = read_receipt(root/'collector_readback.json')
    plan_records = read_receipt(root/'financial_plan_readback.json')
    deeper = read_receipt(root/'financial_deeper_readback.json')
    installed = read_receipt(root/'installed_financial_source_readback.json')
    collector_source = read_receipt(root/'installed_collector_source_readback.json')
    semantics = read_receipt(root/'financial_semantics_readback.json')
    financial_status = read_receipt(root/'financial_status_receipt.json')
    plan_item = suffix(plan_records, '/plan.json'); plan = strict(plan_item['text'])
    registration = object_at(plan_records, '/registration.json')
    candidate_item = suffix(deeper, '/candidate.json'); candidate = strict(candidate_item['text'])
    assessment = object_at(deeper, '/assessment.json')
    financial = object_at(financial_status, '/evaluator-status.json')
    source = next(strict(v['text']) for v in status.values() if '/source-readiness/' in v['path'])
    control = object_at(status, '/control/status.json')
    endpoint = object_at(status, '/evaluation/status.json')
    for value,key in [(plan,'plan_id'),(candidate,'candidate_id')]: json_identity(value,key)
    require(registration['plan_file_sha256'] == plan_item['sha256']
            and registration['plan_id'] == plan['plan_id'], 'REGISTRATION_BINDING')
    require(candidate_item['sha256'] == plan['candidate_manifest_sha256']
            and candidate['candidate_id'] == plan['candidate_id'], 'CANDIDATE_BINDING')
    require(candidate['head_tensor_sha256'] == plan['head_tensor_sha256'], 'HEAD_PLAN_BINDING')
    require(assessment['candidate_id'] == candidate['candidate_id']
            and assessment['plan_id'] == plan['plan_id'], 'ASSESSMENT_BINDING')
    require(candidate['reward_ids'] == plan['training_reward_ids']
            and candidate['dataset_sha256'] == plan['training_dataset_sha256'], 'TRAINING_BINDING')
    source_pins = {}; verified_runtime_files = []
    for filename,expected in plan['runtime_sha256'].items():
        available = [v for v in list(installed.values())+list(semantics.values())
                     if v['path'].endswith('/'+filename)]
        if available:
            require(all(x['sha256'] == expected for x in available), 'INSTALLED_RUNTIME_BINDING')
            source_pins[filename] = expected
            verified_runtime_files.append(filename)
    for filename,expected in candidate['source_python_sha256'].items():
        item = suffix(semantics, '/'+filename)
        require(item['sha256'] == expected, 'TRAINING_SOURCE_BINDING')
        source_pins[filename] = expected
    rule = static_assignment(suffix(installed,'/financial_forward_protocol.py')['text'], 'RULE')
    profile = static_assignment(suffix(semantics,'/financial_value_data.py')['text'], 'PROFILE')
    require(rule == plan['rule'] and profile == candidate['financial_profile'], 'SEMANTIC_CONTRACT')
    chain = verify_chain(suffix(collector,'/quotes.jsonl')['text'],
                         suffix(collector_source,'/shadow_source.py')['sha256'], plan['period_sha256'])
    capture_receipt = object_at(collector, '/collector-receipt.json')
    require(chain['chain_head'] == capture_receipt['chain_head']
            and chain['counts'] == capture_receipt['counts'], 'CAPTURE_RECEIPT_BINDING')
    require(chain['counts'].get('QUOTE',0) == 0, 'NEW_QUOTES_REQUIRE_SEPARATE_LABEL_AUDIT')
    raw_receipt = strict((root/'financial_head_binary_receipt.json').read_bytes())
    raw = base64.b64decode(raw_receipt['data_base64'], validate=True)
    require(raw_receipt['offset'] == 0 and raw_receipt['eof'] is True
            and len(raw) == raw_receipt['size'] == raw_receipt['next_offset']
            and sha(raw) == raw_receipt['chunk_sha256'], 'BINARY_READBACK_BINDING')
    tensors = parse_head(raw, plan['head_tensor_sha256'])
    bias = tensors['value.bias'][0]; weights = tensors['value.weight']
    norm = math.sqrt(math.fsum(x*x for x in weights)); scale = profile['target_scale_usd']
    ideal = [scale*(bias-norm), scale*(bias+norm)]
    eps = 1e-6
    conditional = [scale*(bias-norm*(1+eps)), scale*(bias+norm*(1+eps))]
    require(candidate['unique_closed_rewards'] == 1, 'SINGLE_ROW_EXPLANATION_SCOPE')
    require(len(candidate['target_net_usd']) == 1
            and candidate['diagnostic']['before_scaled'] == [0.0]
            and len(candidate['diagnostic']['steps']) == candidate['replayed_optimizer_steps'] == 16,
            'SINGLE_ROW_RECORDED_TRAINING_SCOPE')
    y = float(candidate['target_net_usd'][0])/scale
    alpha = profile['sgd_learning_rate']; steps = candidate['replayed_optimizer_steps']
    closed_form = y*(1-(1-2*alpha)**steps)
    current_ms = source['at_ms']
    revoked = bool(set(assessment.get('invalidated_training_reward_ids',[]))
                   & set(candidate['reward_ids']))
    require(assessment['observed_trades'] == financial['observed_trades'], 'STATUS_ASSESSMENT_COUNTS')
    require(assessment['observed_trades'] == 0 and assessment['state'] == 'REVOKED' and revoked,
            'DIFFERENT_FINANCIAL_EVIDENCE_REQUIRES_SEPARATE_AUDIT')
    decision = 'KEEP_ORIGINAL_AND_STOP_FINANCIAL_EDITING'
    return dict(schema='hepta.financial-source-weight-audit.v1',
        observed_at_new_york=ny(current_ms), report_scope='Read-only isolated audit of the enumerated captures',
        source_bindings={'source_pins':source_pins,'candidate_manifest_sha256':candidate_item['sha256'],
                         'plan_sha256':plan_item['sha256'],'head_sha256':sha(raw),
                         'required_plan_runtime_files':sorted(plan['runtime_sha256']),
                         'verified_plan_runtime_files':sorted(verified_runtime_files),
                         'missing_plan_runtime_files':sorted(set(plan['runtime_sha256'])-set(verified_runtime_files)),
                         'complete_plan_runtime_source_binding':set(plan['runtime_sha256']) == set(verified_runtime_files),
                         'training_source_binding_complete':True,
                         'registration_signature_verified':False,
                         'canonical_owner_attestation_verified':False,
                         'atomic_host_snapshot':False},
        operational_source=dict(state=source['state'], usable=source['usable'], unusable=source['unusable'],
            latest_quote_new_york=ny(source['latest_source_quote_ms']),
            latest_quote_age_seconds=(current_ms-source['latest_source_quote_ms'])/1000,
            reasons=source['reasons'], verified_selected_capture=chain,
            resident_status_training_counts=control['job_counts'],
            resident_status_as_of_new_york=ny(control['at_ms']),
            training_count_scope='Enumerated resident status, not a host process census'),
        financial_evaluator=dict(state=assessment['state'], status_as_of_new_york=ny(financial['at_ms']),
            status_age_days=(current_ms-financial['at_ms'])/86400000,
            old_status_is_not_current_service_liveness=True,
            registered_input_start_new_york=ny(plan['input_start_ms']),
            registered_input_end_new_york=ny(plan['input_end_ms']),
            registered_outcome_end_new_york=ny(plan['outcome_end_ms']),
            frozen_rule=rule, behavior_scope=plan['behavior_scope'],
            observed_trades=assessment['observed_trades'], original_trades=assessment['total_original_trades'],
            unresolved_or_censored=assessment['unresolved_or_censored'], training_rows=1,
            training_reward_revoked=revoked, reasons=assessment['reasons'],
            raw_execution_ledger_replayed=False, admissible_independent_examples_in_read_plan=0,
            global_independent_financial_label_count=None,
            endpoint_observed_counter=endpoint['observed'],
            endpoint_counter_is_not_financial_net_pnl_sample_size=True),
        actual_weight_geometry=dict(parameters=769, dtype='F32', head='linear 768 to 1 with bias',
            bias=bias, weight_l2=norm, total_l2=math.hypot(norm,bias),
            output_usd='100 * (w dot normalized_feature + b), same shared head for BUY and SELL prompts',
            conditional_unit_ball_range_usd=ideal,
            conditional_norm_le_1_plus_epsilon_range_usd=conditional,
            assumed_normalization_epsilon=eps,
            normalization_error_bound_is_assumption_not_full_encoder_verification=True,
            range_arithmetic='Real arithmetic linear-form bound using parsed F32 parameter values',
            runtime_dot_and_output_rounding_bound=None,
            range_is_not_a_certified_runtime_f32_output_interval=True,
            scope='Analytic Cauchy bound on parsed weights; no encoder execution or semantic feature recovery',
            single_row_squared_huber_recurrence=dict(target_scaled=y, learning_rate=alpha, steps=steps,
                ideal_normalized_feature_prediction=closed_form,
                stored_training_prediction=candidate['diagnostic']['after_scaled'][0],
                absolute_prediction_difference=abs(closed_form-candidate['diagnostic']['after_scaled'][0]),
                recorded_max_gradient_norm=max(s['gradient_norm'] for s in candidate['diagnostic']['steps']),
                recorded_max_huber_scaled=max(s['huber_scaled'] for s in candidate['diagnostic']['steps']),
                ideal_conditions='zero initialization; feature norm one; quadratic Huber region; no clipping activated',
                geometry_is_expected_from_single_negative_example_not_weight_corruption=True,
                reconstruction_is_not_gradient_training_or_independent_quality=True)),
        conclusion=dict(decision=decision, model_forward_calls=0, gradient_steps=0,
            weight_edits=0, usable_independent_quality_evidence=False,
            analytic_linear_form_maximum_below_one_us_cent=conditional[1] < .01,
            source_and_label_repair_precedes_any_efficacy_claim=True,
            no_claim_of_optimal_financial_policy=True, production_eligible=False))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--root',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True); args = ap.parse_args()
    result = audit(args.root.resolve())
    with args.output.open('x') as stream:
        json.dump(result,stream,indent=2,ensure_ascii=False,allow_nan=False);stream.write('\n')
    print(json.dumps({'status':'PASS','head':result['actual_weight_geometry'],
                      'decision':result['conclusion']['decision']},ensure_ascii=False))


if __name__ == '__main__': main()
