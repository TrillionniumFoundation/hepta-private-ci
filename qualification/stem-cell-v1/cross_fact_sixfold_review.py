"""Review six source-composition folds without rerunning or selecting a model.

This is an exploratory symbolic dataset. Aggregated rows over folds/seeds share
vocabulary and related graph structure; only fold-level differences describe
source composition transfer. It is NOT independent pretrained evidence.
"""
import argparse
import json
from pathlib import Path
from itertools import permutations

ARMS=('cross_fact','local')
SEEDS=(41,47,53)
COMPOSITIONS=tuple(permutations(range(3)))


def review(fold_files):
    if len(fold_files)!=len(COMPOSITIONS):raise ValueError('six complete folds required')
    reports=[json.loads(Path(path).read_text()) for path in fold_files]
    by_comp={tuple(x['heldout_composition']):x for x in reports}
    if set(by_comp)!=set(COMPOSITIONS):raise ValueError('missing or repeated source composition')
    folds=[]
    totals={arm:dict(correct=0,complete_questions=0,cpu_ns=0,brier_sum=0.) for arm in ARMS}
    for composition in COMPOSITIONS:
        raw=by_comp[composition]
        if (raw['schema']!='hepta.cross-fact.composition-transfer.cpu.v1'
                or raw['production_authorized'] is not False
                or raw['pretrained_improvement_established'] is not False
                or raw['encoder_pretrained'] is not False
                or raw['model_selection_permitted'] is not False
                or raw['training_graphs']!=30 or raw['heldout_graphs']!=6
                or raw['heldout_rows']!=54 or raw['train_rows']!=270
                or raw['updates_per_arm']!=800 or raw['batch_size']!=64
                or len(raw['seed_results'])!=3):
            raise ValueError('incompatible experimental fold')
        fold=dict(composition=list(composition),seeds=[])
        if tuple(row['seed'] for row in raw['seed_results']) != SEEDS:
            raise ValueError('seed roster changed')
        for row in raw['seed_results']:
            if (row['parameter_count']!=17402 or row['added_adapter_parameters']!=2304
                    or len(row['schedule_sha256'])!=64 or set(row['arms'])!=set(ARMS)):
                raise ValueError('matched Head parameters or optimizer stream missing')
            per=dict(seed=row['seed'],schedule_sha256=row['schedule_sha256'],arms={})
            optimizer_bytes=set()
            for arm in ARMS:
                a=row['arms'][arm];m=a['heldout']
                if (a['completed_updates']!=800 or a['exposures']!=51200
                        or m['total']!=54 or m['questions']!=18
                        or not 0<=m['correct']<=54 or not 0<=m['complete_questions']<=18
                        or a['cpu_ns']<=0 or a['optimizer_tensor_bytes']<=0):
                    raise ValueError('incomplete physical experiment or heldout roster')
                optimizer_bytes.add(a['optimizer_tensor_bytes'])
                per['arms'][arm]=dict(heldout_correct=m['correct'],heldout_question_em=m['complete_questions'],
                                      positive_f1=m['positive_f1'],heldout_brier=m['brier'],
                                      cpu_ns=a['cpu_ns'])
                totals[arm]['correct']+=m['correct']
                totals[arm]['complete_questions']+=m['complete_questions']
                totals[arm]['cpu_ns']+=a['cpu_ns']
                totals[arm]['brier_sum']+=m['brier']
            if len(optimizer_bytes)!=1:raise ValueError('unequal optimizer state bytes')
            fold['seeds'].append(per)
        fold['cross_minus_local_correct']=sum(s['arms']['cross_fact']['heldout_correct']-
            s['arms']['local']['heldout_correct'] for s in fold['seeds'])
        folds.append(fold)
    return dict(schema='hepta.cross-fact.composition-sixfold-review.v1',
        status='exploratory_synthetic_only',
        folds=folds, totals=totals, candidate_observations=6*3*54,
        question_observations=6*3*18,
        independent_composition_types=6,
        always_negative_candidate_correct=6*3*36,
        always_negative_complete_question=0,
        generalized_natural_reasoning_proven=False,
        selected_model=False, source_disjoint_compositions=True,
        pretrained_granite_executed=False, production_authorized=False)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fold_files',nargs=6,type=Path)
    args=parser.parse_args()
    print(json.dumps(review(args.fold_files),sort_keys=True,indent=2,allow_nan=False))
