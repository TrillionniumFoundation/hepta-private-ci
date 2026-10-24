"""Recorded correctness replay only, not new inference or qualification."""
import hashlib,json
from pathlib import Path
import numpy as np
P=Path(__file__).resolve().parent;raw=(P/'observed/correctness.json').read_bytes()
if hashlib.sha256(raw).hexdigest()!='f67ba19aefb49b4519f8f80e6cf9d9716fb6395bad379b791aee0aa4a3b1f553':raise ValueError('correctness drift')
d=json.loads(raw);r=json.loads((P/'observed/results.json').read_text());l=np.array(d['logistic']);c=np.array(d['centroid'])
if l.shape!=(20,3,512) or c.shape!=l.shape or not np.isin(l,[0,1]).all() or not np.isin(c,[0,1]).all():raise ValueError('invalid outcomes')
a=l-c;g=a[:,-1,:]-a[:,0,:];v=g.mean(0);rng=np.random.default_rng(2026102450)
boot=[v[rng.integers(0,512,size=512)].mean() for _ in range(10000)]
if not np.isclose(v.mean(),r['primary']['mean_relative_gain1280_minus320'],atol=1e-14,rtol=0):raise ValueError('primary mismatch')
if not np.allclose(np.quantile(boot,[.025,.975]),r['primary']['conditional_source_bootstrap95'],atol=1e-14,rtol=0):raise ValueError('CI mismatch')
for i,seed in enumerate(d['seeds']):
 for j,n in enumerate(d['budgets']):
  row=next(x for x in r['records'] if x['seed']==seed and x['budget']==n)
  if not np.allclose([l[i,j].mean(),c[i,j].mean(),a[i,j].mean()],[row[k] for k in ['logistic_accuracy','centroid_accuracy','delta']],atol=1e-14,rtol=0):raise ValueError('accuracy mismatch')
sign=[int((g.mean(1)>0).sum()),int((g.mean(1)==0).sum()),int((g.mean(1)<0).sum())]
if sign!=r['positive_zero_negative_seed_gains']:raise ValueError('sign counts mismatch')
print('PASS:120 accuracies, primary conditional-source interval and14/4/2 seed signs. Arithmetic replay only; not fresh qualification.')
