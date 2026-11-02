"""Whole-child CPU/RSS records for a preregistered sealed CPU profile."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def freeze(out):
    out.mkdir(parents=True, exist_ok=False)
    dependencies = [p for name in ('hcsn_addressed_flow_20261101','hcsn_four_stage_flow_20261031','hcsn_distributional_v2','hcsn_missing_answers_20261101') for p in (ROOT/'experiments'/name).glob('*.py')]
    checkpoints = {str(p.relative_to(ROOT)):sha(p) for task in ('mqar','binding') for core in ('flow','diagonal') for p in [ROOT/f'experiments/hcsn_missing_answers_20261101/results/run001/fits/{task}_{core}_17/checkpoint.pt']}
    protocol = dict(schema='hcsn-sealed-cpu-envelope-r2.v1', source={p.name:sha(p) for p in (HERE/'worker.py', Path(__file__))},
        dependency_hashes={str(p.relative_to(ROOT)):sha(p) for p in dependencies},
        checkpoint_hashes=checkpoints,
        checkpoints='Unchanged R1 missing-trained seed17 MQAR/Binding Flow/Diagonal',
        cases=[dict(task=t, core=c, condition=condition, batch=b) for t in ('mqar','binding') for c in ('flow','diagonal') for condition,b in (('base',1),('base',24),('long_tokens_128',24))],
        modes=['no','yes'], memory_worker_limit_bytes=512*1024**2, supervisor_plus_worker_upper_limit_bytes=640*1024**2,
        data='Development namespace, seed923417; this is engineering compatibility/cost, not independent task-quality qualification',
        gates='All sealed cases must finish, exact output hashes and quality must match unsealed cases, worker RSS and conservative supervisor-plus-worker RSS bound satisfy limits',
        memory_scope='No parallel workers. ru_maxrss is worker lifetime highwater. Kernel prevents new process/task creation after seal, but initial descendants cannot be independently enumerated in this executor; full-family peak stays null. Sum of supervisor and worker maxima bounds those two measured processes only.',
        excludes=['GPU','device joules','filesystem page cache','production deployment ownership','arbitrary multi-process worker'],
        seccomp_api_source='https://github.com/seccomp/libseccomp/blob/main/include/seccomp.h.in')
    write(out/'PROTOCOL.json', protocol)


def run(out):
    protocol = json.loads((out/'PROTOCOL.json').read_text())
    if protocol['source'] != {p.name:sha(p) for p in (HERE/'worker.py', Path(__file__))}:
        raise RuntimeError('Source drift')
    if any(sha(ROOT/p)!=digest for p,digest in protocol['dependency_hashes'].items()):
        raise RuntimeError('Dependency drift')
    if any(sha(ROOT/p)!=digest for p,digest in protocol['checkpoint_hashes'].items()):
        raise RuntimeError('Checkpoint drift')
    rows = []
    for i, case in enumerate(protocol['cases']):
        for mode in protocol['modes']:
            name = f'case{i:02d}_{mode}'
            output = out/(name+'.json')
            command = [sys.executable,'-B','-m','experiments.hcsn_cpu_envelope_r2_20261101.worker','--out',str(output),'--sealed',mode]
            for key, value in case.items():
                command += ['--'+key,str(value)]
            begin = time.perf_counter()
            with (out/(name+'.stdout.log')).open('xb') as stdout, (out/(name+'.stderr.log')).open('xb') as stderr:
                child = subprocess.Popen(command,cwd=ROOT,stdout=stdout,stderr=stderr)
                _, status, usage = os.wait4(child.pid,0)
                code = os.waitstatus_to_exitcode(status); child.returncode = code
            row = dict(case=case,mode=mode,command=command,exit_code=code,whole_child_cpu_seconds=usage.ru_utime+usage.ru_stime,
                wall_seconds=time.perf_counter()-begin,wait4_peak_rss_bytes=usage.ru_maxrss*1024)
            if output.exists():
                record = json.loads(output.read_text());row['result']=record
                row['supervisor_plus_worker_rss_upper_bound_bytes']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024+usage.ru_maxrss*1024
            rows.append(row);write(out/(name+'.receipt.json'),row)
            print(json.dumps(dict(case=i, mode=mode, exit_code=code)),flush=True)
    checks=[]
    for index in range(len(protocol['cases'])):
        ordinary,sealed=rows[index*2:index*2+2]
        passed=ordinary['exit_code']==sealed['exit_code']==0
        if passed:
            a,b=ordinary['result'],sealed['result']
            expected_checkpoint=ROOT/f"experiments/hcsn_missing_answers_20261101/results/run001/fits/{sealed['case']['task']}_{sealed['case']['core']}_17/checkpoint.pt"
            passed=(a['output_sha256']==b['output_sha256'] and a['accuracy']==b['accuracy'] and b['sealed']['fork_denied']
                and a['checkpoint_sha256']==b['checkpoint_sha256']==protocol['checkpoint_hashes'][str(expected_checkpoint.relative_to(ROOT))]
                and sealed['wait4_peak_rss_bytes']<=protocol['memory_worker_limit_bytes']
                and sealed['supervisor_plus_worker_rss_upper_bound_bytes']<=protocol['supervisor_plus_worker_upper_limit_bytes'])
        checks.append(dict(case=index,passed=passed))
    write(out/'SUMMARY.json',dict(rows=rows,checks=checks,passed=all(r['passed'] for r in checks),
        whole_child_cpu_seconds=sum(r['whole_child_cpu_seconds'] for r in rows),energy_joules=None,production_activation=False,
        attributable_full_family_peak_rss_bytes=None,full_family_memory_gate=False,
        scope='Local guarded worker compatibility/RSS point profile only; no general full-family meter, measured energy or production qualification'))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=('freeze','run'));parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    freeze(args.out) if args.phase=='freeze' else run(args.out)
