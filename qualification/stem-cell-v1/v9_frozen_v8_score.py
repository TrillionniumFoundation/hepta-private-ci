"""Independent source-group score of archived trained V8 SYNTHETIC checkpoints.

No Trainer import, no forward or new model selection; recomputes scores from raw
sealed probabilities with seed retained in every independent group identity.
"""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path

from v9_typed_graph import digest
from v9_blind_benchmark import read, write_once

SEEDS=(41,47,53)
ARMS=('base','bridge','wide','endpoint')


def score(public_path, truth_path, frozen_path, out_path):
    public,truth,frozen=(read(p) for p in (public_path,truth_path,frozen_path))
    expected={f'{seed}/{arm}' for seed in SEEDS for arm in ARMS}
    case_ids=[c['case_id'] for c in public]
    if (len(case_ids)!=1248 or len(set(case_ids))!=1248
            or set(case_ids)!=set(truth)
            or frozen.get('schema')!='hepta.v9.previous-synthetic-head-zero-shot.v1'
            or frozen.get('public_sha256')!=digest(public)
            or frozen.get('candidate_ids')!=case_ids
            or frozen.get('probs_sha256')!=digest(frozen['probabilities'])
            or set(frozen.get('probabilities',{}))!=expected
            or set(frozen.get('weight_files',{}))!=expected
            or frozen.get('actual_pretrained_encoder_forwards')!=0
            or frozen.get('optimizer_updates')!=0
            or frozen.get('V9_label_access') is not False
            or frozen.get('V9_checkpoint_selection') is not False
            or frozen.get('authority')!='DENY_ALL'
            or frozen.get('production_accepted') is not False):
        raise ValueError('frozen public source, complete weights/panel or authority mismatch')
    groups=defaultdict(list)
    for c in public:
        fields=c['case_id'].split('/')
        if (len(fields)!=5 or fields[0] not in ('train','held_known','held_novel')
                or fields[3] not in ('world-0','world-1')
                or fields[4] not in ('candidate-0','candidate-1')):
            raise ValueError('registered group identity required')
        groups[(fields[0],int(fields[1]),c['source_group'])].append(c)
    if len(groups)!=312 or any(len(x)!=4 for x in groups.values()):
        raise ValueError('complete 312 unique four-row group universe required')
    stats=[]
    for model, probs in sorted(frozen['probabilities'].items()):
        seed,arm=model.split('/')
        if (set(probs)!=set(case_ids)
                or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in probs.values())):
            raise ValueError('complete finite same-source probabilities required')
        counts=defaultdict(lambda:dict(rows=0,right=0,pairs=0,both=0,groups=0,all_four=0,ce=0.))
        for (role,depth,source_id),rows in groups.items():
            preds=[int(probs[c['case_id']]>0.5) for c in rows]
            labels=[truth[c['case_id']] for c in rows]
            if sorted(labels)!=[0,0,1,1]:
                raise ValueError('paired-world labels not balanced')
            by_candidate=defaultdict(list)
            for c,pred,label in zip(rows,preds,labels):
                by_candidate[c['case_id'].split('/')[-1]].append((pred,label))
            if set(by_candidate)!={'candidate-0','candidate-1'} or any(len(p)!=2 for p in by_candidate.values()):
                raise ValueError('complete per-source paired candidates required')
            right=sum(p==t for p,t in zip(preds,labels))
            both=sum(all(p==t for p,t in pair) for pair in by_candidate.values())
            cross_entropy=sum(-math.log(max(1e-12,probs[c['case_id']] if t else 1-probs[c['case_id']]))
                              for c,t in zip(rows,labels))
            k=role,depth
            e=counts[k]
            e['rows']+=4;e['right']+=right;e['pairs']+=2;e['both']+=both
            e['groups']+=1;e['all_four']+=right==4;e['ce']+=cross_entropy
        for (role,depth),e in sorted(counts.items()):
            stats.append(dict(seed=int(seed),arm=arm,role=role,depth=depth,**e,
                candidate_accuracy=e['right']/e['rows'],
                pair_accuracy=e['both']/e['pairs'],
                mean_CE=e['ce']/e['rows'],
                independent_groups=e['groups'],
                same_cases_across_seeds=True))
    payload=dict(schema='hepta.v9.original-v8-frozen-independent-score.v1',
        original_models=12, zero_new_training=True, pretrained_encoder_forwards=0,
        source_sha256=frozen['public_sha256'], probability_sha256=frozen['probs_sha256'],
        observations=stats, true_independent_source_groups=312,
        model_seed_repetitions_not_independent_source_groups=True,
        grammar_training_is_not_natural_generalization=True,
        selected_winner=False, original_v7_joint_qualified=False,
        production_accepted=False, authority='DENY_ALL')
    write_once(out_path,payload)
    return payload


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('public','truth','frozen','output'):
        p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args()
    x=score(a.public,a.truth,a.frozen,a.output)
    print(json.dumps({'observations':len(x['observations']),'sha256':digest(x['observations']),
                      'selected_winner':False,'authority':x['authority']}))

if __name__=='__main__':
    main()
