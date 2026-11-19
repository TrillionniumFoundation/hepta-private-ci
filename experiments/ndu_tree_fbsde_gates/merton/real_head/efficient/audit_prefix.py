"""Reopen original source archives; replay SGD and choices independently.

Uses the inherited independent scalar SGD, not the producer's prefix trainer.
Timers are consistency-checked self-observations, not hardware attestations.
"""
from __future__ import annotations

import argparse
import statistics
import time
from fractions import Fraction as Q
from functools import lru_cache
from pathlib import Path

from prefix import ARMS, REPEATS, HORIZON, STEPS, PARENT, source_hashes, spec
from material import LOCKS, canonical, load_sources, sha, strict_loads, write_new
from audit_real import close, ref_fit, ref_predict, qscore


@lru_cache(None)
def reference_fit(raw, n):
    return ref_fit(strict_loads(raw), n)


def integer(x, positive=False):
    if type(x) is not int or x < int(positive):
        raise ValueError('invalid physical counter')
    return x


def same_head(a,b):
    if set(a) != {'weights','scales'}:
        raise ValueError('head schema')
    close(a['weights'],b['weights']);close(a['scales'],b['scales'])


def inspect(row, fold, labels):
    if row['arm'] not in ARMS or row['source_fold_sha256'] != sha(canonical(fold)):
        raise ValueError('source or arm binding')
    if row['held_labels_loaded'] is not False or row['fresh_encoder_calls'] != 0 or row['fresh_reader_calls'] != 0:
        raise ValueError('forged inference or gold access')
    for k in ('lifecycle_cpu_ns','lifecycle_wall_ns','actual_optimizer_steps','actual_train_row_updates'):
        integer(row[k])
    for value in row['stages'].values():integer(value)
    if sum(row['stages'].values()) > row['lifecycle_cpu_ns']:
        raise ValueError('overlapping or double-charged phase')
    train,held = fold['train'],fold['held_inputs']
    search = row['arm'] in ARMS[4:]
    groups = sorted({r['group'] for r in train})
    banks = row['banks']
    if (len(banks) != (3 if search else 0)) or (len(row['calibration']) != (12 if search else 0)):
        raise ValueError('missing physical pilot or calibration')
    expected_steps,expected_work=0,0
    seen=set(); heads={};bank_by_group={}
    checked_checkpoints=0
    for bank in banks:
        g=bank['validation_group']
        if g not in groups or g in seen:raise ValueError('pilot split census')
        seen.add(g);bank_by_group[g]=bank
        source=[r for r in train if r['group']!=g]
        if bank['train_ids'] != [r['id'] for r in source]:raise ValueError('pilot training leakage')
        if bank['label_sha256'] != sha(canonical([[r['id'],r['label']] for r in source])):
            raise ValueError('pilot labels changed')
        if set(bank['heads']) != set(map(str,STEPS)) or set(bank['cumulative_cpu_ns']) != set(map(str,STEPS)):
            raise ValueError('checkpoint census')
        is_prefix=row['arm']!='corrected_independent'
        nsteps=128 if is_prefix else 168
        expected_schema='hepta.merton.prefix.bank.v1' if is_prefix else 'hepta.merton.independent.bank.v1'
        if bank['schema']!=expected_schema or bank['optimizer_steps']!=nsteps or bank['train_row_updates']!=nsteps*len(source):
            raise ValueError('fictitious checkpoint work saving')
        integer(bank['cpu_ns'],True);integer(bank['wall_ns'],True)
        times=[integer(bank['cumulative_cpu_ns'][str(n)],n>0) for n in STEPS]
        if times[0]!=0 or max(times)>bank['cpu_ns']:raise ValueError('invalid elapsed quote')
        if is_prefix and times!=sorted(times):raise ValueError('prefix clock ran backwards')
        if not is_prefix and len(bank['receipts'])!=4:raise ValueError('independent fit census')
        for index,n in enumerate(STEPS):
            head,trace=reference_fit(canonical(source),n)
            same_head(bank['heads'][str(n)],head)
            if is_prefix:
                close(bank['loss_trace'][:n],trace)
                if len(bank['loss_trace'])!=128:raise ValueError('truncated actual updates')
            else:
                receipt=bank['receipts'][index]
                if receipt['steps']!=n or receipt['cpu_ns']!=(times[index] if n else receipt['cpu_ns']):
                    raise ValueError('fit/quote drift')
                integer(receipt['cpu_ns'],True);integer(receipt['wall_ns'],True)
                if receipt['train_ids']!=([r['id'] for r in source] if n else []):raise ValueError('independent train census')
                close(receipt['loss_trace'],trace)
            heads[g,n]=head;checked_checkpoints+=1
        expected_steps+=nsteps;expected_work+=nsteps*len(source)
    cr={}
    for r in row['calibration']:
        key=r['group'],r['steps']
        if key not in heads or key in cr:raise ValueError('calibration census')
        source=[x for x in train if x['group']==r['group']]
        pp=ref_predict(heads[key],source)
        if r['ids']!=[x['id'] for x in source]:raise ValueError('calibration input changed')
        close(r['p'],pp)
        qq=qscore(source,pp,labels)
        if r['questions']!=[int(qq[q]) for q in sorted(qq)]:raise ValueError('calibration success forged')
        integer(r['prediction_cpu_ns'],True);integer(r['score_cpu_ns'],True)
        cr[key]=r
    alpha=Q(0);quotes={};values={}
    if search:
        common=sum((Q(r['prediction_cpu_ns'],len(r['questions'])) for r in cr.values()),Q(0))/12
        for n in STEPS:
            qs=[Q(sum(cr[g,n]['questions']),len(cr[g,n]['questions'])) for g in groups]
            refit=sum((Q(bank_by_group[g]['cumulative_cpu_ns'][str(n)]*len(train),len(bank_by_group[g]['train_ids'])) for g in groups),Q(0))/3
            quotes[str(n)]={'passage_success':list(map(str,qs)), 'refit_ns':str(refit),'inference_ns_per_question':str(common)}
        if row['arm']!='prefix_neutral':
            alpha=Q(1,4)
            for g in groups:
                for good in cr[g,0]['questions']:
                    alpha=max(Q(0),min(Q(1,2),alpha+(Q(-1,8) if good else Q(1,4))))
        for n in STEPS:
            qs=[Q(x) for x in quotes[str(n)]['passage_success']]
            value=HORIZON*((1-alpha)*sum(qs,Q(0))/3+alpha*min(qs))
            # Equivalent registered 0.001 utility / CPU millisecond.
            value-=(Q(quotes[str(n)]['refit_ns'])+HORIZON*common)/1_000_000_000
            values[str(n)]=str(value)
        selected=sorted(STEPS,key=lambda n:(-Q(values[str(n)]),n))[0]
        if sum(b['cpu_ns'] for b in banks)+sum(r['prediction_cpu_ns']+r['score_cpu_ns'] for r in cr.values()) > row['stages']['pilot_cpu_ns']:
            raise ValueError('pilot work not fully charged')
    else:
        selected=0 if row['arm']=='no_update' else int(row['arm'][6:])
    if row['alpha']!=str(alpha) or row['quotes']!=quotes or row['values']!=values or row['selected_steps']!=selected:
        raise ValueError('same-profile selection drift')
    head,trace=reference_fit(canonical(train),selected)
    same_head(row['head'],head);receipt=row['final_fit']
    if receipt['steps']!=selected or receipt['train_ids']!=([x['id'] for x in train] if selected else []):
        raise ValueError('final fit leakage')
    expected_label=None if not selected else sha(canonical([[x['id'],x['label']] for x in train]))
    if receipt['train_label_digest']!=expected_label:raise ValueError('final label lineage')
    close(receipt['loss_trace'],trace)
    if row['stages']['final_fit_cpu_ns']!=integer(receipt['cpu_ns'],True):raise ValueError('unpaid final fit')
    expected_steps+=selected;expected_work+=len(train)*selected
    if row['actual_optimizer_steps']!=expected_steps or row['actual_train_row_updates']!=expected_work:
        raise ValueError('optimizer accounting')
    pp=ref_predict(head,held)
    if [r['id'] for r in row['held_predictions']] != [r['id'] for r in held]:raise ValueError('heldout denominator')
    close([r['p'] for r in row['held_predictions']],pp)
    return {'questions':qscore(held,pp,labels),
            'candidate_correct':sum(int(p>0.5)==labels[r['id']] for r,p in zip(held,pp)),
            'brier_sum':sum(2*(p-labels[r['id']])**2 for r,p in zip(held,pp)),
            'checkpoints':checked_checkpoints,
            'alpha':str(alpha),
            'all_candidate_minima_zero':all(min(map(Q,c['passage_success']))==0 for c in quotes.values()) if search else None}


def audit(paths, material, run, output):
    c,w=time.process_time_ns(),time.perf_counter_ns()
    source,labels,provenance=load_sources(paths)
    groups=sorted({r['group'] for r in source});folds={}
    for i,g in enumerate(groups):
        expected={'schema':'hepta.merton.real-head.fold.v1','fold':i,'held_group':g,
                  'train':[dict(r,label=labels[r['id']]) for r in source if r['group']!=g],
                  'held_inputs':[r for r in source if r['group']==g],'provenance':provenance}
        if strict_loads((Path(material)/f'fold-{i}.json').read_bytes())!=expected:
            raise ValueError('original source material differs')
        folds[i]=expected
    sealed=strict_loads((Path(run)/'sealed.json').read_bytes())
    if strict_loads((Path(run)/'spec.json').read_bytes())!=spec() or sealed['spec_sha256']!=sha(canonical(spec())):
        raise ValueError('experiment spec drift')
    if sealed['source_sha256']!=source_hashes() or sealed['authority']!='DENY_ALL':raise ValueError('source identity or authority drift')
    if any(sealed[k]!=0 for k in ('new_sources','new_encoder_calls','new_reader_calls')):raise ValueError('forged new sources/models')
    wanted={(r,i,a) for r in range(REPEATS) for i in range(4) for a in ARMS}
    keys=[(r['repeat'],r['fold'],r['arm']) for r in sealed['rows']]
    if len(keys)!=len(set(keys)) or set(keys)!=wanted:raise ValueError('missing or duplicated lifecycle')
    totals={};all_checkpoints=0;cross_bank={};decisions={};alpha_values=set();risk_mins=[]
    for row in sealed['rows']:
        result=inspect(row,folds[row['fold']],labels)
        all_checkpoints+=result['checkpoints']
        key=row['repeat'],row['arm']
        t=totals.setdefault(key,{'questions':{},'correct':0,'brier_sum':0.0,'cpu_ns':0,'wall_ns':0,'steps':0,'row_updates':0,'selection':{}})
        t['questions'].update(result['questions']);t['correct']+=result['candidate_correct'];t['brier_sum']+=result['brier_sum']
        t['cpu_ns']+=row['lifecycle_cpu_ns'];t['wall_ns']+=row['lifecycle_wall_ns']
        t['steps']+=row['actual_optimizer_steps'];t['row_updates']+=row['actual_train_row_updates']
        t['selection'][str(row['fold'])]=row['selected_steps']
        decisions.setdefault((row['arm'],row['fold']),set()).add(row['selected_steps'])
        if row['arm']=='prefix_ndu':
            alpha_values.add(result['alpha']);risk_mins.append(result['all_candidate_minima_zero'])
        if row['arm'] in ('corrected_independent','prefix_ndu'):
            cross_bank[row['repeat'],row['fold'],row['arm']]=row['banks']
    pairs=0
    for repeat in range(REPEATS):
        for i in range(4):
            aa=cross_bank[repeat,i,'corrected_independent'];bb=cross_bank[repeat,i,'prefix_ndu']
            for a,b in zip(aa,bb):
                if a['validation_group']!=b['validation_group']:raise ValueError('paired split mismatch')
                for n in STEPS:
                    # Stronger than cross-implementation tolerance: SAME producer arithmetic.
                    if a['heads'][str(n)]!=b['heads'][str(n)]:raise ValueError('prefix changes independent SGD result')
                    pairs+=1
    if sealed['optimizer_steps']!=sum(r['actual_optimizer_steps'] for r in sealed['rows']):raise ValueError('run cost census')
    summaries=[]
    for arm in ARMS:
        values=[totals[r,arm] for r in range(REPEATS)]
        if any(len(v['questions'])!=8 for v in values):raise ValueError('whole-question census')
        summaries.append({'arm':arm,'unique_questions':8,'unique_candidates':33,'unique_passages':4,
                          'whole_question_success_by_repeat':[sum(v['questions'].values()) for v in values],
                          'candidate_correct_by_repeat':[v['correct'] for v in values],
                          'two_class_brier_by_repeat':[v['brier_sum']/33 for v in values],
                          'median_cpu_ms':statistics.median(v['cpu_ns'] for v in values)/1e6,
                          'min_cpu_ms':min(v['cpu_ns'] for v in values)/1e6,
                          'max_cpu_ms':max(v['cpu_ns'] for v in values)/1e6,
                          'median_wall_ms':statistics.median(v['wall_ns'] for v in values)/1e6,
                          'steps_by_repeat':[v['steps'] for v in values],
                          'train_row_updates_by_repeat':[v['row_updates'] for v in values],
                          'choices_by_repeat':[v['selection'] for v in values]})
    out={'schema':'hepta.merton.prefix.audit.v1','authority':'DENY_ALL',
         'source_sha256':source_hashes(),'sealed_sha256':sha((Path(run)/'sealed.json').read_bytes()),
         'verified_lifecycles':len(keys),'verified_checkpoints':all_checkpoints,
         'exact_paired_independent_prefix_checkpoints':pairs,'actual_optimizer_steps':sealed['optimizer_steps'],
         'common_profile_choice_replays':REPEATS*4*3,
         'selection_variability':{a:{str(i):sorted(decisions[a,i]) for i in range(4)} for a in ARMS},
         'ndu_calibration_alpha_values':sorted(alpha_values),
         'all_ndu_candidate_supported_minima_zero':all(risk_mins),
         'endogenous_preference_variation_identified':len(alpha_values)>1,
         'summaries':summaries,'new_sources':0,'new_encoder_calls':0,'new_reader_calls':0,
         'clock_repeats_are_independent_sources':False,'hardware_attestation':False,
         'prospective_efficacy':False,'ndu_specific_superiority_established':False,
         'audit_cpu_ns':time.process_time_ns()-c,'audit_wall_ns':time.perf_counter_ns()-w}
    write_new(output,out)
    print({'lifecycles':len(keys),'exact_checkpoint_pairs':pairs,'optimizer_steps':sealed['optimizer_steps']})
    return out


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for role in LOCKS:parser.add_argument('--'+role.replace('_','-'),required=True,type=Path)
    for arg in ('material','run','output'):parser.add_argument('--'+arg,required=True,type=Path)
    args=parser.parse_args()
    audit({r:getattr(args,r) for r in LOCKS},args.material,args.run,args.output)
