"""New v2 candidate ancestry, fixed quality clocks, and all-opportunity costs."""
from resource_arithmetic import check_points, close, first_best, first_crossing, nonnegative, require, verify_development

TRAINING_CAP, TRAINING_RSS = 43200, 6*1024**3


def charge(parent, outer, report, row):
    """Preserve finite measured amounts even when another admission check fails."""
    base = parent['row']
    parent_wall = nonnegative(base['full_chain_charged_wall_seconds'], 'original full process wall')
    row.update(full_chain_charged_wall_seconds=None, known_chain_wall_lower_bound_seconds=parent_wall,
        cumulative_full_CPU_seconds=None, cumulative_CPU_lower_bound_seconds=base.get('cumulative_CPU_lower_bound_seconds'),
        max_attempt_RSS_bytes=base.get('max_attempt_RSS_bytes'),
        original_full_process_wall_seconds=parent_wall, phase_outer_wall_seconds=None, phase_wrapper_wall_seconds=None,
        phase_wait4_CPU_seconds=None, raw_C2_attempt=outer,
        CPU_missing_components=['original pre-fit startup/import CPU not fully bound',
            'original post-report exit CPU','C2 per-fit wrapper CPU'],
        quality_clock_scope='original full process plus C2 observed phase prefix; no interpolation',
        final_cost_scope='original full process plus complete C2 attempt wrapper; never substituted for quality-prefix time')
    values = {}
    for source, target in [('whole_process_wall_seconds','phase_outer_wall_seconds'),
                           ('attempt_wrapper_wall_seconds','phase_wrapper_wall_seconds'),
                           ('child_cpu_seconds','phase_wait4_CPU_seconds')]:
        value = outer.get(source)
        if value is not None:
            try:
                values[source] = nonnegative(value, source)
                row[target] = value
            except ValueError as exc:
                row['errors'].append('cost: '+str(exc))
    process, wrapper = values.get('whole_process_wall_seconds'), values.get('attempt_wrapper_wall_seconds')
    known = [v for v in (process,wrapper) if v is not None]
    row['known_chain_wall_lower_bound_seconds'] = parent_wall+max(known,default=0.)
    if wrapper is not None and (process is None or wrapper >= process):
        row['full_chain_charged_wall_seconds'] = parent_wall+wrapper
    elif wrapper is not None:
        row['errors'].append('cost: wrapper smaller than measured child process')
    cpu = values.get('child_cpu_seconds')
    if cpu is not None:
        before = row['cumulative_CPU_lower_bound_seconds']
        row['cumulative_CPU_lower_bound_seconds'] = cpu+(before if before is not None else 0.)
    elif outer.get('process_started') is not False:
        row['CPU_missing_components'].append('C2 child wait4 CPU missing')
    for peak in (outer.get('child_peak_rss_bytes'), (report or {}).get('peak_rss_bytes')):
        if peak is not None:
            try:
                nonnegative(peak, 'observed phase RSS')
                row['max_attempt_RSS_bytes'] = max(row['max_attempt_RSS_bytes'] or 0,peak)
            except ValueError as exc:
                row['errors'].append('cost: '+str(exc))
    try:
        require(outer['parent_full_outer_wall_seconds']==parent_wall
                and outer['parent_actual_hard_wall_seconds']==parent['fit']['outer']['hard_wall_seconds']
                and outer['cumulative_active_wall_cap_seconds']==TRAINING_CAP, 'parent wall/cap differs')
        if 'remaining_at_dispatch_seconds' in outer:
            close(outer['remaining_at_dispatch_seconds'],TRAINING_CAP-parent_wall,'remaining without refund',1e-7)
    except (ValueError,KeyError,TypeError) as exc:
        row['errors'].append('cost: '+str(exc))
    return row


def plateau(points):
    best, anchor, stale, best_epoch, first_stop = -1., -1., 0, None, None
    for p in (p for p in points if p['kind']=='complete_epoch'):
        q, n = p['quality'], p['epoch']
        if q > best:
            best, best_epoch = q, n
        if q > anchor+.002:
            anchor, stale = q, 0
        else:
            stale += 1
        if first_stop is None and n>=30 and stale>=10:
            first_stop=n
    return {'best':best,'best_epoch':best_epoch,'plateau_anchor':anchor,'stale_epochs':stale},first_stop


def history(parent, outer, report, support):
    fit, original = parent['fit'], parent['points']
    name, plan = fit['name'], fit['plan']
    require(report['schema']=='hcsn-c2-soft-wall-continuation-v1' and report['production_execution'] is True
            and report['arm']=='hcsn' and report['seed']==plan['seed']
            and report['learning_rate']==plan['learning_rate'] and report['confirmation_access'] is False,
            'C2 report candidate/scope differs')
    require(report['parent_outer']==fit['outer']
            and report['parent_report']=={'bytes':fit['report_bytes'],'sha256':fit['report_sha256']}
            and report['parent_full_outer_wall_charged']==fit['outer']['whole_process_wall_seconds']
            and report['refund_for_discarded_parent_work_seconds']==0, 'C2 parent identity or charged wall differs')
    require(report['fresh_independent_fits_started']==0 and report['continuation_attempts_started']==1
            and report['new_diagnostic_updates']==0 and report['inherited_memorization']==fit['memorization'],
            'new/repeated diagnostic or parent memorandum differs')
    require(report['source_before']==report['source_after']==fit['source_before']
            and report['source_and_parent_inputs_unchanged'] is True
            and report['common_and_physical_weights_unchanged'] is True, 'source/shared/physics changed')
    retained = sum(p['kind']=='complete_epoch' for p in original)
    require(fit['status']=='budget_exhausted' and fit['training_adequacy_established'] is False
            and report['parent_retained_epochs']==retained and report['retained_main_updates_at_resume']==retained*12,
            'censored original anchor differs')
    parent_wall = fit['outer']['whole_process_wall_seconds']
    phase_wall = nonnegative(report['phase_process_wall_seconds'],'reported phase terminal prefix')
    require(phase_wall <= outer['whole_process_wall_seconds']
            and report['cumulative_process_wall_seconds']==parent_wall+phase_wall,
            'terminal prefix/parent offset differs')
    phase_cpu = nonnegative(report['phase_process_cpu_seconds'],'reported phase terminal CPU')
    require(phase_cpu <= outer['child_cpu_seconds']+1e-6, 'reported CPU exceeds waited child')
    points, epochs, previous_cpu = list(original), report['epochs'], -1.
    metrics = {}
    for offset, epoch in enumerate(epochs,retained+1):
        require(epoch['epoch']==offset and epoch['complete'] is True and offset<=200, 'C2 complete epoch gap')
        _, quality = verify_development(epoch['development'],support)
        wall = nonnegative(epoch['phase_process_wall_seconds'],'epoch phase prefix')
        cpu = nonnegative(epoch['phase_process_cpu_seconds'],'epoch phase CPU')
        require(0 <= wall <= phase_wall and previous_cpu<=cpu<=phase_cpu
                and epoch['cumulative_process_wall_seconds']==parent_wall+wall, 'C2 quality clock/CPU differs')
        previous_cpu=cpu
        parent_cpu=parent['row'].get('cumulative_CPU_lower_bound_seconds')
        points.append({'phase':'C2','epoch':offset,'kind':'complete_epoch',
            'wall_seconds':epoch['cumulative_process_wall_seconds'],
            'CPU_lower_seconds':cpu+(parent_cpu if parent_cpu is not None else 0.),
            'CPU_upper_seconds':None,'quality':epoch['development']['macro_f1_11_classes']})
        metrics[offset]=epoch['development']
    check_points(points)
    final=retained+len(epochs)
    require(report['cumulative_epochs_completed']==final and report['cumulative_active_wall_cap_seconds']==TRAINING_CAP
            and report['maximum_cumulative_epochs']==200, 'C2 final epoch/cap differs')
    require(type(report['new_main_updates']) is int and report['new_main_updates']>=12*len(epochs)
            and report['logical_main_updates']==retained*12+report['new_main_updates']
            and report['actual_executed_main_updates_logged_all_phases']==fit['main_updates']+report['new_main_updates']
            and report['new_unretained_logged_updates']==report['logical_main_updates']-final*12,
            'actual/logical/partial updates differ')
    state, first_stop = plateau(points)
    require(report['stopping']==state and report['best_epoch']==state['best_epoch'], 'strict best/plateau differs')
    require(first_stop is None or first_stop==final, 'continued beyond first recorded plateau')
    producer = (report['status']=='completed_development' and report.get('stop_reason')=='development_plateau'
                and fit['memorization']['passed'] is True)
    require(report['training_adequacy_established'] is producer, 'reported adequacy differs')
    if producer:
        require(first_stop==final, 'claimed plateau absent')
    if report['status']=='completed_development':
        require(outer['returncode']==0 and report.get('stop_reason') in ('development_plateau','epoch_cap_not_convergence')
                and report['new_unretained_logged_updates']==0, 'successful C2 has partial/failed terminal')
    else:
        require(outer['returncode']!=0, 'exit0 lacks completed report')
    return points, metrics, producer


def candidate(parent, outer, report, report_spec, auditor, support, error=None):
    fit=parent['fit']
    row={'name':fit['name'],'arm':'hcsn','seed':fit['seed'],'learning_rate':fit['plan']['learning_rate'],
        'quality':None,'raw_saved_quality':None,'quality_verified':False,'producer_adequate':False,
        'independent_adequate':False,'status':'missing_or_unverified_C2','stop_reason':None,
        'diagnostic_passed':fit['diagnostic_passed'],'points':list(parent['points']),
        'history_metadata_checked':False,'first_observed_target_crossing':None,
        'selected_epoch':None,'errors':[],'scientific_admission':'HOLD','whole_training_numerical_admission':'HOLD'}
    charge(parent,outer,report,row)
    if error:
        row['errors'].append('input: '+str(error))
    if report is None:
        row['errors'].append('report: absent; original opportunity remains charged')
        return row
    row.update(raw_report_status=report.get('status'),stop_reason=report.get('stop_reason'),
               producer_adequate=report.get('training_adequacy_established') is True)
    try:
        require(report_spec is not None and outer.get('terminal_evidence_complete') is True
                and outer.get('process_started') is True and outer['result']==report_spec['identity'],
                'report/outer identity or complete terminal missing')
        points, metrics, producer = history(parent,outer,report,support)
        best=first_best(points)
        row.update(points=points,history_metadata_checked=True,raw_saved_quality=best['quality'],
                   selected_epoch=best['epoch'],producer_adequate=producer,
                   before_training_target_eligible=any(p['kind']=='development_before' and p['quality']>=.3 for p in points))
        require(auditor is not None,'independent auditor unavailable')
        chain,replay=auditor.candidate(row['name'])
        source_path=report_spec.get('source_path',report_spec['path'])
        require(chain['report_identity']==report_spec['identity'] and chain['report_path']==source_path
                and chain['inputs'][source_path]==report_spec['identity']
                and replay['inputs'][source_path]==report_spec['identity']
                and chain['fit_plan']==fit['plan'] and chain['source_map']==fit['source_before'],
                'independent chain/report/source identity differs')
        require(chain['C2_status']==report['status'] and chain['reported_adequacy'] is producer
                and chain['last_complete_epoch']==report['cumulative_epochs_completed']
                and chain['best']['epoch']==best['epoch']
                and chain['best']['identity']['sha256']==report['best_checkpoint_sha256'],
                'independent best/terminal differs')
        _, quality=verify_development(chain['best_epoch_metrics'],support)
        close(quality,best['quality'],'independent strict-best D')
        if best['epoch'] in metrics:
            require(chain['best_epoch_metrics']['confusion_matrix']==metrics[best['epoch']]['confusion_matrix'],
                    'independent best CM differs from C2 epoch')
        _, fresh=verify_development(replay['fresh_development'],support)
        require(replay['fresh_development']['confusion_matrix']==chain['best_epoch_metrics']['confusion_matrix'],
                'fresh replay CM differs')
        close(fresh,best['quality'],'independent fresh D')
        full=row['full_chain_charged_wall_seconds']
        compliant=(full is not None and full<=TRAINING_CAP and outer['child_peak_rss_bytes']<=TRAINING_RSS
                   and report['peak_rss_bytes']<=TRAINING_RSS and not outer.get('hard_timeout_sent'))
        require(chain['C2_observed_training_budget_compliant'] is compliant,'independent training budget differs')
        independent=chain['independent_adequacy_supported']
        require(type(independent) is bool and independent is
                (producer and compliant and chain['status']=='PASSED_BOUND_EVIDENCE_ONLY'),
                'independent adequacy has incompatible recording/budget/producer status')
        row.update(quality=best['quality'],quality_verified=True,independent_adequate=independent,
            status='verified_adequate_checkpoint' if independent else 'verified_diagnostic_checkpoint',
            best_complete_epoch=best,first_observed_target_crossing=first_crossing(points),
            independent_chain_status=chain['status'],independent_report_identity=chain['report_identity'],
            fresh_development=replay['fresh_development'],C2_observed_training_budget_compliant=compliant)
    except (ValueError,KeyError,TypeError,IndexError) as exc:
        row['errors'].append('quality: '+str(exc))
    return row

