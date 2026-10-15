"""Separate scalar SGD and post-seal publisher-label scoring. Same author, no signer."""
from __future__ import annotations
import argparse
import math
import statistics
import time
from fractions import Fraction as Q
from functools import lru_cache
from pathlib import Path
import numpy as np
from material_news import ROOT, PROTOCOL_SHA, encode, loads, original, packet, sha, spec, write


def reference_row(row, mean, scale):
    # Convert NumPy FP32 scalars before subtraction; retain declared FP64 arithmetic.
    return [(float(v)-m)/s for v,m,s in zip(row,mean,scale)]+[1.]

def scalar_softmax(row, weights):
    logits=[math.fsum(a*b for a,b in zip(row,col)) for col in zip(*weights)]
    top=max(logits);e=[math.exp(v-top) for v in logits];total=math.fsum(e)
    return [v/total for v in e]

@lru_cache(maxsize=2)
def reference(x,y):
    mean=[math.fsum(col)/len(x) for col in zip(*x)]
    scale=[max(1e-6,math.sqrt(math.fsum((v-m)**2 for v in col)/len(x))) for m,col in zip(mean,zip(*x))]
    xx=[[(v-m)/s for v,m,s in zip(row,mean,scale)]+[1.] for row in x]
    weights=[[0.]*4 for _ in range(385)];checkpoints={0:np.array(weights)};losses=[]
    columns=list(zip(*xx))
    for step in range(1,129):
        p=[scalar_softmax(row,weights) for row in xx]
        losses.append(math.fsum(-math.log(row[label]) for row,label in zip(p,y))/64+
                      0.0005*math.fsum(v*v for row in weights[:-1] for v in row))
        errors=[[row[j]-int(label==j) for j in range(4)] for row,label in zip(p,y)]
        error_columns=list(zip(*errors))
        weights=[[v-.1*(math.fsum(a*b for a,b in zip(columns[k],error_columns[j]))/64+
                             (0.001*v if k<384 else 0)) for j,v in enumerate(row)]
                    for k,row in enumerate(weights)]
        if step in (8,32,128):checkpoints[step]=np.array(weights)
    return mean,scale,checkpoints,losses

def equal(a,b):
    aa,bb=np.asarray(a),np.asarray(b)
    if aa.shape!=bb.shape or not np.isfinite(aa).all() or not np.allclose(aa,bb,rtol=1e-9,atol=1e-10):
        raise ValueError('independent numerical replay mismatch')

def audit(archive: Path, material: Path, run: Path, output: Path):
    c0,w0=time.process_time_ns(),time.perf_counter_ns();cfg=spec()
    seal=loads((run/'sealed.json').read_bytes());a,receipt=packet(material/'worker.npz')
    names=('protocol.json','material_news.py','trial_news.py','audit_news.py','test_news.py','README.md')
    expected={n:sha((ROOT/n).read_bytes()) for n in names}
    if set(seal) != {'schema','posture','protocol_sha256','worker_sha256','archive_sha256','source_sha256',
                     'attempts_sha256','mean','scale','common_preparation_cost','runtime','fresh_encoder_calls','heldout_labels_loaded','rows'}:
        raise ValueError('unknown or missing seal field')
    if (seal.get('schema')!='hepta.merton.news-seal.v1' or seal.get('posture')!='RESEARCH_ONLY_DENY_ALL'
        or seal.get('source_sha256')!=expected or seal.get('protocol_sha256')!=PROTOCOL_SHA
        or seal.get('worker_sha256')!=receipt['worker_sha256'] or seal.get('archive_sha256')!=cfg['archive_sha256']
        or seal.get('fresh_encoder_calls')!=0 or seal.get('heldout_labels_loaded') is not False):
        raise ValueError('invalid seal identity or claim')
    # Re-open original source, not producer-created labels or probabilities.
    rows,x,parts=original(archive)
    for source,dest in [('train','train'),('calibration','cal'),('holdout','holdout')]:
        idx=parts[source];equal(a['x_'+dest],x[idx])
        if a[dest+'_ids'].tolist()!=[rows[i]['case_id'] for i in idx]:raise ValueError('original ID mismatch')
        if source!='holdout':equal(a['y_'+dest],[rows[i]['label'] for i in idx])
    labels={rows[i]['case_id']:rows[i]['label'] for i in parts['holdout']}
    label_file=(material/'scorer-labels.json').read_bytes()
    if sha(label_file)!=receipt['held_label_sha256'] or loads(label_file)!=labels:raise ValueError('original label mismatch')
    expected_hashes=[sha(rows[i]['text'].encode()) for i in parts['calibration']]
    if a['cal_hashes'].tolist()!=expected_hashes:raise ValueError('calibration block assignment changed')
    mean,scale,weights,losses=reference(tuple(map(tuple,a['x_train'].astype(float).tolist())),tuple(a['y_train'].tolist()))
    equal(seal['mean'],mean);equal(seal['scale'],scale)
    def predictions(part,w):
        return [scalar_softmax(reference_row(row,mean,scale),w.tolist()) for row in a['x_'+part]]
    majority=max(range(4),key=lambda j:sum(int(v==j) for v in a['y_train']))
    order=sorted(range(32),key=lambda i:expected_hashes[i])
    def blocks(pred):return [sum(int(pred[i]==a['y_cal'][i]) for i in order[j:j+8]) for j in range(0,32,8)]
    cal={s:blocks([max(range(4),key=p.__getitem__) for p in predictions('cal',w)]) for s,w in weights.items()}
    p=Q(1,4);trace=[p]
    for n in blocks([majority]*32):p=max(Q(0),min(Q(1,2),p+Q(4-n,32)));trace.append(p)
    hold={s:predictions('holdout',w) for s,w in weights.items()}
    wanted={(r,arm) for r in range(3) for arm in cfg['arms']}
    records=seal['rows'];keys=[(r['repeat'],r['arm']) for r in records]
    if len(keys)!=len(set(keys)) or set(keys)!=wanted:raise ValueError('missing or duplicate lifecycle')
    journal=(run/'attempts.jsonl').read_bytes()
    if sha(journal)!=seal['attempts_sha256']:raise ValueError('journal changed')
    events=[loads(line) for line in journal.splitlines()]
    if len(events)!=54:raise ValueError('incomplete attempts')
    for j,k in enumerate(keys):
        for off,status in [(0,'start'),(1,'success')]:
            if events[2*j+off]!={'repeat':k[0],'arm':k[1],'status':status}:raise ValueError('attempt order/status mismatch')
    scored=[];checkpoint_checks=0;same_profile=0
    for row in records:
        if set(row) != {'repeat','arm','selected_steps','actual_steps','majority_class','weights','checkpoints','losses',
                        'calibration_blocks','preference_trace','selection_values','holdout_ids','probabilities','phases','cpu_ns','wall_ns'}:
            raise ValueError('unknown or missing lifecycle field')
        if type(row['repeat']) is not int or type(row['selected_steps']) is not int:
            raise ValueError('noninteger lifecycle identity or selection')
        if loads((run/f"{row['repeat']}-{row['arm']}.json").read_bytes()) != row:
            raise ValueError('standalone lifecycle and seal disagree')
        arm=row['arm'];is_search=arm in ('neutral','fixed_risk','ndu_discrete','augmented_same_profile')
        if is_search:
            alpha=Q(0) if arm=='neutral' else Q(1,4) if arm=='fixed_risk' else trace[-1]
            values={s:(1-alpha)*Q(sum(v),32)+alpha*Q(min(v),8) for s,v in cal.items()}
            selected=0
            for s in (8,32,128):
                if values[s]>values[selected]:selected=s
            if row['selection_values']!={str(s):str(v) for s,v in values.items()} or row['calibration_blocks']!={str(s):v for s,v in cal.items()}:
                raise ValueError('selection/calibration drift')
            if row['preference_trace']!=[str(v) for v in trace]:raise ValueError('preference drift')
            stops=(0,8,32,128);actual=128;same_profile+=1
        else:
            selected=int(arm[5:]) if arm.startswith('fixed') else 0;actual=selected;stops=(selected,)
            if row['calibration_blocks'] or row['selection_values'] or row['preference_trace']:raise ValueError('fake free calibration')
        if type(row['actual_steps']) is not int or row['actual_steps']!=actual or row['selected_steps']!=selected:
            raise ValueError('optimizer work or checkpoint mismatch')
        if row['majority_class']!=majority or set(row['checkpoints'])!={str(s) for s in stops}:raise ValueError('wrong fit census')
        for s in stops:equal(row['checkpoints'][str(s)],weights[s]);checkpoint_checks+=1
        equal(row['weights'],weights[selected]);equal(row['losses'],losses[:actual])
        pred=[[float(j==majority) for j in range(4)] for _ in range(32)] if arm=='train_majority' else hold[selected]
        equal(row['probabilities'],pred)
        if row['holdout_ids']!=a['holdout_ids'].tolist():raise ValueError('changed output order')
        for clock in ('cpu_ns','wall_ns'):
            if type(row[clock]) is not int or row[clock]<0:raise ValueError('invalid clock')
            phase_sum=0
            for phase in row['phases'].values():
                if type(phase[clock]) is not int or phase[clock]<0:raise ValueError('invalid phase counter')
                phase_sum+=phase[clock]
            if phase_sum>row[clock]:raise ValueError('phases exceed actual lifecycle')
        if actual and row['phases']['fit']['cpu_ns'] <= 0:raise ValueError('unmetered positive training work')
        expected_phases={'fit','prediction'}|({'calibration_and_selection'} if is_search else set())
        if set(row['phases'])!=expected_phases:raise ValueError('missing or extra charged phase')
        predicted=[max(range(4),key=v.__getitem__) for v in pred]
        correct=[int(v==labels[i]) for v,i in zip(predicted,row['holdout_ids'])]
        brier=math.fsum((v-float(j==labels[i]))**2 for pr,i in zip(pred,row['holdout_ids']) for j,v in enumerate(pr))/32
        scored.append({'repeat':row['repeat'],'arm':arm,'selected_steps':selected,'actual_steps':actual,
                       'correct':sum(correct),'correct_vector':correct,'multiclass_brier':brier,
                       'cpu_ms':row['cpu_ns']/1e6,'wall_ms':row['wall_ns']/1e6,
                       'net_after_declared_cpu_fee':sum(correct)-row['cpu_ns']/1e9})
    summaries=[]
    for arm in cfg['arms']:
        rr=[r for r in scored if r['arm']==arm]
        if any(r['correct_vector']!=rr[0]['correct_vector'] or r['selected_steps']!=rr[0]['selected_steps'] for r in rr):
            raise ValueError('repeat policy or answer drift')
        baseline=next(r for r in scored if r['arm']=='fixed8')
        summaries.append({'arm':arm,'correct':rr[0]['correct'],'denominator':32,'selected_steps':rr[0]['selected_steps'],
            'actual_updates_each_repeat':rr[0]['actual_steps'],'median_cpu_ms':statistics.median(r['cpu_ms'] for r in rr),
            'multiclass_brier':rr[0]['multiclass_brier'],
            'wins_vs_fixed8':sum(a>b for a,b in zip(rr[0]['correct_vector'],baseline['correct_vector'])),
            'losses_vs_fixed8':sum(a<b for a,b in zip(rr[0]['correct_vector'],baseline['correct_vector']))})
    result={'schema':'hepta.merton.news-audit.v1','posture':'RESEARCH_ONLY_DENY_ALL',
        'source_sha256':expected,'archive_sha256':cfg['archive_sha256'],
        'seal_sha256':sha((run/'sealed.json').read_bytes()),'verified_lifecycles':len(records),
        'verified_checkpoint_comparisons':checkpoint_checks,'same_profile_choice_replays':same_profile,
        'actual_updates':sum(r['actual_steps'] for r in records),'calibration_blocks':cal,
        'preference_trace':[str(v) for v in trace],
        'downside_varies_between_candidates':len({min(v) for v in cal.values()})>1,
        'preference_trace_varies':len(set(trace))>1,'preference_endpoint_saturated':trace[-1] in (Q(0),Q(1,2)),
        'prediction_label_custody':'separate_worker_input_and_postseal_process;same_author;not_OS_or_signed_isolation',
        'unique_source_records':128,'unique_holdout_records':32,'validated_story_families':None,
        'new_calendar_windows':0,'fresh_encoder_calls':0,'original_reader_comparability':False,
        'production_accepted':False,'ndu_superiority_established':False,
        'summaries':summaries,'rows':scored,'audit_cpu_ns':time.process_time_ns()-c0,'audit_wall_ns':time.perf_counter_ns()-w0}
    write(output,result);print(encode({'verified_lifecycles':len(records),'summaries':summaries}).decode())
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('archive','material','run','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();audit(a.archive,a.material,a.run,a.output)
