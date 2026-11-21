#!/usr/bin/env python3
"""Account all child attempts, including one declared non-model timeout probe."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent


def write(name,value):
    with (ROOT/name).open('x') as f:
        json.dump(value,f,indent=2,allow_nan=False); f.write('\n')


def utc(): return datetime.now(timezone.utc).isoformat()


def execute(name,cmd,timeout,env):
    before=resource.getrusage(resource.RUSAGE_CHILDREN)
    started=time.perf_counter(); start_utc=utc(); timed_out=False
    with (ROOT/(name+'.stdout')).open('x') as out,(ROOT/(name+'.stderr')).open('x') as err:
        p=subprocess.Popen(cmd,env=env,stdout=out,stderr=err,start_new_session=True,cwd=str(ROOT))
        try: code=p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out=True; os.killpg(p.pid,signal.SIGKILL); code=p.wait()
    after=resource.getrusage(resource.RUSAGE_CHILDREN)
    return dict(name=name,started_utc=start_utc,ended_utc=utc(),exit_code=code,timed_out=timed_out,
        wall_timeout_seconds=timeout,wall_seconds=time.perf_counter()-started,
        child_user_cpu_seconds=after.ru_utime-before.ru_utime,
        child_system_cpu_seconds=after.ru_stime-before.ru_stime,
        child_cpu_seconds=(after.ru_utime+after.ru_stime)-(before.ru_utime+before.ru_stime),
        cumulative_children_peak_rss_bytes=after.ru_maxrss*1024,
        supervisor_cpu_seconds_at_return=time.process_time())


def main():
    p=json.loads((ROOT/'PROTOCOL_FROZEN.json').read_text())
    os.sched_setaffinity(0,set(p['cpu_affinity']))
    write('LAUNCH_SEAL.json',dict(utc=utc(),protocol_sha256=hashlib.sha256((ROOT/'PROTOCOL_FROZEN.json').read_bytes()).hexdigest(),
        worklist_sha256=p['worklist_sha256'],affinity=sorted(os.sched_getaffinity(0)),automatic_retry=False))
    env=os.environ.copy()
    env.update({'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1',
        'NUMEXPR_NUM_THREADS':'1','PYTHONHASHSEED':'0','PYTHONDONTWRITEBYTECODE':'1',
        'PYTHONPATH':p['runtime']+os.pathsep+p['old_root']+os.pathsep+str(Path(p['old_root'])/'upstream')})
    probe=execute('timeout_probe',[sys.executable,'-c','x=1\nwhile True:\n x=(x+1)%1000003\n'],
                  p['budget']['timeout_probe_wall_seconds'],env)
    probe.update(expected_failure=True,model_calls=0,
        failure_type='deliberate_non_model_wall_timeout',supervisor_cpu_seconds_at_launch=time.process_time())
    write('TIMEOUT_PROBE.json',probe)
    if not probe['timed_out'] or probe['exit_code']!=-signal.SIGKILL:
        raise ValueError('Timeout probe did not exercise kill/reap accounting')
    science=execute('science',[sys.executable,str(ROOT/'run_cost_study.py')],p['budget']['main_wall_seconds'],env)
    total=probe['child_cpu_seconds']+science['child_cpu_seconds']
    write('SUPERVISOR_COST.json',dict(schema='hepta.cost-supervision-receipt.v1',probe=probe,science=science,
        all_children_cpu_seconds=total,supervisor_cpu_seconds=time.process_time(),
        all_children_wall_seconds=probe['wall_seconds']+science['wall_seconds'],
        child_cpu_budget_seconds=p['budget']['all_children_cpu_seconds'],
        within_cpu_budget=total<=p['budget']['all_children_cpu_seconds'],
        completed=science['exit_code']==0,production_eligible=False,
        failure_scope='Includes expected timeout probe and any main failure; failed attempts are never erased or retried'))
    print(json.dumps({'science_exit_code':science['exit_code'],'all_children_cpu_seconds':total,
        'all_children_wall_seconds':probe['wall_seconds']+science['wall_seconds']}),flush=True)
    if science['exit_code']!=0 or total>p['budget']['all_children_cpu_seconds']: raise SystemExit(2)


def review():
    p=json.loads((ROOT/'PROTOCOL_FROZEN.json').read_text())
    os.sched_setaffinity(0,set(p['cpu_affinity']))
    env=os.environ.copy(); env.update({'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1',
        'MKL_NUM_THREADS':'1','NUMEXPR_NUM_THREADS':'1','PYTHONDONTWRITEBYTECODE':'1'})
    cost=execute('reader',[sys.executable,str(ROOT/'read_costs.py')],20,env)
    write('READER_COST.json',cost)
    original=json.loads((ROOT/'SUPERVISOR_COST.json').read_text())
    out=ROOT/'attempt001'
    choice=json.loads((out/'RESEARCH_CHOICE_SEALED.json').read_text())
    rows=[json.loads(s) for s in (out/'TIMINGS.jsonl').read_text().splitlines()]
    confirmation_cpu=sum(r['cpu_ns'] for r in rows if r['phase']=='confirmation')/1e9
    # Includes confirmation-loop bookkeeping, selection/receipt output, exit,
    # both supervisors and the independently observed reader's whole process.
    remainder=(original['science']['child_cpu_seconds']-choice['preconfirmation_process_cpu_seconds']-
        confirmation_cpu+original['supervisor_cpu_seconds']-choice['supervisor_cpu_seconds_at_launch']+
        cost['child_cpu_seconds']+time.process_time())
    total=original['all_children_cpu_seconds']+original['supervisor_cpu_seconds']+cost['child_cpu_seconds']+time.process_time()
    reserve_ok=remainder<=p['budget']['post_analysis_cpu_reserve_seconds']
    passed=cost['exit_code']==0 and reserve_ok and total<=p['budget']['all_children_cpu_seconds']
    write('FINAL_COST_ACCOUNTING.json',dict(schema='hepta.complete-cost-accounting.v1',
        utc=utc(),status='PASS' if passed else 'INVALID_OR_EXCEEDED_BUDGET',
        all_science_probe_reader_and_supervisor_cpu_seconds=total,
        full_science_and_probe_cpu_seconds=original['all_children_cpu_seconds'],
        initial_supervisor_cpu_seconds=original['supervisor_cpu_seconds'],
        independent_reader_cpu_seconds=cost['child_cpu_seconds'],
        review_supervisor_cpu_seconds=time.process_time(),
        confirmation_group_cpu_seconds=confirmation_cpu,
        actual_postcalibration_non_group_analysis_cpu_seconds=remainder,
        post_analysis_reserve_cpu_seconds=p['budget']['post_analysis_cpu_reserve_seconds'],
        analysis_reserve_satisfied=reserve_ok,
        all_cpu_budget_satisfied=total<=p['budget']['all_children_cpu_seconds'],
        research_choice=choice['decision'] if passed else 'STOP',
        research_choice_before_confirmation=choice['decision'],
        general_ndu_decision='KEEP_ORIGINAL_AND_STOP',production_eligible=False,
        precision_note='process rusage boundaries include all child work; final receipt emission is a small unmeasured supervisor tail, not an enforceable completion bound'))
    print(json.dumps({'status':'PASS' if passed else 'INVALID_OR_EXCEEDED_BUDGET',
        'all_cpu_seconds':total,'actual_post_analysis_cpu_seconds':remainder,
        'reserve_satisfied':reserve_ok}),flush=True)
    if not passed: raise SystemExit(2)


if __name__=='__main__':
    if sys.argv[1:]==['--review']: review()
    elif not sys.argv[1:]: main()
    else: raise SystemExit('Only --review is admitted')
