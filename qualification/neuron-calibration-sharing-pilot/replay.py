"""Arithmetic replay of a source-paired conditional contrast, not model inference."""
import hashlib,json
from pathlib import Path
import numpy as np
P=Path(__file__).resolve().parent;O=P/'observed';b=(O/'primary-source-contrast.json').read_bytes()
if hashlib.sha256(b).hexdigest()!='2e82afd67cf5557fde2d23f8b63fb3e4d3e777a5bc2f6841f81d9748a996b322':raise ValueError('source contrast drift')
d=np.array(json.loads(b)['values']);r=json.loads((O/'results.json').read_text())
if d.shape!=(640,) or not np.isfinite(d).all():raise ValueError('invalid contrast')
rng=np.random.default_rng(2026102550);boot=[d[rng.integers(0,640,size=640)].mean() for _ in range(10000)]
if not np.isclose(d.mean(),r['primary']['shared_minus_individual_nll'],atol=1e-15,rtol=0):raise ValueError('mean mismatch')
if not np.allclose(np.quantile(boot,[.025,.975]),r['primary']['conditional_source_bootstrap95'],atol=1e-15,rtol=0):raise ValueError('interval mismatch')
for arm,rs in r['perhead'].items():
 for key in ['nll','brier','ece10','accuracy','coverage','wrong_accepted_over_all']:
  if not np.isclose(np.mean([x[key] for x in rs]),r['summary'][arm][key],atol=1e-15,rtol=0):raise ValueError('summary mismatch')
p=r['constant_prior_metrics']
if p['accepted']!=0 or p['conditional_error'] is not None or p['conditional_error_wilson95'] is not None:raise ValueError('zero acceptance handling')
print('PASS:primary source-paired NLL/interval, per-head aggregate arithmetic andzero-acceptance null handling. Not model inference or fresh qualification.')
