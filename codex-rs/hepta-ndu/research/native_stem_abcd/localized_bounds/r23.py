"""R23 split-localized EXACT rational lower bound, never below the old valid bound."""
import centered as c
from fractions import Fraction as F
from heapq import heappop,heappush
import time,json,resource,hashlib
from pathlib import Path

def bound(box):
    primary=c.hybrid_lower(box)
    _,left,right=c.old.bisect(box)
    return max(primary,min(c.hybrid_lower(left),c.hybrid_lower(right)))

def cert(n,out,cap=4000):
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    cpu=time.process_time();wall=time.perf_counter()
    cand=tuple((F(v),F(v)) for v in c.old.CANDIDATES[n]);cl,cu=c.old.cost_bounds(cand)
    root=tuple((-F(3),F(3)) for _ in range(n))
    rl=bound(root)
    heap=[(float(rl),0,rl,root)];idx=0;count=0;pruned=0
    with (out/'SPLITS.jsonl').open('x') as f:
        while heap and count<cap:
            current=min([cl]+[h[2] for h in heap]);gap=max(F(0),cu-current)
            if gap<=F(1,100):break
            _,ident,low,box=heappop(heap)
            axis,left,right=c.old.bisect(box)
            children=[]
            for child in (left,right):
                idx+=1;lo=bound(child);keep=lo<cu
                if keep:heappush(heap,(float(lo),idx,lo,child))
                else:pruned+=1
                children.append(dict(id=idx,box=c.old.encode_box(child),lower=str(lo),kept=keep))
            f.write(json.dumps(dict(id=ident,lower=str(low),parent=c.old.encode_box(box),axis=axis,children=children)+'\n')
            count+=1
    with (out/'FRONTIER.jsonl').open('x') as f:
        for _,i,lo,box in sorted(heap,key=lambda z:z[1]):
            f.write(json.dumps(dict(id=i,lower=str(lo),box=c.old.encode_box(box)))+'\n')
    glo=min([cl]+[q[2] for q in heap]);gap=max(F(0),cu-glo)
    res=dict(n=n,mode='split_centered',cap=cap,splits=count,pruned=pruned,gap=str(gap),pass_threshold=gap<=F(1,100),cpu=time.process_time()-cpu,wall=time.perf_counter()-wall,peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.glob('*.jsonl')})
    (out/'CERTIFICATE.json').write_text(json.dumps(res,indent=2)+'\n')
    print(json.dumps(res),flush=True)
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--width',type=int,choices=(2,3,4),required=True);p.add_argument('--out',required=True);a=p.parse_args();cert(a.width,a.out)
