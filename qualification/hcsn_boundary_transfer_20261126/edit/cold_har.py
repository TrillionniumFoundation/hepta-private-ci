"""Fresh process replay of one fixed arm through dev selection; no test outcomes are read."""
import argparse
import time
wall=time.perf_counter()
import json
from pathlib import Path
import numpy as np
import har_utility as h
p=argparse.ArgumentParser()
p.add_argument('arm',choices=['KEEP','inverse','same_BP','wide_BP','ridge'])
p.add_argument('folder',type=Path)
p.add_argument('out',type=Path)
args=p.parse_args()
x,y,ids=h.load_partition(args.folder,'train')
groups=np.unique(ids)
base,ad,de=[np.isin(ids,g) for g in [groups[:9],groups[9:15],groups[15:]]]
fit=h.experts(x[base],y[base])
pd,ref=h.observed(x[base],y[base],ids[base],fit)
parent,_=h.sweep(pd,h.OLD)
a,_=h.observed(x[ad],y[ad],ids[ad],fit,ref)
d,_=h.observed(x[de],y[de],ids[de],fit,ref)
tick=time.perf_counter()
if args.arm=='KEEP': pool=[]
elif args.arm=='inverse': pool=[h.sweep(a,h.NEW,parent)[0]]
elif args.arm in ('same_BP','wide_BP'):pool=h.bp(a,parent,args.arm=='wide_BP')
else:
    pool=[dict(kind='ridge',head=h.fit_ridge(a['phi'],a['gain'],pen),threshold=h.NEW+off)
          for pen in (.1,1,10) for off in (-.1,0.,.1)]
pos=h.select(d,parent,pool)
seconds=time.perf_counter()-tick
reference=json.loads((args.out/'seal.json').read_text())['policies'][args.arm]
if reference!=pos:
    raise ValueError('Cold replay changed the selected decision policy')
print(json.dumps(dict(arm=args.arm,fit_select_seconds=seconds,wall_before_process_exit=time.perf_counter()-wall,
                      identical_to_original=True)),flush=True)
