"""Fixed-pixel development study of the repository's actual consolidation fitter.

Same previously used bundled dataset: NOT a new independent evaluation cohort.
No Encoder is trained/loaded. Three seeds and all candidates are retained.
"""
import argparse
from pathlib import Path
import torch
from sklearn.datasets import load_digits
from experiments.shared_stem_cell import execution as e, consolidation as c

def main(output):
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    data = load_digits()
    pixels = torch.tensor(data.data, dtype=torch.float32)
    identities = [e.sha(row.to(torch.uint8).numpy().tobytes()) for row in pixels]
    partition = [int(e.sha(('consolidation-v1:'+v).encode())[:8],16)%10 for v in identities]
    folds = {'train':[i for i,k in enumerate(partition) if k<6],
             'calibration':[i for i,k in enumerate(partition) if 6<=k<8],
             'holdout':[i for i,k in enumerate(partition) if k>=8]}
    routes = torch.tensor([int(v[8:16],16)%8 for v in identities], dtype=torch.long)
    x = pixels/16.0
    e.write_once(output/'plan.json', {'source': 'bundled real UCI digits; raw pixels/16',
        'cohort': [[v, partition[i], int(routes[i])] for i,v in enumerate(identities)],
        'fold_rows': {k:len(v) for k,v in folds.items()}, 'seeds':[17,29,43], 'teacher_steps_per_cell':80,
        'student_steps_per_arm':80, 'cells':8, 'feature_sha256': e.tensor_digest(x),
        'source_sha256': {n:e.sha((Path(e.__file__).parent/n).read_bytes())
                         for n in ('execution.py','consolidation.py','consolidation_digits.py')},
        'new_independent_holdout':False, 'pretrained_encoder':False, 'production_accepted':False})
    tr,cal,hold=folds['train'],folds['calibration'],folds['holdout']
    target=lambda ids: torch.tensor([int(data.target[i]) for i in ids],dtype=torch.long)
    records=[]
    for seed in (17,29,43):
        teachers,costs=[],[]
        for cell in range(8):
            ids=[i for i in tr if routes[i]==cell]
            with torch.random.fork_rng(devices=[]):
                torch.manual_seed(seed+cell)
                model,cost=e.fit(e.Head(64,10,'gated',8),x[ids],target(ids),steps=80,seed=seed)
            teachers.append(model.eval().requires_grad_(False)); costs.append(cost)
        models, selection=c.fit_students(tuple(teachers),x[tr],routes[tr],target(tr),
                                          x[cal],routes[cal],target(cal),steps=80,seed=seed)
        selection_sha=e.write_once(output/f'{seed}-selection.json',selection)
        values=c.predict(tuple(teachers),models,selection,x[hold],routes[hold])
        prediction_sha=e.write_once(output/f'{seed}-predictions.json',{'row_ids':hold,'selection_sha256':selection_sha,**values})
        records.append({'seed':seed,'prediction_sha256':prediction_sha,'selection_sha256':selection_sha,
                        'teacher_training':costs})
    # First holdout-label read happens after EVERY seed has sealed predictions.
    gold=target(hold)
    for rec in records:
        predicted=e.decode(e.bound_file(output/f"{rec['seed']}-predictions.json",rec['prediction_sha256']))
        selection=e.decode(e.bound_file(output/f"{rec['seed']}-selection.json",rec['selection_sha256']))
        rec.update(scores={k:c.score(p,gold,routes[hold],8) for k,p in predicted['predictions'].items()},
                   selected=selection['selected'], parameter_counts=selection['parameter_counts'])
    e.write_once(output/'report.json', {'records':records, 'holdout_rows':len(hold),
        'all_candidates_retained':True,'new_independent_holdout':False,'production_accepted':False})

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--output',type=Path,required=True)
    main(p.parse_args().output)
