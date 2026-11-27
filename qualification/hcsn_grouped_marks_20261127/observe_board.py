"""Auxiliary NVIDIA board observation linked to the immutable fit controller ledger."""
import ctypes as C
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time


class Utilization(C.Structure):
    _fields_=[('gpu',C.c_uint),('memory',C.c_uint)]


def main():
    root=Path(os.environ['HCSN_GROUPED_STUDY']).resolve()
    out=root/'board_observations';out.mkdir(exist_ok=True)
    lock=(out/'record.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    nv=C.CDLL('libnvidia-ml.so.1');assert nv.nvmlInit_v2()==0
    device=C.c_void_p();assert nv.nvmlDeviceGetHandleByIndex_v2(0,C.byref(device))==0
    def scalar(name,*args):
        v=C.c_uint();code=getattr(nv,name)(device,*args,C.byref(v));return v.value if code==0 else None
    offset=0;active=None;ledger=root/'attempts.jsonl';last_mtime=None;last_apps=None
    started=time.time();iteration=0
    with (out/'board.jsonl').open('a',buffering=1) as stream,(out/'observed_checkpoints.jsonl').open('a',buffering=1) as checkpoints:
        while time.time()-started<20*3600:
            begin=time.monotonic()
            if ledger.exists():
                with ledger.open('rb') as entries:
                    entries.seek(offset)
                    for raw in entries:
                        if not raw.endswith(b'\n'):break
                        e=json.loads(raw);offset+=len(raw);active=e['argv'] if e['stage']=='begin' else None
            u=Utilization();valid=nv.nvmlDeviceGetUtilizationRates(device,C.byref(u))==0
            watts=scalar('nvmlDeviceGetPowerUsage')
            if iteration%10==0:
                # Retain only aggregate counts of compute contexts and whether they run from this study's source directory.
                try:
                    p=subprocess.run(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=3)
                    lines=[int(x.strip()) for x in p.stdout.splitlines() if x.strip().isdigit()]
                    if p.returncode==0:
                        member=0;unknown=0
                        for pid in lines:
                            try:member+=Path(os.readlink(f'/proc/{pid}/cwd')).resolve()==root/'src'
                            except OSError:unknown+=1
                        last_apps={'count':len(lines),'study':member,'unknown':unknown,'epoch':time.time()}
                except (OSError,subprocess.TimeoutExpired):last_apps=None
            row={'epoch':time.time(),'monotonic':time.monotonic(),'device_index':0,'board_w':None if watts is None else watts/1000,
                 'gpu_busy_percent':u.gpu if valid else None,'memory_busy_percent':u.memory if valid else None,
                 'temperature_c':scalar('nvmlDeviceGetTemperature',0),'sm_clock_mhz':scalar('nvmlDeviceGetClockInfo',1),
                 'activity':active,'compute_context_sample':last_apps}
            stream.write(json.dumps(row,separators=(',',':'))+'\n')
            if active and len(active)==5 and active[0]=='fit.py':
                _,phase,arm,seed,rate=active
                history=root/'runs'/phase/f'{arm}-{seed}-{float(rate):.4g}'/'history.json'
                if history.is_file():
                    stat=history.stat();key=(str(history),stat.st_mtime_ns)
                    if key!=last_mtime:
                        j=json.loads(history.read_text());rec=j['history'][-1];last_mtime=key
                        event={'epoch_file_updated':stat.st_mtime_ns/1e9,'epoch_seen':time.time(),'activity':active,
                               'stage_s':rec['stage_s'],'train_s':rec['train_s'],'dev_s':rec['dev_s'],'steps':rec['steps']}
                        checkpoints.write(json.dumps(event,separators=(',',':'))+'\n')
            if (root/'final.json').is_file():break
            iteration+=1;time.sleep(max(0.,1-(time.monotonic()-begin)))
    nv.nvmlShutdown()


if __name__=='__main__':main()
