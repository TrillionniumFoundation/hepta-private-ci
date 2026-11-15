"""Inherited baseline adequacy is bound to earlier independent subrecords, never re-executed."""
from resource_arithmetic import close, require, roster


def bind_historical_adequacy(rows, fits, reviews, identities):
    first, second = reviews['baseline_v1'], reviews['baseline_v2']
    require(first['schema']=='fresh42-completed-baseline36-plus-C1-independent-review-v1'
            and second['schema']=='baseline36-C1-independent-clock-supplement-v2' and second['passed'] is True,
            'historical independent review scope/status differs')
    for report in (first,second):
        require(report['confirmation_access'] is False and report['training_performed'] is False
                and report['optimizer_steps_executed']==0
                and report['identity_checks']['source_unchanged'] is True
                and report['identity_checks']['pinned_inputs_unchanged'] is True, 'historical review integrity failed')
    reuse=second['original36_reuse']
    require(reuse['prior_result_sha256']==identities['baseline_v1']['sha256']
            and reuse['original36_passed_subrecords_reused']==36
            and reuse['all_prior_input_and_source_file_hashes_rechecked'] is True,
            'historical original36 reuse identity differs')
    originals={r['name']:r for r in first['original_baseline_records']}
    children={r['name']:r for r in second['C1_records']}
    names=set(roster())-set(roster('hcsn'))
    require(len(first['original_baseline_records'])==len(originals)==36 and set(originals)==names
            and len(second['C1_records'])==len(children)==7
            and set(children)=={name for phase,name in fits if phase=='C1'}, 'historical independent roster differs')
    for row in rows:
        name=row['name']
        before=originals[name]
        require(before['audit_status']=='passed_completed_original_baseline'
                and before['report_sha256']==fits[('original',name)]['report_sha256'], 'original independent report binding failed')
        if name in children:
            checked=children[name]
            require(checked['audit_status']=='passed_completed_C1_chain_artifacts'
                    and checked['parent_report_sha256']==before['report_sha256']
                    and checked['child_report_sha256']==fits[('C1',name)]['report_sha256']
                    and checked['phase_chain']['logical_phase_chain_checks_passed'] is True,
                    'C1 independent report binding failed')
            adequate=checked['phase_chain']['derived_chain_adequacy']
            epoch=checked['phase_chain']['combined_state']['best_epoch']
        else:
            checked=before
            state=checked['independent_adequacy']
            adequate=(checked['memorization_passed'] is True and checked['original_stop_reason']=='development_plateau'
                      and state['independently_recomputed'] is True and state['first_plateau_epoch']==checked['epochs'])
            epoch=checked['best_epoch']
        require(type(adequate) is bool and adequate==row['producer_adequate'], 'historical independent/producer adequacy disagreement')
        require(epoch==row['selected_epoch'], 'historical independent strict best differs')
        close(checked['independent_selected_development']['macro_f1_11_classes'],row['quality'],'historical independently checked quality')
        row.update(independent_adequate=adequate,independent_adequacy_origin='inherited_published_source_bound_independent_review',
            independent_adequacy_reexecuted_now=False,historical_independent_review_identities=identities,
            historical_review_scope='36 prior passed subrecords plus seven later independently checked C1 chains; prior overall failed review is not relabelled.')
    require(sorted(second['memorization_failures_retained'])==sorted(r['name'] for r in rows if not r['diagnostic_passed']),
            'historical failed memorization opportunities lost')
    return {'independent_original_subrecords_bound':36,'independent_C1_subrecords_bound':7,
            'prior_overall_passed':first['passed'],'later_C1_review_passed':second['passed'],
            'training_adequacy_reexecuted_now':False,'review_identities':identities}

