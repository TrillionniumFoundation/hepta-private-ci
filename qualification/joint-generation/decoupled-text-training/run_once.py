"""Complete-child accounting under a NEW synthetic-only lock, never the old lock."""
import fcntl
import hashlib
import json
import os
import pathlib
import resource
import signal
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent
LOCK = pathlib.Path('/workspace/shared/rgb-class-preservation-20261030/benchmark.lock')


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n')


def child(command, out, stem, cpu_limit, wall_limit):
    def limits():
        os.setsid()
        os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
        resource.setrlimit(resource.RLIMIT_CPU,(cpu_limit,cpu_limit))
        resource.setrlimit(resource.RLIMIT_AS,(1024**3,1024**3))
        resource.setrlimit(resource.RLIMIT_FSIZE,(64*1024**2,64*1024**2))
    env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',PYTHONDONTWRITEBYTECODE='1')
    started=time.monotonic()
    with (out/(stem+'.stdout')).open('xb') as stdout, (out/(stem+'.stderr')).open('xb') as stderr:
        process=subprocess.Popen(command,stdout=stdout,stderr=stderr,env=env,preexec_fn=limits)
        def timeout(signum,frame):
            os.killpg(process.pid,signal.SIGKILL)
        signal.signal(signal.SIGALRM,timeout); signal.alarm(wall_limit)
        pid,status,usage=os.wait4(process.pid,0)
        signal.alarm(0)
        process.returncode=os.waitstatus_to_exitcode(status)
    return {'pid':pid,'exit_code':process.returncode,'cpu_seconds':usage.ru_utime+usage.ru_stime,
            'wall_seconds':time.monotonic()-started,'maxrss_kib':usage.ru_maxrss,'complete_wait4':True}


def main(output):
    start=time.process_time(); wall=time.monotonic()
    out=pathlib.Path(output); out.mkdir(exist_ok=False)
    LOCK.parent.mkdir(parents=True,exist_ok=True)
    with LOCK.open('a+') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            write(out/'COST.json',{'status':'LOCK_REFUSED_NO_NUMERICAL_WORK','lock':str(LOCK)})
            raise SystemExit(3)
        frozen=json.loads((ROOT/'FREEZE.json').read_text())
        for name,sha in frozen['files'].items():
            if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=sha: raise ValueError('source mismatch')
        tests=child([sys.executable,'-I','-B','-W','error',str(ROOT/'test_mechanism.py')],out,'tests',15,20)
        write(out/'TEST_COST.json',tests)
        if tests['exit_code'] != 0: raise SystemExit(2)
        science=child([sys.executable,'-I','-B','-W','error',str(ROOT/'run_experiment.py'),str(out/'science')],out,'science',380,max(1,int(590-(time.monotonic()-wall))))
        total=tests['cpu_seconds']+science['cpu_seconds']
        record={'schema':'rgb-complete-child-cost-v1','tests':tests,'science':science,'complete_child_cpu':total,
                'supervisor_cpu_observed_prefix':time.process_time()-start,'supervisor_final_tail':'UNKNOWN_NOT_ZERO',
                'wall_observed_prefix':time.monotonic()-wall,'lock':str(LOCK),'scope':'NEW_SYNTHETIC_ONLY_NOT_ROUND04',
                'historical_research_review_publication_cpu':'SEPARATE_UNKNOWN_NOT_ZERO'}
        if science['exit_code']==0:
            result=json.loads((out/'science/RESULT.json').read_text())
            prefixes={name:row['observed_complete_prefix'] for name,row in result['costs'].items()}
            # Full waited process covers interpreter/import/checkpoint/report/tail.
            remainder=total-sum(prefixes.values())
            if remainder < -1e-6: raise ValueError('CPU allocation exceeds full child cost')
            record['complete_method_child_cpu']={name:value+max(0.,remainder)/8 for name,value in prefixes.items()}
            record['standalone_conservative_method_cpu']={name:(row['base_cpu_allocation']*4 + row['adaptation_checkpoint_cpu'] + row['evaluation_cpu'] + row['shared_cpu_allocation']*8 + row['worker_other_prefix_allocation']*8 + max(0.,remainder)) for name,row in result['costs'].items()}
            record['standalone_cost_note']='Full own-seed base plus ALL shared preparation/test/import/report/tail charges per method; conservative attribution, not measured separate-process standalone latency. Campaign amortized allocation kept separately.'
            record['equal_cap_seconds_per_method']=60
            record['budget_pass']=(total<=400 and all(v<=60 for v in record['standalone_conservative_method_cpu'].values())
                                   and time.monotonic()-wall<=600)
        else: record['budget_pass']=False
        write(out/'COST.json',record)
        print(json.dumps(record),flush=True)
        if science['exit_code']!=0 or not record['budget_pass']: raise SystemExit(2)


if __name__=='__main__': main(sys.argv[1])
