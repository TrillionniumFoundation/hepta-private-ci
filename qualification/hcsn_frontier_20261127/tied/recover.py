"""Recover the originally registered single-core run after its unrelated scheduling wait expired."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import time

ROOT=Path('/tmp/hepta-hcsn-flickr8k-c511-9c415')
BASE=ROOT/'tied_edit'
DRIVER=BASE/'src/run.py'
def sha(data):return hashlib.sha256(data).hexdigest()
def cpu_sample():
    m={}
    for ln in Path('/proc/stat').read_text().splitlines():
        ff=ln.split()
        if ff[0].startswith('cpu') and ff[0][3:].isdigit():
            vals=[int(v) for v in ff[1:9]]
            m[int(ff[0][3:])]=(sum(vals),sum(vals[3:5]))
    return m
def group(i):
    path=Path(f'/sys/devices/system/cpu/cpu{i}/topology/thread_siblings_list')
    values=set()
    for part in path.read_text().strip().split(','):
        if '-' in part:
            a,b=map(int,part.split('-'));values.update(range(a,b+1))
        else:values.add(int(part))
    return values
def choose():
    # CPU 15 and its sibling host the independent attention-free run.
    reserved={15,31};allowed=os.sched_getaffinity(0)
    for path in Path('/proc').glob('[0-9]*'):
        try:
            mask=os.sched_getaffinity(int(path.name))
            if len(mask)<=2:
                # Exclude ordinary application tasks permanently bound to a narrow mask.
                comm=(path/'comm').read_text().strip()
                if not comm.startswith(('kworker','ksoftirqd','migration','watchdog','cpuhp','idle_','rcu','irq/','ktimers')) and (path/'cmdline').read_bytes():
                    reserved.update(mask)
        except (OSError,ValueError):pass
    initial=cpu_sample();time.sleep(3);final=cpu_sample()
    busy={i:1-(final[i][1]-initial[i][1])/max(1,final[i][0]-initial[i][0]) for i in allowed}
    candidates=[i for i in allowed if not (group(i)&reserved) and group(i)<=allowed]
    if not candidates:raise RuntimeError('no free affinity group in observed allowed set')
    i=min(candidates,key=lambda i:(max(busy[j] for j in group(i)),sum(busy[j] for j in group(i)),i))
    return i,sorted(group(i)),{str(j):busy[j] for j in group(i)},sorted(reserved)
def main():
    original=DRIVER.read_bytes()
    assert sha(original)=='0050212ba02451c264e65c663fb2272b0ffdbcf7d93c03364d5143d20fc6b375'
    deps=[ROOT/'coco_restored/verification.json',ROOT/'caption_external20/seal.json']
    assert all(d.is_file() for d in deps)
    obsolete=ROOT/'coco_timed/results/summary.json'
    text=original.decode()
    clause=",ROOT/'coco_timed/results/summary.json'"
    assert text.count(clause)==1
    src=text.replace(clause,'')
    cpu,sib,busy,reserve=choose()
    os.sched_setaffinity(0,{cpu})
    os.environ['HEPTA_FLICKR_ROOT']=str(ROOT)
    rec=dict(original_control_exit='2026-11-27T21:12:12.793814+00:00',original_exit_code=1,
             reason='Expired 32000-second wait for an unrelated single-CPU table; two verified scientific prerequisites retained.',
             obsolete_file_present=obsolete.is_file(),driver_sha256=sha(original),effective_controller_sha256=sha(src.encode()),
             input_sha256={str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in deps},single_cpu=cpu,siblings=sib,
             before_launch_busy=busy,excluded_affinities=reserve,
             started=datetime.datetime.now(datetime.timezone.utc).isoformat())
    meta=BASE/'recovery_e0bf.json'
    if not meta.exists():meta.write_text(json.dumps(rec,indent=2)+'\n')
    print('recovering original tied_edit',rec,flush=True)
    exec(compile(src,str(DRIVER),'exec'),{'__name__':'__main__','__file__':str(DRIVER)})
if __name__=='__main__':main()
