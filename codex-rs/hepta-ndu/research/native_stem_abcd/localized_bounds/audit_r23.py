"""Read-only hash/census and sampled exact subtree replay for R23."""
import argparse,hashlib,json
from pathlib import Path
from fractions import Fraction as F
from r23 import bound
import centered as c

def verify(root):
 root=Path(root); rows=[]
 for n in (2,3,4):
  d=root/f'w{n}';a=json.loads((d/'CERTIFICATE.json').read_text())
  assert a['n']==n and a['cap']==4000
  line=(d/'SPLITS.jsonl').read_text().splitlines();front=(d/'FRONTIER.jsonl').read_text().splitlines()
  assert len(line)==a['splits'] and len(front)>0
  for name in ('SPLITS.jsonl','FRONTIER.jsonl'):
   assert hashlib.sha256((d/name).read_bytes()).hexdigest()==a['files'][name]
  records=[json.loads(x) for x in line]
  chosen=sorted(set([0,len(records)-1]+list(range(0,len(records),max(1,len(records)//100)))))
  for j in chosen:
   r=records[j];box=c.old.decode_box(r['parent']);k,l,rr=c.old.bisect(box)
   assert r['axis']==k and c.old.encode_box(l)==r['children'][0]['box'] and c.old.encode_box(rr)==r['children'][1]['box']
   assert F(r['lower'])==bound(box)
   for kid,child in zip((l,rr),r['children']):
    assert F(child['lower'])==bound(kid)
  upper=c.old.cost_bounds(tuple((F(s),F(s)) for s in c.old.CANDIDATES[n]))[1]
  gl=min([upper]+[F(json.loads(x)['lower']) for x in front]);gap=max(F(0),upper-gl)
  assert gap==F(a['gap'])
  rows.append(dict(n=n,splits=len(line),frontier=len(front),sample_replayed=len(chosen),gap=float(gap),qualified=a['pass_threshold'],cpu=a['cpu']))
 return rows
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',required=True);a=p.parse_args();print(json.dumps(verify(a.root),indent=2))
