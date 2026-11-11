"""Saved-metadata orchestration; seven cores, no candidate/failed cost dropped."""
from pathlib import Path

from audit_evidence import Auditor, terminal_roster
from candidate_accounting import candidate
from metadata_io import digest_bytes, save, strict_json
from old_metadata import check_old
from resource_arithmetic import ARMS, core_table, cost_sum, require, roster


def fixed_spec(binding, plan, suffix):
    matching = [p for p in plan['fixed_inputs'] if p.endswith(suffix)]
    require(len(matching) == 1, 'fixed input is ambiguous: '+suffix)
    key = matching[0]
    return {'path': binding['fixed_inputs'][key], 'identity': plan['fixed_inputs'][key]}


def withhold(result, reason):
    result.setdefault('integrity_errors', []).append(reason)
    result['execution_status'] = 'failed_integrity_or_missing_terminal'
    result['derived_longer_resource_table_admitted'] = False
    result['independently_adequate_selected_comparison'] = False
    for row in result.get('candidates', []):
        row['raw_quality_verified_before_final_gate'] = row.get('quality_verified')
        row['quality_verified'] = False
        row['independent_adequate'] = False
    for table in result.get('longer_resource_core_table', []):
        table['raw_selected_common_learning_rate_before_final_gate'] = table.get('selected_common_learning_rate')
        table.update(selected_common_learning_rate=None, selected_statistics=None,
                     selection_status='withheld_final_integrity_failure', selected_trained_comparison_supported=False,
                     median_first_observed_target_seconds=None)


def skeleton():
    return {'schema': 'c2-longer-resource-metadata-analysis-v1', 'execution_status': 'not_completed',
            'candidates': [{'name': name, 'quality_verified': False, 'independent_adequate': False,
                            'status': 'unprocessed_metadata', 'full_chain_charged_wall_seconds': None} for name in roster()],
            'longer_resource_core_table': [], 'derived_longer_resource_table_admitted': False,
            'scientific_admission': 'HOLD', 'whole_training_numerical_admission': 'HOLD',
            'confirmation_E_access': False, 'training_steps': 0, 'forward_calls': 0, 'backward_calls': 0,
            'numerical_oracle_calls': 0, 'energy_joules': None, 'GPU_VRAM_bytes': None, 'billed_currency': None,
            'CPU_axis_used_for_quality_selection': False,
            'old_budget_300_900_1800_modified': False,
            'execution_scope': 'Saved metadata only. Original-budget views and new longer-resource view remain separate.',
            'archive_status': 'provisional_until_external_terminal_receipt_and_archive_identity'}


def load_old(binding, plan, inputs, output):
    original = output/'frozen-original-budget'
    original.mkdir()
    raw_result = inputs.raw(fixed_spec(binding, plan, '/output-v1/RESULT.json'))
    raw_points = inputs.raw(fixed_spec(binding, plan, '/output-v1/POINTS.json'))
    for name, raw in [('RESULT.json', raw_result), ('POINTS.json', raw_points)]:
        with (original/name).open('xb') as stream:
            stream.write(raw)
    old, compact = strict_json(raw_result), strict_json(raw_points)
    reference = old['input_identities']['curves']
    expected = {k: reference[k] for k in ('bytes', 'sha256')}
    require(binding['old_curves']['identity'] == expected, 'original/C1 curve identity differs')
    curves = inputs.json(binding['old_curves'])
    reviews, review_ids = {}, {}
    for label in ('baseline_v1', 'baseline_v2'):
        review_ids[label] = {k: old['input_identities'][label][k] for k in ('bytes', 'sha256')}
        spec = binding['historical_reviews'][label]
        require(spec['identity'] == review_ids[label], 'historical independent review identity differs: '+label)
        reviews[label] = inputs.json(spec)
    baselines, originals, choices, support, validation = check_old(curves, old, compact, reviews, review_ids)
    return old, baselines, originals, choices, support, validation, {
        'RESULT.json': digest_bytes(raw_result), 'POINTS.json': digest_bytes(raw_points)}


def retain_raw_costs(result, baselines, originals, controller, support):
    """Keep observed costs before any terminal/source gate can fail."""
    raw = controller.get('attempts', [])
    result['C2_raw_terminal_attempts_before_admission'] = raw
    rows = []
    for name in roster('hcsn'):
        matches = [r for r in raw if r.get('name') == name]
        if len(matches) == 1:
            row = candidate(originals[name], matches[0], None, None, None, support, 'terminal/source admission pending')
        else:
            row = dict(originals[name]['row'], quality=None, quality_verified=False, independent_adequate=False,
                       full_chain_charged_wall_seconds=None,
                       known_chain_wall_lower_bound_seconds=originals[name]['row']['full_chain_charged_wall_seconds'],
                       errors=['missing/duplicate raw terminal attempt; all raw records retained separately'])
        row['cost_independently_audited'] = False
        rows.append(row)
    result['candidates'] = baselines+rows
    result['all_42_opportunity_cost'] = cost_sum(result['candidates'])
    result['partial_cost_scope'] = 'Reported raw costs retained before terminal/source admission. These are not independently admitted when that gate fails.'


def build(binding, plan, inputs, output, result):
    old, baselines, originals, choices, support, validation, copies = load_old(binding, plan, inputs, output)
    result.update(original_budget_exact_copies=copies, old_view_validation=validation,
                  original_controller_and_C1_costs_nested=old['controller_costs_overlap_attempts'],
                  frozen_baseline_common_LRs=choices, plan=plan)
    # Preserve these charged parents even if terminal/auditor admission fails later.
    result['candidates'] = baselines+[dict(originals[name]['row'], quality_verified=False,
        independent_adequate=False, status='C2_metadata_unprocessed', quality=None,
        known_chain_wall_lower_bound_seconds=originals[name]['row']['full_chain_charged_wall_seconds'],
        full_chain_charged_wall_seconds=None) for name in roster('hcsn')]
    controller = inputs.json(binding['controller_result'])
    retain_raw_costs(result, baselines, originals, controller, support)
    commands = inputs.lines(binding['controller_commands'])
    terminal = inputs.json(binding['native_terminal'])
    require(terminal['job_id'] == binding['native_job_id'], 'native terminal job identity differs')
    require(controller['commands'] == binding['controller_commands']['identity'], 'controller/raw command bytes differ')
    outers = terminal_roster(controller, commands, terminal)
    result['C2_raw_terminal_attempts'] = outers
    result['C2_controller_costs_nested'] = controller.get('costs')
    result['C2_controller_identity'] = binding['controller_result']
    result['terminal_native_identity'] = binding['native_terminal']
    source = binding['controller_result']['source_path']
    auditor, auditor_error = None, None
    try:
        auditor = Auditor(binding['independent_auditor'], inputs)
        context = auditor.context
        require(controller['source_inputs_unchanged'] is True, 'C2 controller source/input gate failed')
        require(context['inputs'][source] == binding['controller_result']['identity']
                and context['inputs'][binding['controller_commands']['source_path']] == binding['controller_commands']['identity'],
                'auditor context/controller identity differs')
        require(context['attempts'] == outers and context['parents'] == {n: r['fit']['outer'] for n, r in originals.items()},
                'auditor context/raw original-C2 terminal attempts differ')
        result['independent_auditor_summary_identity'] = auditor.archive.members['SUMMARY.json']
        result['independent_auditor_external_receipt'] = auditor.external
        result['independent_auditor_complete_native_originals'] = auditor.native
        result['independent_auditor_context_identity'] = auditor.archive.members['stages/context/CONTEXT.json']
    except Exception as exc:
        auditor_error = str(exc)
        auditor = None
    result['independent_auditor_admitted'] = auditor is not None
    result['independent_auditor_error'] = auditor_error
    specs = binding['C2_reports']
    require(len(specs) == 6 and {v['name'] for v in specs} == set(roster('hcsn')), 'C2 report binding roster differs')
    specs = {v['name']: v for v in specs}
    rows = []
    for name in roster('hcsn'):
        inputs.budget()
        spec = specs[name]
        report, error = None, None
        try:
            if spec.get('report') is None:
                require(isinstance(spec.get('missing_reason'), str) and bool(spec['missing_reason']), 'missing report lacks explicit reason')
                error = spec['missing_reason']
            else:
                report = inputs.json(spec['report'])
        except Exception as exc:
            error = str(exc)
        rows.append(candidate(originals[name], outers[name], report, spec.get('report'), auditor, support, error))
        rows[-1]['cost_independently_audited'] = auditor is not None and not any(e.startswith('cost:') for e in rows[-1]['errors'])
    result['candidates'] = baselines+rows
    require(len(result['candidates']) == 42 and {r['name'] for r in result['candidates']} == set(roster()), 'full population lost')
    result['longer_resource_core_table'] = [core_table(arm, [r for r in result['candidates'] if r['arm'] == arm], choices.get(arm))
                                          for arm in ARMS]
    table = result['longer_resource_core_table'][-1]
    if auditor is not None and all(r['quality_verified'] for r in rows):
        saved = auditor.summary['common_lr']
        agrees = saved.get('common_lr') == table['selected_common_learning_rate']
        for group in table['learning_rate_candidates']:
            reference = saved.get('all_seed_means', {}).get(str(group['learning_rate']), {})
            observed = group['verified_three_seed_statistics']
            agrees = agrees and abs(reference.get('mean', float('inf'))-observed['mean']) <= 2e-12
        result['common_LR_independent_arithmetic_matches_auditor'] = agrees
        if not agrees:
            table.update(unadmitted_selection=table['selected_common_learning_rate'],
                         selected_common_learning_rate=None, selected_statistics=None,
                         selection_status='withheld_independent_arithmetic_disagreement',
                         selected_trained_comparison_supported=False, median_first_observed_target_seconds=None)
    result['all_42_opportunity_cost'] = cost_sum(result['candidates'])
    result['independently_adequate_selected_comparison'] = all(t['selected_trained_comparison_supported']
                                                             for t in result['longer_resource_core_table'])
    result['derived_longer_resource_table_admitted'] = auditor is not None
    result['execution_status'] = 'completed_metadata_with_explicit_holds' if any(not r['quality_verified'] for r in rows) else 'completed_metadata'
    result['cost_scope_notes'] = [
        'All original diagnostics remain inside original full-process cost. C2 does not receive a refund for discarded partial parent updates.',
        'Final cost uses complete C1/C2 wrapper wall. Historical byte-identical old tables use their original process scope; both are retained.',
        'Original v8 report CPU is a fit-entry delta: pre-fit startup/import and post-report exit CPU are missing. New C2 child wait4 is exact for that child; cumulative per-fit CPU remains a lower bound/unknown.',
        'Controller wall/children CPU, independent audits and transport are separate overlapping accounts. They are never added to fit wall sums.',
        'Host calendar and concurrent independent auditing differ across phases. These are not idle-host throughput measurements.',
        'Peak RSS is an observed per-attempt maximum, not GPU memory or memory measured at a quality crossing.'
    ]
    separate = []
    for item in binding.get('separate_cost_receipts', []):
        require(item.get('addition_to_fit_sum') is False and item.get('overlap_group') and item.get('scope'),
                'separate cost must declare non-additivity and scope')
        separate.append({**item, 'raw_receipt': inputs.json(item['receipt'])})
    result['separate_audit_transport_costs'] = separate
    result['separate_ledger_completeness'] = 'Only explicitly supplied receipts are inventoried; unsupplied historical costs remain in the upstream ledger, not zero.'
    result['unmeasured'] = ['energy', 'billed currency', 'GPU VRAM', 'original pre-fit startup/import CPU',
                          'original exact post-report exit CPU', 'per-fit wrapper CPU',
                          'latent target crossings between complete-epoch evaluations', 'memory at quality crossing']
    save(output/'LONGER-CURVES.json', {'schema': 'c2-longer-recorded-points-v1',
        'target': .3, 'old_points_copied_unchanged': copies['POINTS.json'],
        'candidates': [{k: r.get(k) for k in ('name', 'quality_verified', 'points', 'history_metadata_checked', 'errors')}
                       for r in result['candidates']]})
    return result
