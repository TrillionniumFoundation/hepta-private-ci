"""Conservative classification of original stage artifacts; no numerical reruns."""

import hashlib
import json
import math
from pathlib import Path


PLAN_SHA = '6ae8bb984d994f0d3fa6963e37d0f4180366a3a7bafd316d887e74f2ef1c7d26'
PROGRAM_MANIFEST_SHA = '154826bbabda6cd44b552e1215f4b5ea5d471ff7b6c2fd7e5abd927ee753f75e'
NAMES = [f'hcsn-s{seed}-lr{rate}' for seed in (101, 211, 307) for rate in ('0.001', '0.003')]


def sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def expected_tasks():
    result = [(name, stage) for stage in (
        'export-best', 'export-last', 'original-prefix', 'domain-best', 'domain-last', 'logrisk'
    ) for name in NAMES]
    result.extend((name, f'finite-best-{index}') for index in range(9) for name in NAMES)
    result.extend((name, 'finite-last-0') for name in NAMES)
    return result


def classify_payload(payload, outer, expected_receipt_sha, closure_passed):
    """Keep raw values visible, but withhold a named-fixture pass if any gate fails."""
    if not isinstance(payload, dict) or not isinstance(outer, dict):
        raise ValueError('stage result or outer receipt is not an object')
    raw = payload.get('result', {})
    if not isinstance(raw, dict):
        raise ValueError('stage numerical result is not an object')
    result = {'raw_numerical_status': raw.get('status'), 'qualified_named_finite_fixture': False}
    source_gate = (
        closure_passed and payload.get('auditor_source_unchanged') is True
        and payload.get('original_inputs_unchanged') is True
        and payload.get('plan_sha256') == PLAN_SHA
        and payload.get('fixed_plan_sha256_after') == PLAN_SHA
        and payload.get('input_receipt_sha256') == expected_receipt_sha
        and payload.get('input_receipt_sha256_after') == expected_receipt_sha
    )
    result['source_and_input_gate_passed'] = source_gate
    outer_gate = (
        outer.get('execution_status') == 'completed' and outer.get('returncode') == 0
        and outer.get('stop_cause') is None and payload.get('execution_status') == 'completed'
        and finite_number(payload.get('peak_rss_bytes'))
        and 0 <= payload['peak_rss_bytes'] <= 2147483648
        and finite_number(outer.get('whole_stage_wall_ceiling_seconds'))
        and 0 < outer['whole_stage_wall_ceiling_seconds'] <= 900
        and finite_number(outer.get('whole_process_wall_seconds'))
        and outer['whole_process_wall_seconds'] >= 0
        and finite_number(outer.get('waited_child_CPU_seconds'))
        and outer['waited_child_CPU_seconds'] >= 0
    )
    result['outer_completion_and_budget_gate_passed'] = outer_gate
    stage = payload.get('stage', '')
    if stage.startswith('finite-'):
        scale = raw.get('scaled_errors', [])
        reference = raw.get('reference', [])
        projected = raw.get('projected', [])
        arithmetic_valid = (
            len(scale) == len(reference) == len(projected) == 4
            and all(finite_number(v) for v in scale + reference + projected)
            and all(abs(abs(a - b) / max(1.0, abs(b)) - e) <= 1e-15
                    for a, b, e in zip(projected, reference, scale))
        )
        numerical_gate = (
            arithmetic_valid and raw.get('scaled_error_limit') == 0.01
            and raw.get('relative_error_gate') is False
            and all(0 <= value <= 0.01 for value in scale)
            and finite_number(raw.get('reference_refinement_delta'))
            and 0 <= raw['reference_refinement_delta'] <= 2e-8
            and finite_number(raw.get('mass_residual')) and abs(raw['mass_residual']) <= 5e-11
            and raw.get('status') == 'passed_fixture'
        )
        result.update(raw_finite_fields={key: raw.get(key) for key in (
            'fixture', 'checkpoint_sha256', 'trace_sha256', 'inputs_sha256',
            'quantities', 'reference', 'projected', 'absolute_errors', 'scaled_errors',
            'relative_errors', 'relative_error_gate', 'scaled_error_limit',
            'reference_refinement_delta', 'reference_omission_bound', 'mass_residual',
            'reference_digits', 'reference_orders', 'minimum_dt', 'maximum_dt', 'horizon')},
            numerical_gate_rechecked_from_original_values=numerical_gate,
            qualified_named_finite_fixture=bool(source_gate and outer_gate and numerical_gate))
    elif stage == 'logrisk':
        result.update(logrisk_primary_passed=raw.get('primary_passed'),
                      direct_FD_all_resolved_pass=raw.get('direct_FD_all_resolved_pass'),
                      direct_FD_inconclusive_count=raw.get('direct_FD_inconclusive_count'),
                      direct_FD_resolved_disagreement_count=raw.get('direct_FD_resolved_disagreement_count'))
    elif stage.startswith('domain-'):
        result['raw_domain_summary'] = {key: raw.get(key) for key in (
            'which', 'state_gradient_checks_passed', 'gradient_scope', 'basis_gate_scope',
            'pressure_sentinels', 'pressure_all_passed', 'pressure_scope_status')}
        result['domain_vector_record_count'] = len(raw.get('records', []))
    elif stage == 'original-prefix':
        result['raw_prefix_result'] = raw
    return result


def inspect_stage(root, name, stage, expected_receipt_sha, closure_passed):
    folder = Path(root) / name
    paths = {'result': folder / (stage + '.json'), 'outer': folder / (stage + '-outer.json'),
             'stdout': folder / (stage + '.stdout'), 'stderr': folder / (stage + '.stderr')}
    existing = {key: {'path': str(path), 'bytes': path.stat().st_size, 'sha256': sha(path)}
                for key, path in paths.items() if path.is_file()}
    row = {'name': name, 'stage': stage, 'artifacts': existing,
           'qualified_named_finite_fixture': False, 'whole_training_domain_admission': 'HOLD'}
    if not existing:
        row['observation_status'] = 'not_observed_to_have_started'
        return row
    if 'outer' not in existing:
        row['observation_status'] = 'attempt_artifacts_without_outer_completion'
        row['cost_scope'] = 'No exact completed-stage outer receipt; CPU/wall not inferred.'
        return row
    try:
        outer = read(paths['outer'])
        if not isinstance(outer, dict):
            raise ValueError('outer receipt is not an object')
        row['outer'] = outer
        if 'result' not in existing:
            row['observation_status'] = 'outer_without_complete_result'
            return row
        if outer.get('result_sha256') != existing['result']['sha256']:
            raise ValueError('result differs from original outer SHA256')
        payload = read(paths['result'])
        if not isinstance(payload, dict):
            raise ValueError('stage result is not an object')
        if payload.get('stage') != stage:
            raise ValueError('result stage identity differs')
        for key in ('stdout', 'stderr'):
            declared = outer.get(key, {})
            if key not in existing or declared.get('sha256') != existing[key]['sha256'] or declared.get('bytes') != existing[key]['bytes']:
                raise ValueError('stream differs from original outer: ' + key)
        row.update(classify_payload(payload, outer, expected_receipt_sha, closure_passed))
        row['observation_status'] = 'completed_artifact_chain' if outer.get('execution_status') == 'completed' else 'failed_or_budget_stage_with_result'
    except (OSError, ValueError, TypeError, KeyError) as error:
        row['observation_status'] = 'invalid_original_artifact_chain'
        row['error'] = repr(error)
        row['qualified_named_finite_fixture'] = False
    return row


def sum_observed_cost(rows):
    totals = {'stage_outer_wall_seconds': 0.0, 'waited_stage_CPU_seconds': 0.0,
              'count_with_outer_cost': 0, 'missing_or_invalid_cost_rows': []}
    for row in rows:
        outer = row.get('outer', {})
        wall = outer.get('whole_process_wall_seconds')
        cpu = outer.get('waited_child_CPU_seconds')
        if all(finite_number(v) and v >= 0 for v in (wall, cpu)):
            totals['stage_outer_wall_seconds'] += wall
            totals['waited_stage_CPU_seconds'] += cpu
            totals['count_with_outer_cost'] += 1
        elif row['observation_status'] != 'not_observed_to_have_started':
            totals['missing_or_invalid_cost_rows'].append({'name': row['name'], 'stage': row['stage']})
    totals['scope'] = ('Existing original per-stage outer timers, nested inside the controller/launcher. '
                       'Do not add these to whole-attempt or bootstrap cost. Missing active-child CPU '
                       'after a process-group kill cannot be inferred from these rows.')
    return totals
