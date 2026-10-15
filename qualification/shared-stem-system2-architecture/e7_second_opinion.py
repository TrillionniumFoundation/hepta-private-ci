"""Second, self-contained real E7 retrospective recomputation and oracle ceiling.

Does NOT import the proposal, the first scorer, its feature/cache helpers, or
its output function. This is a LABEL-AWARE *reviewer*, never a router. It can
only read the two exact archived ZIPs, never load model weights and never execute
an on-demand Stem. A human-origin signer and future task window remain absent.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from math import isclose, isfinite
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

HIST_SHA='e5d945c655112139fce51b989023abd5111c9e7ab28d9bd4e8a771b86dd95f9d'
REAL_SHA='d8e2af397d7ea862245fae0337588ab491dd70e8a8a9a42879e4a7f2d4be3afa'
PANEL_SHA='8090d3b006364f3da780cea7f1bb91827e8024776e175aa99f5636597bfa644a'
ARMS={
    'granite_only':None,
    'mmbert_only':None,
    'gate_conf_075':.75,
    'gate_conf_090':.90,
    'gate_conf_098':.98,
}


def expect(ok,msg):
    if not ok:
        raise ValueError(msg)


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def json_load(raw):
    def reject_duplicate(pairs):
        output={}
        for key,value in pairs:
            expect(key not in output,'duplicate JSON member')
            output[key]=value
        return output
    return json.loads(raw,object_pairs_hook=reject_duplicate,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('NaN/Inf JSON')))


def archive(path,expected):
    path=Path(path)
    expect(path.is_file() and not path.is_symlink(),'missing independent archive')
    blob=path.read_bytes()
    expect(0<len(blob)<=20_000_000 and sha256(blob).hexdigest()==expected,
           'not the exact registered original ZIP')
    with ZipFile(path) as z:
        inventory=z.infolist()
        expect(0<len(inventory)<=100 and len({i.filename for i in inventory})==len(inventory),
               'duplicate or excessive ZIP members')
        expect(all(not i.is_dir() and not PurePosixPath(i.filename).is_absolute()
                   and '..' not in PurePosixPath(i.filename).parts
                   and i.file_size<=2_000_000 and i.compress_size<=2_000_000
                   and ((i.external_attr>>16)&0o170000)!=0o120000
                   for i in inventory),'unsupported ZIP member')
        expect(sum(i.file_size for i in inventory)<=10_000_000,'ZIP expansion bound')
        return {i.filename:z.read(i.filename) for i in inventory}


def group_labels(old):
    panel=json_load(old['stem-agnews-new-source-panel.json'])
    expect(sha256(canonical(panel)).hexdigest()==PANEL_SHA,'original panel identity')
    expect(panel.get('schema')=='hepta.stem.agnews-fresh-cross-sectional-cohort.v1'
           and panel.get('production_promotion')=='DENY_ALL'
           and panel.get('chronological_future_claim') is False
           and panel.get('source_signer_independently_authenticated') is False,
           'wrong original labels posture')
    original=panel.get('cases')
    expect(type(original) is list and len(original)==128,'128 original cases required')
    result={}
    groups=set()
    for row in original:
        cid=row['case_id'];gid=row['group_id']
        expect(type(cid) is str and cid==gid[:24] and row['source_digest']==gid
               and row.get('split')=='new_holdout' and gid not in groups
               and cid not in result and type(row['label']) is int
               and row['label'] in (0,1),'invalid/duplicate original source truth')
        expect(sha256(canonical(row['joint_input'])).hexdigest()==row['joint_input_digest'],
               'original joint input text digest mismatch')
        groups.add(gid)
        result[cid]=(gid,row['joint_input_digest'],row['label'])
    expect(Counter(x[2] for x in result.values())=={0:64,1:64},
           'original labels not independent balanced panel')
    return result


def model_predictions(real,labels):
    expect('granite97.report.json' in real and 'mmbert_small.report.json' in real,
           'two actual model reports required')
    source=real['current-source.sha'].decode('ascii').strip()
    expect(len(source)==40 and all(c in '0123456789abcdef' for c in source),
           'missing exact original model process source')
    old_seals=real['pre-score-seals.sha256'].decode('utf-8')
    result={}
    for model,revision,pooling in [
            ('granite97','835ad14087e140460703cf0fae09f97d469d65c2','cls_l2'),
            ('mmbert_small','0eb3d056ec1d6333cf4e19b0966dfde342a41a3a','masked_mean_l2')]:
        rb=real[model+'.report.json']
        expect(sha256(rb).hexdigest() in old_seals,'not in registered pre-scoring seals')
        report=json_load(rb)
        expect(report.get('model_id')==model and report.get('revision')==revision
               and report.get('pooling')==pooling
               and report.get('schema')=='hepta.p0.compact.physical-trial.v1'
               and report.get('production_accepted') is False
               and report.get('authenticity_independently_verified') is False
               and report.get('chronological_future_verified') is False
               and report.get('actual_encoder_forward_count')==352,
               'false report identity or unsupported model claim')
        rows={}
        original=report['future_predictions']
        expect(type(original) is list and len(original)==192
               and Counter(item['split'] for item in original)=={'test':64,'new_holdout':128},
               'original real-model 192-row evidence not complete')
        for row in original:
            if row['split']!='new_holdout':
                continue
            cid=row['case_id']
            expect(cid in labels and cid not in rows
                   and (row['group_id'],row['joint_input_digest'])==labels[cid][:2],
                   'model prediction not same independently labeled group')
            prob=row['probs']['learned_gate']
            enc=row['encoder_forward_ns'];head=row['head_ns']['learned_gate']
            expect(type(prob) in (int,float) and isfinite(prob) and 0<=prob<=1
                   and type(enc) is int and enc>0 and type(head) is int and head>0,
                   'invalid original probability or physical meter')
            rows[cid]=(prob,enc+head)
        expect(set(rows)==set(labels),'missing physical outcome/label pair')
        result[model]=rows
    return result


def independent_score(labels,models):
    """The five predeclared routes; review against original labels only HERE."""
    scored={}
    for arm,threshold in ARMS.items():
        right=0; brier=0.; cost=0; calls=0; win_against_g=0;loss_against_g=0
        for cid,(_,_,label) in labels.items():
            p,c0=models['granite97'][cid]
            q,c1=models['mmbert_small'][cid]
            if arm=='mmbert_only':
                chosen=q;budget=c1
            elif arm=='granite_only':
                chosen=p;budget=c0
            else:
                second=max(p,1-p)<threshold
                chosen=q if second else p
                budget=c0+(c1 if second else 0)
                calls+=int(second)
            good=(chosen>=.5)==bool(label)
            ggood=(p>=.5)==bool(label)
            win_against_g+=int(good and not ggood)
            loss_against_g+=int(ggood and not good)
            right+=int(good)
            brier+=(chosen-label)**2
            cost+=budget
        scored[arm]={'correct':right,'n':len(labels),'accuracy':right/len(labels),
                     'brier':brier/len(labels),
                     'hypothetical_secondary_model_calls':calls,
                     'archived_per_case_wall_proxy_ns_sum':cost,
                     'paired_recovered_from_granite':win_against_g,
                     'paired_lost_from_granite':loss_against_g}
    # Unattainable case-by-case label oracle: upper bound for only these TWO fixed
    # archived prediction classifiers, NOT a valid label-blind action policy.
    g=models['granite97'];m=models['mmbert_small']
    gg=mm=joint=union=0
    for cid,(_,_,label) in labels.items():
        a=(g[cid][0]>=.5)==bool(label)
        b=(m[cid][0]>=.5)==bool(label)
        gg+=a;mm+=b;joint+=a and b;union+=a or b
    return {'arms':scored,
            'paired_correctness':{'granite':gg,'mmbert':mm,'both_right':joint,
                                  'at_least_one_right':union,
                                  'oracle_extra_correct_over_granite':union-gg,
                                  'oracle_uses_future_labels_is_not_an_admissible_policy':True}}


def agree(original,second):
    expect(original.get('schema')=='hepta.e7.real-two-stem-routed-retrospective-score.v1'
           and original.get('authority')=='DENY_ALL'
           and original.get('production_accepted') is False
           and original.get('actual_on_demand_encoder_calls_executed')==0,
           'first-score source or authority mismatch')
    expect(type(original.get('arms')) is dict and set(original['arms'])==set(ARMS),
           'first-score undeclared arms')
    for arm in ARMS:
        left=original['arms'][arm];right=second['arms'][arm]
        for k in ('correct','n','hypothetical_secondary_model_calls',
                  'archived_per_case_wall_proxy_ns_sum',
                  'paired_recovered_from_granite','paired_lost_from_granite'):
            expect(left[k]==right[k],f'independent {arm}.{k} disagreement')
        for k in ('brier','accuracy'):
            expect(isclose(left[k],right[k],rel_tol=0.,abs_tol=1e-14),
                   f'independent {arm}.{k} numerical disagreement')


def report(historical,physical,primary,output):
    old=archive(historical,HIST_SHA);new=archive(physical,REAL_SHA)
    labels=group_labels(old)
    independent=independent_score(labels,model_predictions(new,labels))
    p=Path(primary)
    pb=p.read_bytes()
    primary_review=json_load(pb)
    agree(primary_review,independent)
    record={'schema':'hepta.e7.independent-dual-algorithm-real-retrospective.v1',
            'original_labels_sha256':HIST_SHA,'real_pretrained_archive_sha256':REAL_SHA,
            'primary_original_review_sha256':sha256(pb).hexdigest(),
            'observed_source_groups':len(labels),
            **independent,
            'all_predeclared_threshold_gates_lose_to_granite_only':all(
                independent['arms'][a]['correct']<independent['arms']['granite_only']['correct']
                for a in ('gate_conf_075','gate_conf_090','gate_conf_098')),
            'original_source_signer_independently_authenticated':False,
            'actual_online_second_model_invocations_executed':0,
            'actual_future_time_outcomes_observed':False,
            'model_winner_selected':False,'production_accepted':False,
            'authority':'DENY_ALL'}
    with Path(output).open('xb') as f:
        f.write(canonical(record))
    return {'independent_report_sha256':sha256(Path(output).read_bytes()).hexdigest(),
            'oracle_upper_bound_correct':record['paired_correctness']['at_least_one_right'],
            'gate_routes_loss_confirmed':record['all_predeclared_threshold_gates_lose_to_granite_only'],
            'authority':'DENY_ALL'}


def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('--historical',required=True);a.add_argument('--physical',required=True)
    a.add_argument('--original-score',required=True);a.add_argument('--output',required=True)
    args=a.parse_args()
    print(json.dumps(report(args.historical,args.physical,args.original_score,args.output),sort_keys=True))


if __name__=='__main__':
    main()
