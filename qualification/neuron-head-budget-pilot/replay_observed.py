"""Frozen correctness arithmetic replay; no encoder, labels, or downloads."""
import hashlib,json
from pathlib import Path
import numpy as np
P=Path(__file__).resolve().parent
O=P/'observed' if (P/'observed').exists() else P
raw=(O/'correctness.json').read_bytes()
if hashlib.sha256(raw).hexdigest()!='2f7d48497daeee6ec51c374cc760813ae3f690df62d3d030ca45fe44992ec6a4':raise ValueError('correctness evidence drift')
d=json.loads(raw)['budgets'];r=json.loads((O/'results.json').read_text());delta={}
for n,heads in d.items():
 l=np.array(heads['logistic']);c=np.array(heads['centroid'])
 if l.shape!=(1600,) or c.shape!=(1600,) or not np.isin(l,[0,1]).all() or not np.isin(c,[0,1]).all():raise ValueError('bad binary outcomes')
 got=[l.mean(),c.mean(),l.mean()-c.mean()];want=[r['metrics'][n][k] for k in ['logistic_accuracy','centroid_accuracy','delta']]
 if not np.allclose(got,want,atol=1e-14,rtol=0):raise ValueError('accuracy mismatch')
 delta[n]=l-c
v={'endpoint_delta_2560':delta['2560'],'budget_gain_2560_minus_320':delta['2560']-delta['320']};boot={k:[] for k in v};rng=np.random.default_rng(2026102401)
for _ in range(10000):
 ix=rng.integers(0,1600,size=1600)
 for k,a in v.items():boot[k].append(a[ix].mean())
for k,a in v.items():
 if not np.isclose(a.mean(),r['primary'][k]['estimate'],atol=1e-14,rtol=0):raise ValueError('contrast mismatch')
 if not np.allclose(np.quantile(boot[k],[.0125,.9875]),r['primary'][k]['bootstrap97_5'],atol=1e-14,rtol=0):raise ValueError('interval mismatch')
if r['budget_related_benefit_demonstrated'] is not False:raise ValueError('joint claim incorrect')
print('PASS: 8 accuracies, 2 paired intervals, preserved false joint hypothesis; evidence arithmetic only, NOT model inference or qualification.')
