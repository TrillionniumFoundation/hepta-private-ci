"""Independently re-fit the historic E24 tau=.01 policy BEFORE any NEW holdout.

Requires exact original E15 source-owner training-only materials.  These are
previously examined, public human annotations, not new validation truth.
This stage authenticates arithmetic + byte lineage, NOT an original signer.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from math import isclose,isfinite
from pathlib import Path
from e14_multirc_route import read_prelabel
from e15_reader_crossfit import digest,verify_train
from e24_question_risk import fit_one,METHODS
from e25_fixed_policy_transfer import frozen
from e25_unseen_material import write_once

E15_FOLD_SHAS=(
    'cc1c13323cb8377cbd5cdfa5c806796cb85505746e8509f21432d83a1ac4fb2d',
    '8aa9f4b82a4478e9329cba5468adbea4a5a75bd9707b57358eb78a981cf0fd5e',
    'e097d3a3bd210c1b8a84736cc6c219ea2605763c5b83b2c823dd136c00dedec5',
    '8565aa2c841ad067d58e9ca04222247277de509bb4bdac38eb42e7662d13c6b2',
)
E15_FOLD_ARTIFACTS=(11949081037,11948881417,11948806536,11948681555)


def exact_e15_train_from_zip(path: str,fold: int):
    from zipfile import ZipFile
    source=Path(path)
    if sha256(source.read_bytes()).hexdigest()!=E15_FOLD_SHAS[fold]:
        raise ValueError('original E15 training-only ZIP SHA changed')
    with ZipFile(source) as z:
        names=z.namelist()
        if names!=[f'training-fold-{fold}.json']:
            raise ValueError('original E15 source-owner ZIP scope changed')
        raw=z.read(names[0])
    if len(raw)>10000:raise ValueError('unbounded E15 training material')
    def reject_pair(arr):
        obj={}
        for k,v in arr:
            if k in obj:raise ValueError('duplicate historical JSON field')
            obj[k]=v
        return obj
    return json.loads(raw,object_pairs_hook=reject_pair)


def refit(archive,policy_path,owner_zips):
    if type(owner_zips) is not list or len(owner_zips)!=4:
        raise ValueError('all four original source owner inputs required')
    obs=read_prelabel(archive)
    policy=frozen(policy_path)
    confirmations=[]
    for fold,source in enumerate(owner_zips):
        train=exact_e15_train_from_zip(source,fold)
        y=verify_train(obs,train)
        if len(y)<20 or len(y)>30:raise ValueError('invalid original train-only data')
        original=fit_one(obs,train)
        fixed=policy['folds'][fold]
        if (original['fold']!=fold or original['held_source_group']!=fixed['held_group']
            or original['train_only_material_sha256']!=fixed['train_only_material_sha256']
            or digest(train)!=fixed['train_only_material_sha256']
            or original['training_steps']!=48
            or original['methods']!=list(METHODS)):
            raise ValueError('frozen E24 historical source has changed')
        for name in policy['fixed_hypotheses']:
            actual=original['weights'][name]
            reference=fixed['weights'][name]
            if len(actual)!=5 or len(reference)!=5 or any(
                not isfinite(a) or not isclose(a,b,abs_tol=2e-12,rel_tol=0)
                for a,b in zip(actual,reference,strict=True)):
                raise ValueError('frozen original E24 trained coefficient is not reproduced')
        if any(not isclose(a,b,abs_tol=2e-12,rel_tol=0)
               for a,b in zip(original['training_only_scale'],fixed['scale'],strict=True)):
            raise ValueError('original E24 normalization was changed')
        confirmations.append({'fold':fold,'train_original_human_cases':len(y),
           'original_e15_owner_zip_sha256':E15_FOLD_SHAS[fold],
           'frozen_e24_two_heads_recomputed':True})
    return {'schema':'hepta.e25.independent-historical-policy-refit.v1',
       'authority':'DENY_ALL','production_accepted':False,
       'original_new_holdout_labels_read':False,
       'historical_head_recomputed_from_original_E15_human_train_material':True,
       'original_human_signer_independently_authenticated':False,
       'new_pretrained_forwards':0,'folds':confirmations,
       'source_archive_sha256':policy['model_archive_sha256'],
       'frozen_question_tau':0.01,'new_source_family_admitted':False}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for k in ('archive','frozen-policy','output'):
        ap.add_argument('--'+k,required=True)
    for i in range(4):ap.add_argument(f'--owner-{i}',required=True)
    a=ap.parse_args()
    result=refit(a.archive,a.frozen_policy,[getattr(a,f'owner_{i}') for i in range(4)])
    print(write_once(a.output,result),'DENY_ALL')

if __name__=='__main__':main()
