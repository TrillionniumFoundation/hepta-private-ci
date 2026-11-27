import argparse,json,os,signal,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--fit');a=p.parse_args()
root=Path(__file__).parent/'RUN_OUTPUT'/a.fit;root.mkdir()
start=float(os.environ['HCSN_PHASE_START'])
def finish(status):
    result={'status':status,'synthetic':True,'c2_calls':0,'torch_imports':0,
            'pid':os.getpid(),'affinity':sorted(os.sched_getaffinity(0)),
            'stop_request_present':(root/'STOP_REQUEST.json').exists(),
            'dispatch_elapsed_seconds':time.monotonic()-start}
    (root/'RESULT.json').write_text(json.dumps(result))
    raise SystemExit(0)
signal.signal(signal.SIGTERM,lambda s,f:finish('BUDGET_STOP'))
while True:
    for k in range(10000):
        v=k*k
    if a.fit=='fast' and time.monotonic()-start>.12:finish('TOY_COMPLETED')
    time.sleep(.01)
