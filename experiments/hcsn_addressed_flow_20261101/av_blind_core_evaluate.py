"""Prospective one-actor probe of already frozen common-encoder AV cores.

This wrapper preserves the original eight-actor evaluator and all trained
weights. A single sampling cluster supports point estimates, not population
uncertainty or adoption claims. No training or candidate selection occurs here.
"""

import argparse
import json
from pathlib import Path
import time

import numpy as np
import torch

from . import av_confirmation_guard as guard
from . import av_core_study as core
from . import av_frontend as front


HERE = Path(__file__).resolve().parent
CORE = HERE / 'results/av_core001'
ORIGINAL = HERE / 'results/av_development/fit003'
BLIND = HERE / 'results/av_blind1019_candidates'
COHORT = HERE / 'results/av_development/BLIND_ACTOR1019_COHORT.json'
METADATA = HERE / 'results/av_development/BLIND_ACTOR1019_COHORT_METADATA.json'
HISTORY = HERE / 'results/av_development/HISTORICAL_ACTOR_UNION_PROOF.json'
CORE_SHA = '50163923f4312b63aefc29af4135279ba7da77cb251466eae29a9467b259e0fc'
ORIGINAL_SHA = '18cf5752c049656156a1b87c05be95fa463f37c885cbc2188901f8fd0b46a495'
BLIND_SHA = 'e15355f634395a67fd30e90aec3919b37d41be41a63e88055da400150a27b68e'
HISTORY_SHA = '7af9b818d9f33c4ef09cbb1f92f8a145e2514669380ca35e48a115d47d51631b'


def read(path):
    return json.loads(Path(path).read_text())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def static_identity():
    """Validate the whole old-model/new-cohort handoff without opening media."""
    hashes = {}
    def check(path, expected=None):
        actual=front.digest(path)
        require(expected is None or actual==expected, 'Identity changed: '+str(path))
        hashes[str(Path(path).relative_to(core.ROOT))]=actual
    check(CORE/'ALL_CHECKPOINTS.json',CORE_SHA)
    candidate=read(CORE/'ALL_CHECKPOINTS.json');protocol=read(CORE/'PROTOCOL.json')
    training=read(CORE/'TRAINING_SOURCE.json')
    check(CORE/'PROTOCOL.json',candidate['protocol_sha256'])
    check(CORE/'TRAINING_SOURCE.json')
    require(training['source_commit']==candidate['source_commit'] and
            training['protocol_sha256']==candidate['protocol_sha256'], 'Training source mismatch')
    require(not candidate['failed'] and candidate['source_unchanged'] and
            candidate['protocol_unchanged'], 'Original campaign was not complete and frozen')
    require(core.sources()==protocol['source_hashes'], 'Original scientific source changed')
    wanted={(arm,seed) for arm in core.ARMS for seed in core.SEEDS}
    require(len(candidate['fits'])==len(wanted) and
            {(r['arm'],r['seed']) for r in candidate['fits']}==wanted, 'Missing or duplicated core')
    for fit in candidate['fits']:
        require(fit['status']=='completed', 'Incomplete core fit')
        check(CORE/fit['checkpoint'],fit['checkpoint_sha256'])
    for path,expected in protocol['source_hashes'].items():
        check(core.ROOT/path,expected);check(CORE/'sources'/path,expected)
    check(CORE/'INPUTS.npz',protocol['inputs_sha256'])
    check(CORE/'relation_head.npz',protocol['relation_head_sha256'])
    check(CORE/'CANDIDATES.json',ORIGINAL_SHA)
    require(protocol['frontend_candidate_sha256']==ORIGINAL_SHA and
            candidate['frontend_candidate_sha256']==ORIGINAL_SHA,'Original frontend mismatch')
    check(ORIGINAL/'CANDIDATES.json',ORIGINAL_SHA)
    check(BLIND/'CANDIDATES.json',BLIND_SHA)
    old=front.load_freeze(ORIGINAL/'CANDIDATES.json');new=front.load_freeze(BLIND/'CANDIDATES.json')
    require(old['checkpoints']==new['checkpoints'] and old['selected']==new['selected'],
            'Blind cohort changed trained encoders or selected hyperparameters')
    require(old['source_sha256']==new['source_sha256'] and
            old['protocol_sha256']==new['protocol_sha256'], 'Frontend source handoff changed')
    for row in old['checkpoints']:
        check(ORIGINAL/row['file'],row['sha256']);check(BLIND/row['file'],row['sha256'])
    preflight=guard.verify_candidate(BLIND/'CANDIDATES.json',BLIND_SHA,COHORT,METADATA,
                                     HISTORY,HISTORY_SHA,'globally_unseen')
    require(preflight['splits']['test']==['1019'] and not preflight['prior_exposure_actors'],
            'Expected the one documented unused actor')
    for path,expected in preflight['inputs_sha256'].items():check(Path(path),expected)
    check(__file__);check(guard.__file__)
    return hashes,candidate


def freeze(out):
    hashes,_=static_identity()
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    plan=dict(schema='hcsn.av.one.actor.core.plan.v1',static_inputs_sha256=hashes,
        core_candidate_sha256=CORE_SHA,original_frontend_sha256=ORIGINAL_SHA,
        blind_frontend_sha256=BLIND_SHA,history_proof_sha256=HISTORY_SHA,
        actor='1019',expected_episodes=48,expected_total_weight=72,
        arms=list(core.ARMS),seeds=list(core.SEEDS),conditions=list(core.CONDITIONS),
        models='Reuse all fifteen original trained state dictionaries through original new_model/logits',
        input='Identical three frozen encoder probabilities; one-second accepted prefix; original token timing',
        required_guard='Confirm-mode passed receipt for twelve raw files, thirty-six feature archives and all reconstructed split arrays; metadata-only receipt is insufficient',
        selection='No refit, tuning, model selection or threshold change after media access',
        metrics=['weighted correct mass','weighted accuracy','cross entropy','raw per-episode logits and scores','resampling logit difference'],
        latency=dict(warmup=3,repeats=9,batches=[1,24],scope='Core only on already extracted/encoded observations'),
        references=['same frozen learned multilinear relation head','same independence-assumption construction'],
        sampling_clusters=1,population_confidence_intervals=False,adoption_qualification=False,
        prior_exposure='Absent from explicitly audited ninety-actor union, not an assertion about all unrecorded external history',
        costs='Inference CPU separately metered; original training, acquisition, preparation and frontend costs retained in other receipts; no CPU-to-joule conversion')
    core.write(out/'PLAN.json',plan)
    return dict(plan_sha256=front.digest(out/'PLAN.json'),static_inputs=len(hashes))


def point_metrics(scores,y,weights):
    scores=np.asarray(scores,dtype=float);correct=(scores>=.5)==y
    clipped=np.clip(scores,1e-12,1-1e-12)
    return dict(weighted_correct_mass=float(np.sum(weights*correct)),total_weight=float(weights.sum()),
        weighted_accuracy=float(np.average(correct,weights=weights)),correct_episodes=int(correct.sum()),
        episodes=len(y),cross_entropy=float(np.average(-y*np.log(clipped)-(1-y)*np.log1p(-clipped),weights=weights)),
        sampling_clusters=1,population_confidence_interval=None)


def evaluate(out,confirmation,guard_receipt,plan_sha):
    out,confirmation=Path(out),Path(confirmation)
    require(front.digest(out/'PLAN.json')==plan_sha,'Exact prospective plan hash required')
    plan=read(out/'PLAN.json');hashes,candidate=static_identity()
    require(hashes==plan['static_inputs_sha256'],'Static source/model/cohort identity changed')
    proof=read(guard_receipt)
    require(proof['passed'] is True and proof['mode']=='confirm' and
            proof['candidate_freeze_sha256']==BLIND_SHA and
            proof['scientific_status']=='one_documented_unseen_actor_blind_probe',
            'Successful prepared-input guard for this exact blind candidate required')
    require(proof['prospective_actors']==['1019'] and not proof['prior_exposure_actors'] and
            proof['population_adoption_claim_established'] is False,'Wrong scientific qualification')
    checked=proof['prepared']
    require(checked['all_reconstructed_arrays_equal'] is True and checked['raw_files']==12 and
            checked['derived_feature_archives']==36 and checked['episodes']==48,'Incomplete preparation proof')
    guard.verify_unchanged(proof['inputs_sha256'])
    frontend=read(confirmation/'CONFIRMATION.json')
    require(frontend['candidate_freeze_sha256']==BLIND_SHA and
            frontend['data_sha256']==checked['split_sha256'] and frontend['actors']==['1019'],
            'Wrong frozen frontend result')
    with np.load(confirmation/'predictions.npz',allow_pickle=False) as z:
        p,y,w,actors=z['probabilities'].astype(np.float32),z['y'],z['sample_weight'],z['actor']
    require(p.shape==(48,3) and set(actors)=={'1019'} and float(w.sum())==72.,'Wrong blind cohort shape')
    split_paths=[Path(name) for name in proof['inputs_sha256'] if Path(name).name=='independent_test.npz']
    require(len(split_paths)==1,'Ambiguous verified split')
    with np.load(split_paths[0],allow_pickle=False) as z:
        require(np.array_equal(y,z['y']) and np.array_equal(w,z['sample_weight']) and
                np.array_equal(actors,z['actor']),'Prediction labels/weights/order changed')
    destination=out/'confirmation';destination.mkdir(exist_ok=False)
    wall,cpu=time.perf_counter(),time.process_time();results=[]
    for fit in candidate['fits']:
        model=core.new_model(fit['arm'],fit['seed']).eval()
        model.load_state_dict(torch.load(CORE/fit['checkpoint'],weights_only=True,map_location='cpu'))
        for condition in core.CONDITIONS:
            output=core.logits(model,p,condition)
            scores=torch.softmax(torch.from_numpy(output),-1).numpy()[:,1].astype(float)
            row=dict(arm=fit['arm'],seed=fit['seed'],condition=condition,**point_metrics(scores,y,w))
            if condition=='base':base=output
            if condition=='resample':row['resampling_error']=float(np.max(np.abs(output-base)))
            path=destination/f"{fit['arm']}_{fit['seed']}_{condition}.npz"
            np.savez_compressed(path,logits=output,score=scores,y=y,sample_weight=w,actor=actors)
            row.update(raw_file=path.name,raw_sha256=front.digest(path),checkpoint_sha256=fit['checkpoint_sha256'])
            if condition=='base':
                row['head_only_latency']={}
                for size in (1,24):
                    times=[]
                    for repeat in range(12):
                        tick=time.perf_counter();core.logits(model,p[:size],chunk=size)
                        if repeat>=3:times.append(time.perf_counter()-tick)
                    row['head_only_latency'][str(size)]=dict(seconds=times,median_seconds=float(np.median(times)),episodes_per_second=size/float(np.median(times)))
            results.append(row)
    with np.load(CORE/'relation_head.npz',allow_pickle=False) as z:
        learned=1/(1+np.exp(-(front.relation_features(p)@z['coef']+z['intercept'])))
    constructed=front.constructed_posterior(p)
    reference_path=destination/'reference_predictions.npz'
    np.savez_compressed(reference_path,learned_relation=learned,constructed=constructed,y=y,sample_weight=w,actor=actors)
    summary=dict(schema='hcsn.av.one.actor.core.result.v1',results=results,
        references={'learned_relation':point_metrics(learned,y,w),'constructed':point_metrics(constructed,y,w)},
        plan_sha256=plan_sha,core_candidate_sha256=CORE_SHA,blind_frontend_sha256=BLIND_SHA,
        guard_receipt_sha256=front.digest(guard_receipt),frontend_result_sha256=front.digest(confirmation/'CONFIRMATION.json'),
        encoder_predictions_sha256=front.digest(confirmation/'predictions.npz'),reference_predictions_sha256=front.digest(reference_path),
        cpu_seconds=time.process_time()-cpu,wall_seconds=time.perf_counter()-wall,energy_joules=None,gpu=None,
        sampling_clusters=1,population_confidence_intervals=False,adoption_qualification=False,
        scope='One documented unseen actor; point estimates only; same fifteen previously trained cores; no retuning')
    core.write(destination/'SUMMARY.json',summary)
    return summary


def smoke():
    """No confirmation data: verify all fifteen frozen cores on generated input."""
    _,candidate=static_identity();p=np.array([[.2,.8,.6],[.7,.3,.4]],np.float32)
    cases=[]
    for fit in candidate['fits']:
        model=core.new_model(fit['arm'],fit['seed']).eval()
        model.load_state_dict(torch.load(CORE/fit['checkpoint'],weights_only=True,map_location='cpu'))
        for condition in core.CONDITIONS:
            output=core.logits(model,p,condition)
            require(output.shape==(2,2) and np.isfinite(output).all(),'Synthetic forward failed')
            cases.append(dict(arm=fit['arm'],seed=fit['seed'],condition=condition))
    return dict(passed=True,cases=len(cases),data='Generated probabilities only; no media or confirmation input',source_sha256=front.digest(__file__))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=('freeze','evaluate','smoke'),required=True)
    parser.add_argument('--out',type=Path)
    parser.add_argument('--confirmation',type=Path)
    parser.add_argument('--guard-receipt',type=Path)
    parser.add_argument('--plan-sha256')
    a=parser.parse_args();torch.set_num_threads(1)
    if a.mode=='freeze':result=freeze(a.out)
    elif a.mode=='smoke':result=smoke()
    else:result=evaluate(a.out,a.confirmation,a.guard_receipt,a.plan_sha256)
    print(json.dumps(result,indent=2,sort_keys=True),flush=True)


if __name__=='__main__':
    main()
