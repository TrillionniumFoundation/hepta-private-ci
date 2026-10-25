"""Independent count/hash audit; recompute ECE from actual native tick confidence."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np

from ...abc_recovery.training_run import file_sha,write_json


def read_rows(path):
    with gzip.open(path,'rt') as f:return [json.loads(line) for line in f]


def ece(p,y):
    bins=np.minimum((p//100000).astype(int),9)
    return sum(abs(y[bins==b].sum()-p[bins==b].sum()/1e6) for b in range(10))/len(y)


def audit(calibration,verification,native,output):
    cohorts={};identities={};checks=0
    for label,directory in [('calibration',calibration),('verification',verification)]:
        rows=read_rows(directory/'rows.jsonl.gz');ids=[]
        with np.load(directory/'features.npz',allow_pickle=False) as archive:x=archive['x_q24']
        for i,row in enumerate(rows):
            ids.extend(row['source_ids'])
            if row['feature_sha256']!=hashlib.sha256(x[i].tobytes()).hexdigest():raise ValueError('Feature row hash changed')
            for modality,filename in [('image','image.png'),('text','caption.txt')]:
                path=directory/'media'/f"{row['pair']:04d}"/filename
                if file_sha(path)!=row['raw_sha256'][modality]:raise ValueError('Original emitted media changed')
                checks+=1
        if len(set(ids))!=len(ids):raise ValueError('Repeated original source')
        identities[label]=set(ids)
        cohorts[label]={'pairs':len(rows),'original_images':len(ids),
            'ood_pairs':sum(r['is_declared_ood'] for r in rows),'rows_sha256':file_sha(directory/'rows.jsonl.gz')}
    if identities['calibration'] & identities['verification']:raise ValueError('Overlapping qualification source roles')
    rows=read_rows(verification/'rows.jsonl.gz')
    ticks=[json.loads(line) for line in (native/'ticks.jsonl').read_text().splitlines()]
    if len(ticks)!=len(rows) or any(t['pair']!=r['pair'] or t['joint_correct']!=r['joint_correct']
                                  for t,r in zip(ticks,rows)):raise ValueError('Native row identity mismatch')
    p=np.asarray([t['confidence_ppm'] for t in ticks],dtype=np.int64)
    y=np.asarray([r['joint_correct'] for r in rows]);ood=np.asarray([r['is_declared_ood'] for r in rows])
    native_ece_id=ece(p[~ood],y[~ood]);native_ece_full=ece(p,y)
    rng=np.random.default_rng(28191017);bootstrap=[]
    strata=[np.asarray([i for i,r in enumerate(rows) if r['view']==v]) for v in
            ('clean','noise','occlusion','missing_trusted','conflict_untrusted')]
    for _ in range(4000):
        sample=np.concatenate([rng.choice(s,len(s),replace=True) for s in strata]);bootstrap.append(ece(p[sample],y[sample]))
    success=int(y[~ood].sum());n=int((~ood).sum());phat=success/n;z=1.959963984540054
    center=(phat+z*z/(2*n))/(1+z*z/n)
    half=z*np.sqrt(phat*(1-phat)/n+z*z/(4*n*n))/(1+z*z/n)
    groups=[]
    for probability in sorted(set(p.tolist())):
        use=p==probability;groups.append({'confidence_ppm':probability,'n':int(use.sum()),'successes':int(y[use].sum()),
                                        'actual_success':float(y[use].mean()),'ood_count':int(ood[use].sum())})
    report={'schema':'hepta.abc3.native-independent-count-audit.v1','cohorts':cohorts,
        'calibration_verification_source_overlap':0,'raw_media_file_hashes_recomputed':checks,
        'feature_row_hashes_recomputed':sum(v['pairs'] for v in cohorts.values()),
        'native_ticks_joined_to_original_verification_pairs':len(ticks),'native_replay_adds_independent_samples':0,
        'ece_from_actual_native_confidence_id':native_ece_id,'ece_from_actual_native_confidence_full':native_ece_full,
        'verification_id_accuracy_wilson_95':[center-half,center+half],
        'id_ece_stratified_pair_bootstrap_percentile_95':np.quantile(bootstrap,[.025,.975]).tolist(),
        'bootstrap_replicates':4000,'bootstrap_seed':28191017,'bootstrap_is_not_additional_evidence':True,
        'ece_interval_is_descriptive_not_a_changed_admission_gate':True,'groups':groups,
        'native_tick_file_sha256':file_sha(native/'ticks.jsonl')}
    write_json(output,report);print(json.dumps(report,sort_keys=True))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('calibration','verification','native','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();audit(a.calibration,a.verification,a.native,a.output)
