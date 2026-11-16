"""New v2 verification of immutable original42/C1 metadata; old published views are never rewritten."""
from resource_arithmetic import (ARMS, LRS, SEEDS, check_points, close, first_best,
    first_crossing, nonnegative, roster, verify_development)
from resource_arithmetic import require
from historical_review import bind_historical_adequacy


def phase_points(fit, observations, parent, support=None, events=31952):
    require(fit['source_unchanged'] is True and fit['common_weights_unchanged'] is True, 'historical source/shared gate failed')
    require(fit['outer']['result_sha256'] == fit['report_sha256'], 'historical report/outer SHA differs')
    phase, result = fit['phase'], []
    outer = nonnegative(fit['outer']['whole_process_wall_seconds'], 'historical process wall')
    parent_wall = nonnegative(parent['outer']['whole_process_wall_seconds'], 'parent complete process wall')
    if phase == 'C1':
        require(fit['parent_report_sha256'] == parent['report_sha256'] and fit['plan']['parent_plan'] == parent['plan'],
                'historical C1 parent identity differs')
        close(fit['outer']['parent_outer_wall_seconds'], parent_wall, 'historical C1 parent wall')
    require(phase in ('original','C1'), 'unknown historical phase')
    previous_cpu = -1.
    for observed in observations:
        require(all(observed[k] == fit[k] for k in ('phase','name','arm','seed','report_sha256','report_bytes')),
                'observation/fit identity differs')
        support, _ = verify_development(observed['development'], support, events)
        if phase == 'original':
            wall = nonnegative(observed['process_wall_seconds'], 'original observation wall')
            require(wall <= outer, 'original observation beyond complete process exit')
            cpu = observed.get('process_cpu_seconds')
            upper = cpu
        else:
            wall = nonnegative(observed['cumulative_process_wall_seconds'], 'C1 cumulative observation wall')
            late = wall-parent_wall
            early = nonnegative(observed['phase_process_wall_seconds'], 'C1 early sample')
            require(early <= late <= outer, 'historical C1 two-sample interval outside original outer')
            cpu, upper = observed['cumulative_cpu_lower_bound_seconds'], observed['cumulative_cpu_upper_bound_seconds']
            require(upper is None and observed['cumulative_full_process_cpu_seconds'] is None, 'historical exact CPU invented')
            close(cpu, fit['parent_cpu_lower_bound_seconds']+observed['phase_full_process_cpu_seconds'], 'historical CPU lower bound')
        if cpu is not None:
            nonnegative(cpu, 'historical observed CPU')
            require(cpu >= previous_cpu, 'historical CPU samples decrease')
            previous_cpu = cpu
        result.append({'phase':phase, 'epoch':observed['epoch'], 'kind':observed['kind'], 'wall_seconds':wall,
                       'CPU_lower_seconds':cpu, 'CPU_upper_seconds':upper,
                       'quality':observed['development']['macro_f1_11_classes']})
    check_points(result)
    require(sum(p['kind']=='development_before' for p in result) == (1 if phase=='original' else 0), 'historical before-evaluation roster differs')
    return result, support


def parent_cost(fit, points):
    full = nonnegative(fit['outer']['whole_process_wall_seconds'], 'original full process wall')
    recorded = fit.get('all_report_clock_fields', {}).get('cpu_seconds')
    candidates = [p['CPU_lower_seconds'] for p in points if p.get('CPU_lower_seconds') is not None]
    if recorded is not None:
        candidates.append(nonnegative(recorded, 'original fit-entry CPU delta'))
    peak = fit.get('peak_rss_bytes')
    if peak is not None:
        nonnegative(peak, 'original peak RSS')
    return {'full_chain_charged_wall_seconds':full, 'known_chain_wall_lower_bound_seconds':full,
        'cumulative_full_CPU_seconds':None, 'cumulative_CPU_lower_bound_seconds':max(candidates, default=None),
        'original_reported_fit_entry_CPU_seconds':recorded, 'original_fit_entry_CPU_is_complete_process_CPU':False,
        'CPU_missing_components':['original pre-fit startup/import CPU not fully bound by the fit-entry delta',
                                  'original post-report exit CPU'], 'max_attempt_RSS_bytes':peak}


def historical_candidate(parent, child, points):
    best = first_best(points)
    require(best is not None, 'historical candidate lacks a complete epoch')
    selected = child or parent
    require(best['epoch'] == selected['best_epoch'], 'historical best is not first strict maximum')
    if selected.get('selected_development') is not None:
        close(best['quality'], selected['selected_development']['macro_f1_11_classes'], 'historical selected D')
    cost = parent_cost(parent, [p for p in points if p['phase']=='original'])
    if child:
        wrapper = child['outer'].get('attempt_wrapper_wall_seconds')
        if wrapper is None:
            cost['full_chain_charged_wall_seconds'] = None
            cost['known_chain_wall_lower_bound_seconds'] += nonnegative(child['outer']['whole_process_wall_seconds'], 'known C1 child process')
        else:
            require(nonnegative(wrapper, 'C1 complete wrapper') >= child['outer']['whole_process_wall_seconds'], 'C1 wrapper below process wall')
            cost['full_chain_charged_wall_seconds'] += wrapper
            cost['known_chain_wall_lower_bound_seconds'] = cost['full_chain_charged_wall_seconds']
        cpu = child['outer'].get('phase_full_process_cpu_seconds')
        if cpu is not None and cost['cumulative_CPU_lower_bound_seconds'] is not None:
            cost['cumulative_CPU_lower_bound_seconds'] += nonnegative(cpu, 'C1 CPU sample')
        cost['CPU_missing_components'] += ['C1 post-report child exit CPU', 'C1 per-fit wrapper CPU']
        peaks = [x for x in (cost['max_attempt_RSS_bytes'],child.get('peak_rss_bytes')) if x is not None]
        cost['max_attempt_RSS_bytes'] = max(peaks,default=None)
    adequate = selected['training_adequacy_established'] is True
    return {'name':parent['name'],'arm':parent['arm'],'seed':parent['seed'],
        'learning_rate':parent['plan']['learning_rate'],'quality':best['quality'],'quality_verified':True,
        'producer_adequate':adequate,'independent_adequate':False,'status':'verified_historical_metadata',
        'stop_reason':selected.get('stop_reason'),'diagnostic_passed':parent['diagnostic_passed'],
        'selected_epoch':best['epoch'],'best_complete_epoch':best,'points':points,'history_metadata_checked':True,
        'first_observed_target_crossing':first_crossing(points),
        'before_training_target_eligible':any(p['kind']=='development_before' and p['quality']>=.3 for p in points),
        'errors':[],'cost_independently_audited':True,**cost}


def check_old(curves, old, compact, reviews, review_identities):
    require(curves['schema']=='hcsn-original42-and-c1-epoch-curves-v1' and curves['confirmation_access'] is False,
            'historical curves scope differs')
    require(old['schema']=='hcsn-descriptive-resource-analysis-v1' and old['validation']['passed'] is True
            and old['validation']['all_input_bytes_unchanged'] is True and old['confirmation_access'] is False
            and old['model_execution'] is False, 'frozen original analysis not admitted')
    fits = {(f['phase'],f['name']):f for f in curves['fits']}
    require(len(fits)==len(curves['fits'])==49, 'historical 49-report roster differs')
    originals = {name:f for (phase,name),f in fits.items() if phase=='original'}
    require(set(originals)==set(roster()) and sum(k[0]=='C1' for k in fits)==7, 'historical original42/C1 count differs')
    require(all(f['arm']!='hcsn' for (phase,_),f in fits.items() if phase=='C1'), 'historical HCSN C1 invented')
    observations = {key:[] for key in fits}
    require(len(curves['observations'])==2969, 'historical observation roster differs')
    for row in curves['observations']:
        observations[(row['phase'],row['name'])].append(row)
    require(compact['schema']=='hcsn-recorded-resource-points-v1'
            and compact['curves_sha256']==old['input_identities']['curves']['sha256'], 'compact curve identity differs')
    require(compact['columns']==['epoch','kind','wall_seconds','CPU_lower_seconds','CPU_upper_seconds','quality'], 'compact columns changed')
    points, support = {}, None
    for key, fit in fits.items():
        require(fit['name']==f"{fit['arm']}-s{fit['seed']}-lr{originals[fit['name']]['plan']['learning_rate']:g}", 'historical label differs')
        values, support = phase_points(fit, observations[key], originals[key[1]], support)
        epochs = [p['epoch'] for p in values if p['kind']=='complete_epoch']
        offset = 1 if key[0]=='original' else 1+sum(p['kind']=='complete_epoch' for p in observations[('original',key[1])])
        require(epochs==list(range(offset,offset+len(epochs))), 'historical complete epochs not contiguous')
        require([[p[k] for k in compact['columns']] for p in values]==compact['by_phase_and_name']['/'.join(key)],
                'original compact points changed')
        points[key]=values
    require(set(compact['by_phase_and_name'])=={'/'.join(k) for k in fits}, 'compact phase roster differs')
    view = old['views']['original42_plus_separate_C1']
    saved = {r['name']:r for r in view['chains']}
    require(len(saved)==42 and set(saved)==set(originals), 'old chain roster differs')
    baselines, parents = [], {}
    for name,parent in originals.items():
        child=fits.get(('C1',name))
        combined=points[('original',name)]+(points[('C1',name)] if child else [])
        check_points(combined)
        row=historical_candidate(parent,child,combined)
        require(saved[name]['best_complete_epoch']==row['best_complete_epoch']
                and saved[name]['first_observed_target_crossing']==row['first_observed_target_crossing'], 'historical selected observation changed')
        close(saved[name]['full_chain_outer_wall_seconds'],parent['outer']['whole_process_wall_seconds']+
              (child['outer']['whole_process_wall_seconds'] if child else 0),'old process-scope bill')
        require(saved[name]['final_training_adequacy']==row['producer_adequate'], 'old adequacy changed')
        if parent['arm']=='hcsn':
            require(parent['status']=='budget_exhausted' and not row['producer_adequate'], 'old HCSN censoring changed')
            parents[name]={'fit':parent,'row':row,'points':combined,'support':support}
        else:
            baselines.append(row)
    choices={r['arm']:r['selected_common_learning_rate'] for r in view['tables']['final'] if r['arm']!='hcsn'}
    require(set(choices)==set(ARMS)-{'hcsn'}, 'frozen baseline LR roster differs')
    for arm, lr in choices.items():
        means={v:sum(r['quality'] for r in baselines if r['arm']==arm and r['learning_rate']==v)/3 for v in LRS}
        require(lr==min(LRS,key=lambda v:(-means[v],v)), 'frozen baseline common LR arithmetic differs')
    inherited=bind_historical_adequacy(baselines,fits,reviews,review_identities)
    return baselines,parents,choices,support,{'historical_reports':49,'CM_observations':2969,
        'inherited_independent_adequacy':inherited,
        'compact_points_verified':True,'old_300_900_1800_views_recalculated_or_modified':False,
        'old_hcsn_censoring_retained':True,'CPU_scope':'Original fit-entry deltas and prefix observations remain lower bounds; pre-fit/import and exit accounting is incomplete.'}
