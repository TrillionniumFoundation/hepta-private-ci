#!/usr/bin/env python3
"""Independently bound original ScienceQA OCR accuracy WITHOUT per-case TEST labels.

This deliberately uses the *published aggregate heldout review statistics*, which
are label-derived, but never reads per-example heldout label bytes or invents
labels for performance claims. Solves sharp integer-program bounds, not a score.
"""
import hashlib, json, os, zipfile
from pathlib import Path
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

ORIGINAL=Path('/mnt/data/e3-2173-success-38678847948.zip')
OCR=Path('/mnt/data/e3-original-ocr-run-38825811927.zip')
ZIP_SHAS={'original':'f421f20cdb5d35becf5e93ed63e58996d48701c2b27b979d608e2b05b6b61f30',
          'ocr':'c80d5b9cda23a8a6ee144aeba459dc516b6b67c854c2c5fe86d3b2ba94884964'}
SHA_FILE={'original':'e6354f38de4292dda60ebab380cb13d488853b9c08371e54f8f1762827febaf7',
          'ocr':'96ba4117a37689eeafe2415661e028a9170b7ccdd8c345b6b8d6241b7a928885'}
SOURCE_SHA='a561916c7d56b6677c5511c329a49bbeec94879f019d29f159ff59be83359202'
N=64;K=4

def digest(data):return hashlib.sha256(data).hexdigest()

def archive(path,expected):
    assert digest(path.read_bytes())==expected, f'archive identity mismatch: {path.name}'
    return zipfile.ZipFile(path)

def main():
    with archive(ORIGINAL,ZIP_SHAS['original']) as z:
        old_raw=z.read('sealed-source-bound-predictions.json')
        aggregate_raw=z.read('independent-descriptive-review.json')
        manifest=z.read('SHA256SUMS').decode('ascii')
        assert digest(old_raw)==SHA_FILE['original']
        assert 'sealed-source-bound-predictions.json' in manifest
        old=json.loads(old_raw); published=json.loads(aggregate_raw)
    with archive(OCR,ZIP_SHAS['ocr']) as z:
        new_raw=z.read('e3-ocr-observed/sealed-ocr-predictions.json')
        assert digest(new_raw)==SHA_FILE['ocr']
        new=json.loads(new_raw)
    assert old['source_sha256']==new['source_sha256']==published['source_sha256']==SOURCE_SHA
    past=old['predictions']; future=new['rows']
    assert len(past)==len(future)==N
    byid={row['id']:row for row in future}
    assert len(byid)==N and len({row['id'] for row in past})==N
    assert all(p['group']==byid[p['id']]['group'] and
               p['source_input_sha256']==byid[p['id']]['source_input_sha256']
               for p in past)
    armnames=sorted(published['arms'])
    guess={a:np.array([int(np.argmax(p['arms'][a])) for p in past]) for a in armnames}
    guess['ocr_text']=np.array([int(np.argmax(byid[p['id']]['probabilities'])) for p in past])
    base=guess['text_only']
    obs=[];rhs=[]
    for i in range(N):
        arr=np.zeros((N,K));arr[i,:]=1
        obs.append(arr.ravel());rhs.append(1)
    for arm in armnames:
        arr=np.zeros((N,K));arr[np.arange(N),guess[arm]]=1
        obs.append(arr.ravel());rhs.append(published['arms'][arm]['correct'])
    for arm,pair in sorted(published['paired_vs_text_only'].items()):
        diff=guess[arm]!=base
        for key,which in [('rescued_errors_vs_text',guess[arm]),('new_errors_vs_text',base)]:
            arr=np.zeros((N,K));arr[np.arange(N)[diff],which[diff]]=1
            obs.append(arr.ravel());rhs.append(pair[key])
    A=np.stack(obs);b=np.asarray(rhs)
    c=np.zeros((N,K));c[np.arange(N),guess['ocr_text']]=1;c=c.ravel()
    exact=LinearConstraint(A,b,b)
    results=[]
    for sign in (1,-1):
        res=milp(sign*c,integrality=np.ones(N*K),bounds=Bounds(np.zeros(N*K),np.ones(N*K)),
                 constraints=[exact],options={'time_limit':30,'mip_rel_gap':0})
        assert res.status==0 and res.x is not None and res.mip_gap==0, res.message
        witnesses=np.rint(res.x)
        assert np.max(np.abs(A@witnesses-b))==0
        results.append(int(round(c@witnesses)))
    assert int(published['arms']['text_only']['correct'])==17
    report={'schema':'hepta.e3-original-ocr-aggregate-constrained-bounds.v1',
            'status':'PARTIAL_IDENTIFICATION_NOT_AN_ACCURACY_RESULT',
            'original_zip_sha256':ZIP_SHAS['original'],'original_prediction_sha256':SHA_FILE['original'],
            'ocr_zip_sha256':ZIP_SHAS['ocr'],'ocr_prediction_sha256':SHA_FILE['ocr'],
            'source_sha256':SOURCE_SHA,'cases':N,'classes':K,
            'source_id_group_sha_verified':True,
            'uses_published_label_derived_aggregate_correct_counts':True,
            'per_case_test_labels_read':False,
            'published_original_text_correct':17,
            'ocr_changed_argmax_count':int(np.sum(guess['ocr_text']!=base)),
            'ocr_compatible_correct_lower_bound':results[0],
            'ocr_compatible_correct_upper_bound':results[1],
            'ocr_compatible_accuracy_bounds':[results[0]/N,results[1]/N],
            'ocr_compatible_net_correct_gain_bounds':[results[0]-17,results[1]-17],
            'constraints':int(A.shape[0]),'binary_decision_variables':int(A.shape[1]),
            'solver':'scipy.optimize.milp (HiGHS) exact integer optimality; 0 MIP gap',
            'labeled_ocr_correctness_is_not_identified':True,
            'accuracy_superiority_claim_allowed':False,
            'stem_winner':None,'production_accepted':False,'authority':'DENY_ALL'}
    output=Path('/mnt/data/e3_ocr_original_aggregate_bounds_20261016.json')
    with output.open('x',encoding='utf8') as f:
        json.dump(report,f,sort_keys=True,indent=2)
        f.write('\n');f.flush();os.fsync(f.fileno())
    print(json.dumps(report,indent=2,sort_keys=True))

if __name__=='__main__':main()
