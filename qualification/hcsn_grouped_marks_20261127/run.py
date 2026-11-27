"""Interleave registered fits, seal choices, then hand each scored model to a cold process."""
import fcntl
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
from fit import ARMS, CONFIRM, CONTROL_ORDER, RATES, ROOT, SRC, TUNING, json_file, run_path, sha, write_json


def device_snapshot():
    exe = shutil.which('nvidia-smi')
    if exe is None:
        return {}
    gpu = subprocess.run([exe, '--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,power.draw',
                          '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=20)
    jobs = subprocess.run([exe, '--query-compute-apps=process_name,used_memory', '--format=csv,noheader,nounits'],
                          capture_output=True, text=True, timeout=20)
    # Keep executable names and memory usage only; do not retain desktop command-line options.
    process_kinds = []
    for entry in jobs.stdout.splitlines():
        command, separator, memory = entry.rpartition(',')
        if separator and command.strip():
            process_kinds.append({'program':Path(command.strip().split()[0]).name, 'used_MiB':memory.strip()})
    return {'gpu_sample':gpu.stdout.strip().splitlines(),'compute_processes':process_kinds,
            'quantity_order':['model','temperature_C','utilization_percent','memory_MiB','board_power_W']}


def scientific_child(argv):
    env = {**os.environ, 'OMP_NUM_THREADS':'1', 'OPENBLAS_NUM_THREADS':'1', 'MKL_NUM_THREADS':'1', 'PYTHONUNBUFFERED':'1'}
    log = ROOT/'worker.log'
    start = time.time()
    attempts = ROOT/'attempts.jsonl'
    with attempts.open('a') as h:
        h.write(json.dumps({'stage':'begin','argv':argv,'epoch':start,'device':device_snapshot()})+'\n')
    with log.open('a') as stream:
        result = subprocess.run([sys.executable,*argv],cwd=SRC,env=env,stdout=stream,stderr=subprocess.STDOUT)
    with attempts.open('a') as h:
        h.write(json.dumps({'stage':'end','argv':argv,'epoch':time.time(),'started_epoch':start,'elapsed':time.time()-start,'exit':result.returncode,'device':device_snapshot()})+'\n')
    if result.returncode:
        raise RuntimeError(f"Scientific process ended with status {result.returncode}: {argv}")


def seal_once(path,record):
    if path.exists():
        assert json_file(path)==record
    else:
        write_json(path,record)


def fitting(phase):
    seeds = TUNING if phase=='tune' else CONFIRM
    fixed = json_file(ROOT/'tuning_seal.json')['rates'] if phase=='confirm' else None
    for seed in seeds:
        rng=np.random.default_rng(seed)
        settings = [(name, lr) for name in ARMS for lr in (RATES if fixed is None else [fixed[name]])]
        rng.shuffle(settings)
        for arm,rate in settings:
            d=run_path(phase,arm,seed,rate)
            if (d/'complete.json').exists():
                rec=json_file(d/'complete.json')
                assert rec['history_sha256']==sha(d/'history.json')
                assert rec['contract']['gallery']==sha(ROOT/'gallery/manifest.json')
                continue
            scientific_child(['fit.py',phase,arm,str(seed),str(rate)])
            assert (d/'complete.json').exists()


def choose_rates():
    # Ties favor the designated middle rate, then the lower rate.
    order=(.0005,.0002,.001)
    values={};rates={};minima={}
    for arm in ARMS:
        scores={}
        for lr in order:
            scores[str(lr)]=float(np.mean([json_file(run_path('tune',arm,seed,lr)/'complete.json')['best']['nll'] for seed in TUNING]))
        best=min(order,key=lambda lr: scores[str(lr)])
        rates[arm]=best;values[arm]=scores;minima[arm]=scores[str(best)]
    control=min(CONTROL_ORDER,key=lambda c:minima[c])
    anchor=minima[control]+.04
    record={'registrations':sha(SRC/'PROTOCOL.md'),'tuning_seeds':list(TUNING),'candidate_losses':values,
            'rates':rates,'control':control,'targets':[anchor,anchor-.04,anchor+.04],
            'data':sha(ROOT/'gallery/manifest.json'),'tuning_receipts':{}}
    for arm in ARMS:
        for seed in TUNING:
            for lr in RATES:
                d=run_path('tune',arm,seed,lr)
                record['tuning_receipts'][d.name]=sha(d/'complete.json')
    assert len(record['tuning_receipts'])==36
    seal_once(ROOT/'tuning_seal.json',record)


def seal_confirmations():
    tuning=json_file(ROOT/'tuning_seal.json'); assignments={}
    for arm in ARMS:
        for seed in CONFIRM:
            d=run_path('confirm',arm,seed,tuning['rates'][arm])
            rec=json_file(d/'complete.json')
            assert rec['contract']['targets']==tuning['targets'] and rec['history_sha256']==sha(d/'history.json')
            unique={}
            for target,entry in [('best',rec['best']),*rec['first'].items()]:
                assert sha(d/entry['file'])==entry['sha256']
                unique[target]={'state':entry['sha256'],'name':entry['file'],'stage':entry['stage_s'],
                    'seconds':entry['train_s']+entry['dev_s'],'nll':entry['nll'],'steps':entry['steps'],'tokens':entry['tokens']}
            assignments[d.name]={'complete':sha(d/'complete.json'),'assignment':unique}
    assert len(assignments)==72
    sources={n:sha(SRC/n) for n in ('fit.py','model.py','parent_cell.py','grouped_router.py','run.py','cold.py','analyze.py','qualify.py','PROTOCOL.md')}
    seal_once(ROOT/'evaluation_seal.json',{'tuning':sha(ROOT/'tuning_seal.json'),'sources':sources,
        'manifest':sha(ROOT/'gallery/manifest.json'),'assignments':assignments,'all_sources_frozen':True})


def main():
    ROOT.mkdir(exist_ok=True,parents=True)
    lock=(ROOT/'controller.lock').open('a'); fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    bound=ROOT/'source_seal.json'
    names=('PROTOCOL.md','grouped_router.py','legacy_cohort_reference.py','acquire.py','model.py','parent_cell.py',
           'fit.py','qualify.py','run.py','cold.py','analyze.py')
    seal_once(bound,{n:sha(SRC/n) for n in names})
    if not (ROOT/'gallery/manifest.json').exists():raise RuntimeError('New cohorts are not frozen')
    if not (ROOT/'gpu_qualification.json').exists():
        scientific_child(['qualify.py','cuda',str(ROOT/'gpu_qualification.json')])
    fitting('tune');choose_rates()
    fitting('confirm');seal_confirmations()
    tuning=json_file(ROOT/'tuning_seal.json')
    for arm in ARMS:
        for seed in CONFIRM:
            d=run_path('confirm',arm,seed,tuning['rates'][arm])
            if not (d/'cold.json').exists():scientific_child(['cold.py',arm,str(seed)])
    scientific_child(['analyze.py'])
    print('completed',sha(ROOT/'final.json'),flush=True)


if __name__=='__main__':
    main()
