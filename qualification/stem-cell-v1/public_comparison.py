"""Compare observed public-study quality and costs without choosing a winner.

A shared encoding pass is paid once by the experiment, but a standalone arm must
pay the whole applicable encoding pass, NOT an equal fraction of it. Arithmetic
subtotals are neither wall-clock speedups nor full service/energy costs. This
post-execution report performs no fitting, retries, selection or significance test.
"""
from __future__ import annotations

import itertools
import math

from next_round_matrix import _digest
from work_record import validate_work_record

SCHEMA = 'hepta.public-quality-cost-comparison.v1'


def _sum_known(values):
    values = tuple(values)
    return sum(values) if all(v is not None for v in values) else None


def _ratio(numerator, denominator):
    return numerator / denominator if numerator is not None and denominator is not None and denominator > 0 else None


def _work(record, study, phases):
    prefixes = validate_work_record(record, expected_policy=study['measurement_policy'])
    if record['profile'] != study['measurement_policy']['arithmetic_profile']:
        raise ValueError('cannot aggregate incompatible arithmetic units')
    # A new execution phase must be deliberately added to this accounting model.
    # Do not silently omit its cost simply because old public runs never used it.
    if any(s['phase'] not in phases for s in record['scopes']):
        raise ValueError('public work outside the declared accounting phases')
    complete = {p: record['phase_flops'][p] for p in phases}
    return dict(complete=complete, known_prefix=sum(prefixes[p] for p in phases),
                aborted_reservations=record['aborted_formula_reservations'],
                stopped=record['stopped'])


def cost_accounting(run, study):
    """Validate ledger semantics and expose bank-only and encoding-inclusive costs.

    Required stages that were never observed stay missing. Zero work is used only
    by absence from an explicitly inapplicable phase set, never to fill a null.
    Failed-arm prefixes survive in the campaign subtotal; no success-only average.
    Caller is responsible for verifying the original artifact/source identities.
    """
    from shared_learning_probe import study_topologies
    names = [t[0] for t in study_topologies(study)]
    if [a['topology'] for a in run['arms']] != names:
        raise ValueError('complete ordered arm inventory required')
    shared = _work(run['shared_encoder_work'], study, ('train', 'inference'))
    if shared['stopped'] is not None:
        raise ValueError('stopped shared encoding cannot support a completed trial')
    shared_total = _sum_known(shared['complete'].values())
    pooled_training = ('train', 'migration') if 'family_policy' in study else ('train',)
    applicable = (*pooled_training, 'evaluation', 'inference')
    arms, known_total, aborted_total = [], shared['known_prefix'], shared['aborted_reservations']
    for arm in run['arms']:
        if arm['status'] not in ('completed', 'failed'):
            raise ValueError('unknown arm disposition cannot become a zero-cost failure')
        work = _work(arm['work'], study, applicable)
        if arm['status'] == 'completed' and work['stopped'] is not None:
            raise ValueError('stopped arm cannot be reported completed')
        known_total += work['known_prefix']
        aborted_total += work['aborted_reservations']
        bank_training = _sum_known(work['complete'][p] for p in pooled_training)
        bank_total = _sum_known(work['complete'].values())
        standalone = _sum_known((shared_total, bank_total))
        arms.append(dict(topology=arm['topology'], status=arm['status'],
            known_bank_prefix_formula_work=work['known_prefix'],
            bank_training_formula_work=bank_training,
            initial_control_prediction_formula_work=work['complete']['evaluation'],
            bank_final_inference_formula_work=work['complete']['inference'],
            complete_bank_trial_formula_work=bank_total,
            standalone_training_formula_work=_sum_known((shared['complete']['train'], bank_training)),
            standalone_final_inference_formula_work=_sum_known((shared['complete']['inference'], work['complete']['inference'])),
            standalone_observed_trial_formula_work=standalone,
            encoder_fraction_of_standalone_observed_trial=_ratio(shared_total, standalone)))
    complete_total = _sum_known([shared_total] + [a['complete_bank_trial_formula_work'] for a in arms])
    comparisons = []
    for left, right in itertools.combinations(arms, 2):
        ratios = {}
        for metric in ('bank_training_formula_work', 'standalone_training_formula_work',
                       'bank_final_inference_formula_work', 'standalone_final_inference_formula_work',
                       'standalone_observed_trial_formula_work'):
            fraction = _ratio(right[metric], left[metric])
            # Ratios of failed candidates' partial trajectories are not efficiency
            # comparisons even when every dispatched prefix happens to be counted.
            ratios[metric + '_candidate_reduction'] = (1-fraction if fraction is not None and
                left['status'] == right['status'] == 'completed' else None)
        comparisons.append(dict(baseline=left['topology'], candidate=right['topology'], **ratios))
    return dict(schema='hepta.public-observed-cost-accounting.v1', unit=run['shared_encoder_work']['profile'],
        shared_encoder_formula_work=shared['complete'], shared_encoder_total=shared_total,
        physical_campaign_known_prefix_formula_work=known_total,
        physical_campaign_complete_observed_formula_work=complete_total,
        failed_kernel_reservations_not_completed_work=aborted_total,
        all_registered_arms_completed=all(a['status']=='completed' for a in arms),
        training_pool=list(pooled_training), arms=arms, comparisons=comparisons,
        shared_work_counted_once_in_campaign=True, standalone_charges_full_encoding=True,
        scope='encoding_training_transition_initial_control_and_final_inference_ATen_formulas',
        excluded_costs=['model_load','tokenization_and_Python_work','publication','scoring','energy'],
        hardware_speedup_established=False, full_system_efficiency_established=False)


def _correct(rows, labels):
    if (not isinstance(rows, list) or len(rows) != len(labels)
            or any(not isinstance(r, list) or len(r) != 4 or
                   any(type(v) not in (int,float) or not math.isfinite(v) for v in r) for r in rows)):
        raise ValueError('complete finite four-class prediction matrix required')
    return [int(max(range(4), key=r.__getitem__)==label) for r,label in zip(rows,labels,strict=True)]


def _changes(left, right, labels):
    """Paired counts retain regressions hidden by an almost unchanged average."""
    def group(indices):
        if not indices:
            return dict(rows=0, recovered=0, lost=0, both_correct=0, both_wrong=0, accuracy_delta=None)
        recovered = sum(left[i]==0 and right[i]==1 for i in indices)
        lost = sum(left[i]==1 and right[i]==0 for i in indices)
        return dict(rows=len(indices), recovered=recovered, lost=lost,
                    both_correct=sum(left[i]==right[i]==1 for i in indices),
                    both_wrong=sum(left[i]==right[i]==0 for i in indices),
                    accuracy_delta=(recovered-lost)/len(indices))
    classes = {str(c):group([i for i,t in enumerate(labels) if t==c]) for c in range(4)}
    observed = [v['accuracy_delta'] for v in classes.values() if v['rows']]
    return dict(overall=group(list(range(len(labels)))), per_class=classes,
                worst_observed_class_delta=min(observed),
                observed_class_regressions=[c for c,v in classes.items() if v['rows'] and v['accuracy_delta']<0])


def quality_cost_comparison(run, study, labels):
    """Add exact paired outcomes to a validated observed-cost comparison.

    Similar aggregate accuracy is NOT an equivalence/noninferiority result. Class
    deltas are descriptions, not confidence bounds. Raw labels are not included in
    the returned record; one shared label-vector digest binds all pairings.
    """
    if (not isinstance(labels,list) or not 4<=len(labels)<=128
            or len(labels)!=len(run['heldout_inputs'])
            or any(type(t) is not int or not 0<=t<4 for t in labels)):
        raise ValueError('complete bounded shared labels required')
    identities = run['heldout_inputs']
    if (len({r['sample_id'] for r in identities})!=len(identities)
            or len({r['input_digest'] for r in identities})!=len(identities)):
        raise ValueError('duplicate held-out identities cannot be new paired observations')
    accounting = cost_accounting(run,study)
    names = [a['topology'] for a in run['arms']]
    if [p['topology'] for p in run['predictions']]!=names:
        raise ValueError('predictions do not cover the registered arms in order')
    fitted, within = {}, []
    for arm,output in zip(run['arms'],run['predictions'],strict=True):
        name=arm['topology']
        if arm['status'] == 'failed':
            if output['before'] is not None or output['after'] is not None:
                raise ValueError('failed arm cannot publish scored success predictions')
            within.append(dict(topology=name,status='unavailable_failed_arm',rows=len(labels)))
            continue
        before, after = _correct(output['before'],labels), _correct(output['after'],labels)
        fitted[name]=after
        within.append(dict(topology=name,status='observed',**_changes(before,after,labels)))
    paired=[]
    for left,right in itertools.combinations(names,2):
        entry=dict(baseline=left,candidate=right,rows=len(labels))
        if left not in fitted or right not in fitted:
            entry['status']='unavailable_failed_arm'
        else:
            entry.update(status='observed',**_changes(fitted[left],fitted[right],labels))
        paired.append(entry)
    report=dict(schema=SCHEMA,study_id=study['study_id'],predictions_content_id=_digest(run),
        labels_sha256=_digest(labels),heldout_identity_sha256=_digest(identities),
        cost_accounting=accounting, before_after=within, paired_quality=paired,
        analysis_role='post_execution_descriptive_no_candidate_selection',
        equal_quality_established=False, independent_cases_verified=False,
        statistical_superiority_established=False, production_authorized=False)
    report['comparison_id']=_digest(report)
    return report
