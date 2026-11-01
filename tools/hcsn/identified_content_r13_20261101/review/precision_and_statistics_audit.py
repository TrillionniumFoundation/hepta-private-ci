"""Independent source/receipt audit and formula-level confirmation recomputation.

Does not import evaluation.py, statistics.py, or costs.py. The t quantile is
inverted independently from the regularized incomplete-beta CDF in mpmath.
"""

import datetime
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from mpmath import mp

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/'evidence'
DEST=Path(__file__).with_suffix('.json')
P=json.loads((ROOT/'PROTOCOL.json').read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def preflight():
    frozen=json.loads((EVIDENCE/'FREEZE.json').read_text())
    source_checks={name:sha(ROOT.parent/name)==expected for name,expected in frozen['source_sha256'].items()}
    artifact_checks={name:sha(EVIDENCE/name)==expected for name,expected in frozen['fit_sha256'].items()}
    library=ROOT/'native/evidence/build/libhcsn_prepared.so'
    receipts=[]
    paired=[]
    for seed in P['seeds']:
        fits={}
        for core in P['cores']:
            name=f'{seed}_{core}.json'
            receipt=json.loads((EVIDENCE/'receipts'/name).read_text())
            fit=json.loads((EVIDENCE/'fits'/name).read_text())
            fits[core]=fit
            receipts.append(dict(seed=seed,core=core,receipt_sha256=sha(EVIDENCE/'receipts'/name),
                whole_process_cpu_seconds=receipt['whole_process_cpu_seconds'],
                child_cpu_sum_error=abs(receipt['whole_process_cpu_seconds']-receipt['child_user_cpu_seconds']-receipt['child_system_cpu_seconds']),
                preparation_cpu_seconds=fit['preparation_cpu_seconds'],fit_cpu_seconds=fit['fit_cpu_seconds'],
                overhead_cpu_seconds=receipt['whole_process_cpu_seconds']-fit['preparation_cpu_seconds']-fit['fit_cpu_seconds'],
                fit_budget=fit['budget_cpu_seconds'],fit_overshoot=fit['budget_overshoot_seconds'],
                updates=fit['updates'],selected_update=fit['selected_update'],
                source_matches_freeze=all(frozen['source_sha256'].get(n)==h for n,h in receipt['source_before'].items()),
                source_unchanged=receipt['source_unchanged'],returncode=receipt['returncode'],
                frontend_identity_matches=fit['frontend_sha256']==sha(EVIDENCE/'frontend.json')))
        choice=min(P['cores'][1:],key=lambda core:fits[core]['selected_validation']['posterior_ce'])
        paired.append(dict(seed=seed,training_digest_same=len({f['train_data_sha256'] for f in fits.values()})==1,
            validation_digest_same=len({f['validation_data_sha256'] for f in fits.values()})==1,
            choice=choice,frozen_choice=frozen['ordinary_choices'][str(seed)],
            selected_validation_ce={core:f['selected_validation']['posterior_ce'] for core,f in fits.items()}))
    frontend=json.loads((EVIDENCE/'frontend.json').read_text())
    frontend_receipt=json.loads((EVIDENCE/'frontend_receipt.json').read_text())
    args=frontend_receipt['arguments']
    replica=Path(args[args.index('--output')+1])
    replica_data=json.loads(replica.read_text())
    same_frontend=all(frontend[k]==replica_data[k] for k in ('coefficients','intercept','training_iterations','development_counts','dataset'))
    operative=['evaluation.py','statistics.py','costs.py','contract.py','models.py','content.py',
        'data.py','inference.py','training.py','controller.py','launch.py','fit_frontend.py',
        'propagation/api.py','propagation/bounds.py','propagation/finite_volume.py','native/adapter.py']
    covered={n:f'{ROOT.name}/{n}' in frozen['source_sha256'] for n in operative}
    checks=dict(source_hashes_match=all(source_checks.values()),artifact_hashes_match=all(artifact_checks.values()),
        native_library_hash_matches=sha(library)==frozen['native_library_sha256'],operative_sources_covered=all(covered.values()),
        receipts_count=len(receipts),all_24_receipts_valid=len(receipts)==24 and all(r['returncode']==0 and r['source_unchanged'] and r['source_matches_freeze'] and r['frontend_identity_matches'] and r['child_cpu_sum_error']<1e-12 and r['overhead_cpu_seconds']>=0 for r in receipts),
        all_paired_data_and_choices_match=all(r['training_digest_same'] and r['validation_digest_same'] and r['choice']==r['frozen_choice'] for r in paired),
        frontend_replica_weights_and_counts_match=same_frontend)
    return dict(timestamp=now(),confirmation_present_at_snapshot=(EVIDENCE/'CONFIRMATION.json').exists(),
        source_review_completed_before_first_outcome_read=True,freeze_sha256=sha(EVIDENCE/'FREEZE.json'),
        source_checks=source_checks,artifact_checks=artifact_checks,native_library_sha256=sha(library),
        operative_source_coverage=covered,receipts=receipts,paired_fits=paired,checks=checks,
        frontend_receipt_scope='Full-process deterministic refit; deployed coefficients/counts match; original and replica timing fields need not match',
        source_identity_limits=[
            'Per-fit source_before covers the training computation but omits launch.py; final FREEZE covers launch.py and run_fits.py.',
            'Frontend-refit source_before omits its fit_frontend.py entrypoint; final FREEZE covers fit_frontend.py. Receipt is not retrospective proof of that entrypoint hash at execution.',
            'R12 contract reads its PROTOCOL.json at import, although the R13-used FinancialOutputs and bayes_step do not use those protocol values; this transitive non-operative file is not in FREEZE.',
            'Source hashes do not attest the entire Python/OS/dependency environment; native binary identity is separately verified.'],
        statistics_contract=dict(independent_units='8 paired fit seeds, not episodes',
            gain='Two-sided 256 sign assignments; Holm over the two D-B utility domains; mean utility gain >= .01',
            noninferiority='One-sided Student lower bound at alpha/2=.025 in each of two domains, greater than -.01',
            cost_primary='ratio of mean unique amortized deployment CPU, D/B <= .9, conditional on noninferiority',
            caveats=['Sign-flip exactness assumes conditional sign exchangeability/symmetry, not merely equal means.',
                     'Student coverage is model-based with eight fits, not a distribution-free finite-sample guarantee.',
                     'Gain tests zero improvement plus a point-estimate .01 threshold; it is not a confidence bound proving improvement greater than .01.',
                     'Unique deployment reuse and runtime/kernel efficiency are distinct; search/equal-charge/runtime ledgers must accompany primary cost.']),
        frozen_files_modified=False)


def t_quantile(probability,df):
    mp.dps=70
    probability=mp.mpf(str(probability))
    lo,hi=mp.mpf(0),mp.mpf(16)
    for _ in range(180):
        x=(lo+hi)/2
        cdf=1-mp.betainc(mp.mpf(df)/2,mp.mpf('.5'),0,df/(df+x*x),regularized=True)/2
        if cdf<probability:
            lo=x
        else:
            hi=x
    return float((lo+hi)/2)


def independent_paired(values,critical):
    n=len(values)
    mean=math.fsum(values)/n
    se=math.sqrt(math.fsum((v-mean)**2 for v in values)/(n-1)/n)
    rationals=[Fraction.from_float(float(v)) for v in values]
    total=sum(rationals,Fraction(0))
    # Existing implementation has 1e-14 tolerance in mean units; also report exact represented-value counting.
    tolerance=Fraction.from_float(1e-14)*n
    extreme=exact=0
    for bits in range(1<<n):
        signed=sum((v if bits&(1<<i) else -v for i,v in enumerate(rationals)),Fraction(0))
        extreme += abs(signed)>=abs(total)-tolerance
        exact += abs(signed)>=abs(total)
    lower=mean-critical*se
    return dict(paired_values=values,mean=mean,standard_error=se,ci95_student=[lower,mean+critical*se],
        one_sided_simultaneous_lower=lower,exact_sign_flip_p=extreme/(1<<n),
        represented_rational_sign_flip_p_without_tolerance=exact/(1<<n),n_independent_fits=n)


def independent_confirmation():
    path=EVIDENCE/'CONFIRMATION.json'
    payload=json.loads(path.read_text())
    assert not payload['development'] and payload['freeze_sha256']==sha(EVIDENCE/'FREEZE.json')
    published=json.loads((EVIDENCE/'SUMMARY.json').read_text()) if (EVIDENCE/'SUMMARY.json').exists() else None
    count=P['confirmation_episodes_per_domain']
    amort=P['training_amortization_episodes']
    frontend=json.loads((EVIDENCE/'frontend_receipt.json').read_text())['whole_process_cpu_seconds']
    critical=t_quantile(1-P['familywise_alpha']/len(P['domains']),len(P['seeds'])-1)
    rows=[]
    max_ledger=max_mean=max_component=0.
    causal_all=True
    outcomes_match=True
    for row in payload['results']:
        outcome=json.loads((EVIDENCE/'outcomes'/f"{row['seed']}_{row['domain']}.json").read_text())
        outcomes_match &= outcome==row
        fits={core:json.loads((EVIDENCE/'receipts'/f"{row['seed']}_{core}.json").read_text())['whole_process_cpu_seconds'] for core in P['cores']}
        assert fits==row['fit_costs'] and row['frontend_cost']==frontend
        cal=fits['hx_distribution']
        setup=row['global_setup_cpu_seconds']+row['seed_setup_cpu_seconds']
        expected_arms={}
        for name,arm in row['arms'].items():
            assert len(arm['utility'])==len(arm['accuracy'])==count
            mean=math.fsum(arm['utility'])/count
            accuracy=math.fsum(arm['accuracy'])/count
            max_mean=max(max_mean,abs(mean-arm['mean_utility']),abs(accuracy-arm['mean_accuracy']))
            actions=np.asarray(arm['actions']);tokens=np.asarray(arm['acquired_tokens'])
            causal=(arm['read_calls']==int(np.sum(actions==3)) and arm['advance_calls']==int(np.sum(actions>=2))
                and arm['raw_text_reads']==arm['text_encoder_calls'] and arm['raw_text_reads']+arm['recovery_read_calls']==arm['read_calls']
                and np.array_equal(tokens>=0,actions==3) and np.all(np.sum(actions==3,axis=1)<=P['read_budget'])
                and np.all(np.sum((actions>=0)&(actions<2),axis=1)==1))
            causal_all &= bool(causal)
            own=fits.get(arm['core'],0.)
            unique=cal+(own if arm['core'] in P['cores'][1:] else 0)+frontend+setup
            search=math.fsum(fits.values())+frontend+setup
            runtime=(arm['inference_cpu_seconds']+arm['world_preparation_cpu_seconds'])/count
            expected=dict(full_process_own_fit_cpu_seconds=own,shared_calibration_cpu_seconds=cal,
                frontend_fit_cpu_seconds=frontend,unique_fit_cpu_seconds=unique,all_candidate_search_cpu_seconds=search,
                service_setup_cpu_seconds=setup,runtime_cpu_per_episode=runtime,
                unique_amortized_cpu_per_episode=runtime+unique/amort,
                total_search_amortized_cpu_per_episode=runtime+search/amort,
                equal_calibration_charge_cpu_per_episode=runtime+(own+cal+frontend+setup)/amort)
            max_ledger=max(max_ledger,max(abs(arm[k]-v) for k,v in expected.items()))
            component=math.fsum(arm['cpu_components'].values())-arm['inference_cpu_seconds']
            max_component=max(max_component,component)
            assert arm['text_encoder_cpu_seconds']<=arm['cpu_components']['world_read_and_recovery']+1e-9
            expected_arms[name]=dict(mean_utility=mean,mean_accuracy=accuracy,**expected)
        rows.append(dict(seed=row['seed'],domain=row['domain'],ordinary_choice=row['ordinary_choice'],arms=expected_arms))
    domains={}
    scalar_checks=[]
    def compare(label,a,b,tolerance=1e-11):
        difference=abs(float(a)-float(b))
        scalar_checks.append(dict(name=label,difference=difference,passed=difference<=tolerance))
    contrasts=[('B_minus_A','B','A'),('D_minus_C','D','C'),('C_minus_A','C','A'),('D_minus_B','D','B'),('D_minus_HMM','D','HMM')]
    for domain in P['domains']:
        subset=sorted((r for r in rows if r['domain']==domain),key=lambda r:r['seed'])
        assert [r['seed'] for r in subset]==sorted(P['seeds'])
        result={name:independent_paired([r['arms'][left]['mean_utility']-r['arms'][right]['mean_utility'] for r in subset],critical) for name,left,right in contrasts}
        result['interaction']=independent_paired([r['arms']['D']['mean_utility']-r['arms']['C']['mean_utility']-r['arms']['B']['mean_utility']+r['arms']['A']['mean_utility'] for r in subset],critical)
        ratios={}
        metrics={'runtime_cost_ratio_D_over_B':'runtime_cpu_per_episode','unique_actual_cost_ratio_D_over_B':'unique_amortized_cpu_per_episode',
            'total_model_search_cost_ratio_D_over_B':'total_search_amortized_cpu_per_episode','conservative_cost_ratio_D_over_B':'equal_calibration_charge_cpu_per_episode'}
        for name,metric in metrics.items():
            ratios[name]=math.fsum(r['arms']['D'][metric] for r in subset)/math.fsum(r['arms']['B'][metric] for r in subset)
        noninf=result['D_minus_B']['one_sided_simultaneous_lower']>-P['quality_noninferiority_margin']
        domains[domain]=dict(contrasts=result,cost_ratios=ratios,noninferiority_pass=noninf,
            cost_acceptance_pass=noninf and ratios['unique_actual_cost_ratio_D_over_B']<=P['cost_ratio_threshold'])
        if published:
            original=published['domains'][domain]
            for name,data in result.items():
                for metric in ('mean','one_sided_simultaneous_lower','exact_sign_flip_p'):
                    compare(domain+'/'+name+'/'+metric,data[metric],original['contrasts'][name][metric])
            for name,value in ratios.items():
                compare(domain+'/'+name,value,original[name])
            compare(domain+'/noninferiority',noninf,original['noninferiority_pass'],0)
            compare(domain+'/cost_acceptance',domains[domain]['cost_acceptance_pass'],original['cost_acceptance_pass'],0)
    previous=0.
    order=sorted(domains,key=lambda d:domains[d]['contrasts']['D_minus_B']['exact_sign_flip_p'])
    for rank,domain in enumerate(order):
        contrast=domains[domain]['contrasts']['D_minus_B']
        previous=max(previous,min(1.,(len(order)-rank)*contrast['exact_sign_flip_p']))
        contrast['holm_p']=previous
        gain=previous<=P['familywise_alpha'] and contrast['mean']>=P['quality_gain_minimum']
        domains[domain]['quality_gain_acceptance_pass']=gain
        if published:
            compare(domain+'/Holm',previous,published['domains'][domain]['contrasts']['D_minus_B']['holm_p'],0)
            compare(domain+'/quality_gain',gain,published['domains'][domain]['quality_gain_acceptance_pass'],0)
    return dict(timestamp=now(),confirmation_sha256=sha(path),summary_sha256=sha(EVIDENCE/'SUMMARY.json') if published else None,
        independent_t975_df7=critical,domains=domains,rows=rows,scalar_comparisons=scalar_checks,
        checks=dict(outcomes_match_aggregate=bool(outcomes_match),causal_count_invariants=bool(causal_all),
            maximum_mean_difference=max_mean,maximum_cost_ledger_difference=max_ledger,
            maximum_timing_components_excess=max_component,summary_all_match=all(r['passed'] for r in scalar_checks)),
        implementation='Independent fsum/sample-variance formulas, Fraction enumeration of 256 signs, incomplete-beta Student quantile, and explicit cost algebra; production analysis functions are never imported.')


def main():
    if DEST.exists():
        report=json.loads(DEST.read_text())
        if 'confirmation' in report:
            raise FileExistsError('Completed independent audit already exists')
    else:
        report=dict(schema='hcsn-r13-independent-precision-statistics-audit-v1',preflight=preflight())
        DEST.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    if (EVIDENCE/'CONFIRMATION.json').exists():
        report['confirmation']=independent_confirmation()
        report['final_frozen_source_checks']=preflight()['checks']
        DEST.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
        print(json.dumps(report['confirmation']['checks'],indent=2))
        print(json.dumps({d:{k:v for k,v in row.items() if k!='contrasts'} for d,row in report['confirmation']['domains'].items()},indent=2))
    else:
        print('Preflight written; awaiting CONFIRMATION.json')


if __name__=='__main__':
    main()
