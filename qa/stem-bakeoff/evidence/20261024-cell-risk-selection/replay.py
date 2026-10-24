"""Published-count/source-contrast arithmetic replay; NOT independent inference."""
import json,math,hashlib
from pathlib import Path
import numpy as np
from scipy.stats import binom
P=Path(__file__).resolve().parent
q=json.loads((P/'protocol.json').read_text());s=json.loads((P/'selection-freeze.json').read_text());r=json.loads((P/'results.json').read_text());c=json.loads((P/'source-contrasts.json').read_text())
assert hashlib.sha256((P/'protocol.json').read_bytes()).hexdigest()==s['protocol_sha256']
assert hashlib.sha256((P/'observed/source/run.py').read_bytes()).hexdigest()==s['driver_sha256']
assert hashlib.sha256((P/'selection-freeze.json').read_bytes()).hexdigest()==r['selection_freeze_sha256']
def upper(k,n,d):
 if n==0 or k==n:return 1.
 lo,hi=0.,1.
 for _ in range(100):
  mid=(lo+hi)/2
  if binom.cdf(k,n,mid)>d:lo=mid
  else:hi=mid
 return (lo+hi)/2
assert len(s['candidates'])==200
for a in s['candidates']:
 u=upper(a['wrong_accepted'],a['accepted'],.05/200)
 assert abs(u-a['upper'])<1e-10
 assert a['passes']==(a['accepted']>0 and u<=.05)
for chosen in s['selected']:
 passing=[a for a in s['candidates'] if a['seed']==chosen['seed'] and a['passes']]
 expected=min(passing,key=lambda a:(-a['accepted'],a['threshold'])) if passing else None
 assert chosen['calibration_record']==expected
 assert chosen['threshold']==(expected['threshold'] if expected else None)
 assert chosen['reject_all']==(expected is None)
assert sum(a['passes'] for a in s['candidates'])==r['passing_candidates']==0
assert sum(a['reject_all'] for a in s['selected'])==r['reject_all_heads']==20
for name,rr in r['per_head'].items():
 for a in rr:
  n=a['accepted'];k=a['wrong_accepted'];assert 0<=k<=n<=640
  assert a['coverage']==n/640 and a['wrong_over_all']==k/640
  assert a['conditional_error']==(k/n if n else None)
  if n:assert abs(a['descriptive_one_sided_CP95']-upper(k,n,.05))<1e-10
  else:assert a['descriptive_one_sided_CP95'] is None
 for key,field in [('mean_coverage','coverage'),('mean_wrong_over_all','wrong_over_all')]:assert abs(r['summary'][name][key]-np.mean([a[field] for a in rr]))<1e-14
x=np.array(c['values']);assert x.shape==(2,640)
rng=np.random.Generator(np.random.PCG64(q['bootstrap_seed']));b=np.array([x[:,rng.integers(0,640,640)].mean(1) for _ in range(q['bootstrap_replicates'])])
np.testing.assert_allclose(x.mean(1),r['descriptive_contrasts']['means'],atol=1e-14,rtol=0)
np.testing.assert_allclose(np.quantile(b,[.025,.975],axis=0).T,r['descriptive_contrasts']['conditional_source_bootstrap95'],atol=1e-14,rtol=0)
assert math.ceil(math.log(.05/200)/math.log(1-.05))==162
assert math.ceil(math.log(.05/200)/math.log(1-.01))==826
print('PASS: published-count bounds, choice, nulls and source-bootstrap arithmetic; no independent inference.')
