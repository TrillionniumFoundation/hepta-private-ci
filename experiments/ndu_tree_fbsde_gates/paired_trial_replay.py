"""Execute frozen paired-world learning with two sealed future windows.

No network, credential, pretrained checkpoints, native Neuron, or authority.
Stages are *separate processes*: train-only critic -> prediction seal ->
future-world evaluator. Deterministic seeds are public, so source secrecy and
independent factual outcomes are explicitly NOT claimed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from paired_continuation import canon, digest

SCRIPTS=("paired_trial_prepare.py","paired_continuation.py",
         "paired_continuation_evaluator.py","paired_trial_replay.py")


def _digest_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _strict_execute(cmd, logfile, *, env):
    before=time.perf_counter_ns()
    with Path(logfile).open('x',encoding='utf-8') as f:
        completed=subprocess.run(cmd, cwd=str(Path(__file__).resolve().parent),
                                 env=env, stdin=subprocess.DEVNULL, stdout=f,
                                 stderr=subprocess.STDOUT, timeout=120, check=False)
    if completed.returncode:
        raise ValueError('subprocess failed: '+Path(logfile).name)
    return time.perf_counter_ns()-before


def run(folder,*, train_count=4096, future_count=512):
    folder=Path(folder).resolve()
    if not folder.is_dir() or any(folder.iterdir()):
        raise ValueError('new empty pre-existing output directory required')
    if type(train_count) is not int or not 128 <= train_count <= 8192 or type(future_count) is not int or not 32 <= future_count <= 2000:
        raise ValueError('bounded prospective experiment size')
    src=Path(__file__).resolve().parent
    host_env=dict(os.environ, OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1',
                  PYTHONDONTWRITEBYTECODE='1')
    def cmd(script,*args):
        return [sys.executable,str(src/script),*map(str,args)]
    start=time.perf_counter_ns()
    durations={}
    durations['prepare_ns']=_strict_execute(cmd('paired_trial_prepare.py','--output-dir',str(folder),
        '--train-count',train_count,'--future-count',future_count),folder/'prepare.log',env=host_env)
    source_names=['train_rows.json','train_worlds.json','future_1.json','future_2.json']
    source_sha={p:_digest_file(folder/p) for p in source_names}
    durations['fit_predict_ns']=_strict_execute(cmd('paired_continuation.py',
        '--train-rows',folder/'train_rows.json','--train-worlds',folder/'train_worlds.json',
        '--future-1',folder/'future_1.json','--future-2',folder/'future_2.json',
        '--seal',folder/'seal.json'),folder/'predict.log',env=host_env)
    seal=json.loads((folder/'seal.json').read_text(encoding='utf-8'))
    sealed_hash=digest(seal)
    if seal['actual_training_pairs'] != train_count*3 or seal['critic_parameters'] != 45:
        raise ValueError('actual learning did not cover fixed paired panel')
    scores={}
    for window,seed in (('future_1',919),('future_2',929)):
        durations[window+'_evaluate_ns']=_strict_execute(cmd('paired_continuation_evaluator.py',
             '--seal',folder/'seal.json','--seal-sha256',sealed_hash,
             '--future',folder/(window+'.json'),'--window',window,
             '--world-seed',seed,'--score',folder/(window+'.score.json')),
             folder/(window+'.log'),env=host_env)
        scored=json.loads((folder/(window+'.score.json')).read_text(encoding='utf-8'))
        if scored['sealed_prediction_sha256'] != sealed_hash or scored['future_public_sha256']!=seal['source_only_future_inputs_sha256'][window] or scored['n'] != future_count:
            raise ValueError('post-seal evaluation binding mismatch')
        scores[window]=scored
    if source_sha != {p:_digest_file(folder/p) for p in source_names} or sealed_hash != digest(json.loads((folder/'seal.json').read_text(encoding='utf-8'))):
        raise ValueError('source or sealed action drift during independent scoring')
    source_hashes={script:_digest_file(src/script) for script in SCRIPTS}
    panel={k:{"source_sha256":v['future_public_sha256'],"evaluated_cases":v['n'],
              "arms":v['arms'],"world_seed_after_seal":v['eval_world_seed_after_seal']}
           for k,v in scores.items()}
    report={"schema":"hepta.ndu-system2.paired-continuation-replay.v1",
            "predeclared_arbitrary_training_seed":801,
            "future_input_seeds":{"future_1":1801,"future_2":2801},
            "future_world_seed_scoring_only":{"future_1":919,"future_2":929},
            "source_file_bytes_sha256":source_sha,
            "code_file_bytes_sha256":source_hashes,
            "seal_sha256":sealed_hash,
            "training_pairs_actually_fitted":seal['actual_training_pairs'],
            "train_only_critic_weights_sha256":seal['trained_critic_weights_sha256'],
            "critic_train_cpu_ns":seal['actual_fit_cpu_ns'],
            "physical_work_wall_ns":time.perf_counter_ns()-start,
            "stage_wall_ns":durations,
            "prospective_results":panel,
            "p3_qualified":False,"p5_qualified":False,"p0_real_model_qualified":False,
            "underlying_task":"synthetic independent two-Bernoulli bits / one-step inspection",
            "real_pretrained_encoder_forward_count":0,
            "independent_natural_outcome_verified":False,
            "source_owner_signature_verified":False,
            "no_label_access_enforced_by_cryptographic_trust":False,
            "matched_physical_compute_established":False,
            "real_ndu_fbsde_solved":False,
            "production_accepted":False,"authority":"DENY_ALL"}
    with (folder/'report.json').open('x',encoding='utf-8') as f:
        f.write(canon(report)+'\n')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir',required=True)
    p.add_argument('--train-count',type=int,default=4096)
    p.add_argument('--future-count',type=int,default=512)
    args=p.parse_args()
    x=run(args.output_dir,train_count=args.train_count,future_count=args.future_count)
    print(canon({"report_path":str(Path(args.output_dir).resolve()/'report.json'),
                 "first_expected_utility":{k:{a:round(x['prospective_results'][k]['arms'][a]['expected_mean'],6) for a in ('no_search','exact_tree','learned_critic')} for k in ('future_1','future_2')},
                 "p3_qualified":False,"authority":"DENY_ALL"}))

if __name__=='__main__':
    main()
