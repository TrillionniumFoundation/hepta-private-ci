"""Read-only recomputation over saved two-window paired-continuation observations.

Reject incomplete/rewritten source/predictions/score, fake arms, physical work
and unsupported capability. This is local self-audit, not external attestation.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from paired_continuation import digest,public_panel
from paired_continuation_evaluator import score
from paired_trial_replay import SCRIPTS


def sha_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def audit(folder):
    root=Path(folder)
    def read(name):
        return json.loads((root/name).read_text(encoding='utf-8'))
    report=read('report.json')
    seal=read('seal.json')
    train=read('train_rows.json')
    worlds=read('train_worlds.json')
    panels={k:read(k+'.json') for k in ('future_1','future_2')}
    if report.get('schema')!='hepta.ndu-system2.paired-continuation-replay.v1' or report.get('authority')!='DENY_ALL' or report.get('production_accepted') is not False:
        raise ValueError('missing deny-all report identity')
    for k in ('p3_qualified','p5_qualified','p0_real_model_qualified',
              'independent_natural_outcome_verified','source_owner_signature_verified',
              'no_label_access_enforced_by_cryptographic_trust','matched_physical_compute_established',
              'real_ndu_fbsde_solved'):
        if report.get(k) is not False:
            raise ValueError('unsupported qualification claim: '+k)
    if report.get('real_pretrained_encoder_forward_count')!=0 or seal.get('pretrained_encoder_executed') is not False:
        raise ValueError('fake pretrained Encoder evidence')
    if type(worlds) is not dict or set(worlds)!={'train_rows_sha256','worlds'} or worlds['train_rows_sha256']!=digest(train):
        raise ValueError('train-world binding mismatch')
    if len(worlds['worlds'])!=len(train) or report.get('training_pairs_actually_fitted')!=3*len(train) or report['training_pairs_actually_fitted']!=seal['actual_training_pairs']:
        raise ValueError('training pairs incomplete')
    if report.get('seal_sha256')!=digest(seal) or seal.get('authority')!='DENY_ALL' or seal.get('production_accepted') is not False:
        raise ValueError('sealed prediction mismatch')
    if seal['train_rows_sha256']!=digest(train) or seal['training_observations_sha256']!=digest(worlds['worlds']):
        raise ValueError('train evidence changed')
    names=('train_rows.json','train_worlds.json','future_1.json','future_2.json')
    if set(report['source_file_bytes_sha256'])!=set(names) or any(report['source_file_bytes_sha256'][name]!=sha_file(root/name) for name in names):
        raise ValueError('raw source files drifted')
    src=Path(__file__).resolve().parent
    if set(report['code_file_bytes_sha256'])!=set(SCRIPTS) or any(report['code_file_bytes_sha256'][name]!=sha_file(src/name) for name in SCRIPTS):
        raise ValueError('code identity differs from executed report')
    cohorts=[public_panel(train,'train')]
    for k in ('future_1','future_2'):
        cohorts.append(public_panel(panels[k],k))
    if any(cohorts[a]&cohorts[b] for a,b in ((0,1),(0,2),(1,2))):
        raise ValueError('cross-window/source identity reuse')
    if set(report.get('prospective_results',{}))!={'future_1','future_2'}:
        raise ValueError('incomplete two-window report')
    checked=0
    for window, seed in (('future_1',919),('future_2',929)):
        external=read(window+'.score.json')
        independent=score(panels[window],seal,sealed_sha256=report['seal_sha256'],
                          window=window,world_seed=seed)
        if independent!=external:
            raise ValueError('independent recomputation disagrees with evaluator receipt')
        sample=report['prospective_results'][window]
        if sample['source_sha256']!=independent['future_public_sha256'] or sample['evaluated_cases']!=len(panels[window]) or sample['world_seed_after_seal']!=seed or sample['arms']!=independent['arms']:
            raise ValueError('report changes scores/omits cohort')
        base=independent['arms']
        if base['exact_tree']['expected_regret_to_exact_tree']!=0.0 or base['learned_critic']['expected_regret_to_exact_tree'] < -1e-12:
            raise ValueError('reported learned critic better than exact oracle without support')
        checked+=len(panels[window])
    return {'schema':'hepta.ndu-system2.paired-local-audit.v1',
            'cohort_count':3,'future_windows_checked':2,'future_cases_recomputed':checked,
            'frozen_report_sha256':sha_file(root/'report.json'),
            'verified_source_and_action_receipts':True,
            'external_source_authentication_established':False,
            'real_model_reasoning_gain_established':False,
            'p3_qualified':False,'p5_qualified':False,
            'production_accepted':False,'authority':'DENY_ALL'}


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--directory',required=True)
    cli.add_argument('--audit',required=True)
    args=cli.parse_args()
    result=audit(args.directory)
    with Path(args.audit).open('x',encoding='utf-8') as f:
        f.write(json.dumps(result,sort_keys=True,separators=(',',':'))+'\n')
    print(json.dumps(result,sort_keys=True))

if __name__=='__main__':main()
