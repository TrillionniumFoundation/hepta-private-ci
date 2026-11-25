"""Supervise resident CPU inference workers with *external* wall deadlines.

This is opt-in infrastructure for a NEW experiment protocol, not a retroactive
change to the frozen 2026-10-22 pilot. A blocking native encoder cannot be
preempted safely by Python timers inside its worker; on deadline, the parent
kills the worker and records consumed wall time as incompletely attributed work.
Resident initialization/restarts are separately reported, not free resources.
"""
import multiprocessing
from multiprocessing.connection import wait
import time


def _serve(conn, initializer, initargs, task_fn):
    try:
        started = time.perf_counter()
        initializer(*initargs)
        conn.send(('ready', time.perf_counter()-started, None))
    except BaseException as error:
        conn.send(('init_error', 0., repr(error)))
        conn.close()
        return
    try:
        while True:
            message = conn.recv()
            if message is None:
                return
            job_id, job = message
            conn.send(('started', job_id, time.perf_counter()))
            try:
                result = task_fn(job)
            except BaseException as error:
                conn.send(('failed', job_id, time.perf_counter(), repr(error)))
            else:
                conn.send(('done', job_id, time.perf_counter(), result))
    except (EOFError, BrokenPipeError, OSError):
        return
    finally:
        conn.close()


class HardBudgetPool:
    """Run input-ordered jobs across resident workers with process kill + restart.

    Yields (job_index, result_or_none, receipt). A timeout/worker failure must
    stay in the scored denominator; caller builds a zero-quality failure record.
    The supplied task function and initializer must be top-level picklable callables.
    """
    def __init__(self, initializer, initargs, task_fn, workers=2,
                 init_timeout=180., kill_grace=0.1):
        if not isinstance(workers, int) or workers < 1 or init_timeout <= 0 or kill_grace < 0:
            raise ValueError('invalid worker count or supervisor timings')
        self.initializer, self.initargs, self.task_fn = initializer, initargs, task_fn
        self.max_workers = workers
        self.init_timeout, self.kill_grace = float(init_timeout), float(kill_grace)
        self.ctx = multiprocessing.get_context('spawn')
        self.residents = {}
        self.initializations = []

    def _stop(self, item):
        if not item:
            return
        proc, conn = item['process'], item['conn']
        if proc.is_alive():
            proc.terminate()
            proc.join(self.kill_grace)
            if proc.is_alive():
                proc.kill()
                proc.join(self.kill_grace)
        if proc.is_alive():
            raise RuntimeError('cannot hard-stop unresponsive worker')
        conn.close()
        proc.join(timeout=0)

    def _spawn(self, slot):
        local, remote = self.ctx.Pipe()
        proc = self.ctx.Process(target=_serve, args=(remote,self.initializer,self.initargs,self.task_fn))
        proc.daemon = True
        proc.start()
        remote.close()
        if not local.poll(self.init_timeout):
            self._stop({'process':proc,'conn':local})
            raise RuntimeError('resident initializer exceeded its separate timeout')
        try:
            name, seconds, detail = local.recv()
        except EOFError:
            self._stop({'process':proc,'conn':local})
            raise RuntimeError('resident initializer crashed without a receipt')
        if name != 'ready':
            self._stop({'process':proc,'conn':local})
            raise RuntimeError('resident initializer failed: '+str(detail))
        resident={'worker_pid':proc.pid,'load_seconds':seconds,'slot':slot}
        self.initializations.append(resident)
        self.residents[slot]={'process':proc,'conn':local,'resident':resident,'job':None}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        for slot,item in list(self.residents.items()):
            self._stop(item)
            del self.residents[slot]

    def run(self, jobs, budget):
        if not isinstance(budget, (int,float)) or not 0 < budget < float('inf'):
            raise ValueError('budget must be positive, finite wall seconds')
        jobs = list(jobs)
        if not jobs:
            return
        try:
            for slot in range(min(self.max_workers,len(jobs))):
                self._spawn(slot)
            next_job, completed = 0, 0
            while completed < len(jobs):
                # Never perform blocking model initialization while another
                # resident is serving a budgeted episode.
                if not any(item['job'] is not None for item in self.residents.values()):
                    for slot in range(min(self.max_workers,len(jobs))):
                        if slot not in self.residents and next_job < len(jobs):
                            self._spawn(slot)
                for slot,item in self.residents.items():
                    if item['job'] is None and next_job < len(jobs):
                        started = time.perf_counter()
                        item['conn'].send((next_job,jobs[next_job]))
                        item['job']={'index':next_job,'dispatched':started,'started':None}
                        next_job += 1
                active=[i for i in self.residents.values() if i['job'] is not None]
                if not active:
                    raise RuntimeError('supervisor lost all assigned workers')
                now=time.perf_counter()
                near=min(item['job']['dispatched'] + budget for item in active)
                ready=wait([item['conn'] for item in active],timeout=min(0.02,max(0,near-now)))
                finished=[]
                for conn in ready:
                    item=next(i for i in active if i['conn'] is conn)
                    job=item['job']
                    try:
                        kind,index,at,*other=conn.recv()
                    except EOFError:
                        finished.append((job['index'],None,'worker_crashed',time.perf_counter()-job['dispatched'],item,None))
                        continue
                    if index!=job['index']:
                        raise RuntimeError('supervisor message/job identity mismatch')
                    if kind=='started':
                        job['started']=at
                        continue
                    if kind not in ('done','failed'):
                        raise RuntimeError('unrecognized resident reply')
                    elapsed=max(time.perf_counter(),at)-job['dispatched']  # Charge result serialization and transport.
                    status='hard_timeout' if elapsed>budget else ('completed' if kind=='done' else 'worker_failed')
                    value=other[0] if kind=='done' and status=='completed' else None
                    finished.append((index,value,status,elapsed,item,other[0] if kind=='failed' else None))
                # Check elapsed deadlines even when the worker is blocked in native code.
                for item in active:
                    if any(x[4] is item for x in finished):
                        continue
                    job=item['job']
                    if time.perf_counter() - job['dispatched'] >= budget:
                        finished.append((job['index'],None,'hard_timeout',
                                         time.perf_counter()-job['dispatched'],item,None))
                for index,value,status,elapsed,item,error_detail in finished:
                    slot=item['resident']['slot']
                    resident=item['resident']
                    restart=status in ('hard_timeout','worker_crashed')
                    other_active=any(other is not item and other['job'] is not None
                                     for other in self.residents.values())
                    restart_now=restart and not other_active and next_job < len(jobs)
                    if restart:
                        self._stop(item)
                        elapsed=max(elapsed,time.perf_counter() - item['job']['dispatched'])
                        del self.residents[slot]
                    else:
                        item['job']=None
                    yield index,value,{'status':status,'measured_wall_seconds':max(elapsed,1e-9),
                                       'resident':resident,'worker_killed':restart,
                                       'worker_restarted':restart_now,
                                       'internal_call_counts_complete':status=='completed',
                                       'error_detail':error_detail}
                    completed += 1
                    if restart_now:
                        self._spawn(slot)
        finally:
            self.close()


def interrupted_episode(job, receipt, identities, model_revision):
    """Scoreable non-success receipt; no false zero-cost inference or fabricated PNG.

    A killed worker cannot return complete native-call counts or component spans.
    Charge all supervisor-observed wall to unallocated_failure, include all
    expected cost components with explicit measurement completeness flags, and
    retain the original denominator with a zero-quality termination.
    """
    observation, method, seed, risk_weight, _partner, budget = job
    duration = receipt['measured_wall_seconds']
    reason = receipt['status']
    if reason == 'completed' or not 0 < duration < float('inf'):
        raise ValueError('only measured interrupted jobs admit a failure receipt')
    costs = [{'component':component,'calls':0,'wall_seconds':0.}
             for component in ('encoder','backbone','cell','controller','critic',
                               'verifier','render','communication')]
    costs.append({'component':'unallocated_failure','calls':1,'wall_seconds':duration,
                  'internal_model_calls_unknown':True})
    return {'task_id':observation['task_id'],'method':method,'seed':seed,
        'risk_weight':risk_weight,'budget_cap':budget,'budget_unit':'wall_seconds',
        'termination':reason,'text':'','boxes':[],'label':observation['target_category'],
        'artifact_path':None,'artifact_sha256':None,'controls':[],'failures':[reason],
        'costs':costs,'model_revision':model_revision,
        'policy_version':f'hepta-grounded-v2-hard-budget/{method}',
        'actual_input_image_sha256':observation['image_sha256'],
        'source_image_sha256':observation['image_sha256'],
        'actual_wall_seconds':duration,'actual_cpu_seconds':None,
        'ledger_minus_wall_seconds':0.,'generated_tokens':None,
        'token_measurement_complete':False,'internal_model_calls_complete':False,
        'failed_work_detail':'process killed or failed; native calls/cost split unobservable; wall charged to unallocated_failure',
        'candidates':[],'trajectory':None,'checkpoint_identities':identities,
        'resident_initialization':receipt['resident'],'supervisor':receipt,
        'verification':{'quality':0.0,'severe_probability':None},
        'generated_for_verifier':{'boxes':[],'tokens':[],'controls':[],'termination':reason},
        'accounting':'parent-measured wall through kill; no internal-call attribution; initialization separate'}
