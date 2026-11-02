"""Frozen-grid development comparison; never changes the inherited gates."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import importlib
import numpy as np

ROOT = Path(__file__).resolve().parent


def run(output, witness_only, module_name):
    kernel = importlib.import_module(module_name)
    if output.exists():
        raise ValueError('Evidence exists')
    data = json.loads((ROOT / 'FROZEN_REFERENCE.json').read_text())
    source_path = Path(kernel.__file__)
    source = source_path.read_bytes()
    dependencies = {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in
                    (['frozen_kernel.py', 'float32_pair.py'] if module_name == 'compensated_kernel' else ['frozen_kernel.py'])}
    selected = data['rows']
    if witness_only:
        specs = [('maturity_0.01', 'log_distance', .0004600004758685827),
                 ('maturity_0.01', 'log_distance', .00034500000765547156),
                 ('maturity_0.1', 'asset', 87.50782775878906),
                 ('delta_0.2', 'log_distance', 0.), ('recovery_0', 'asset', 128.73773193359375)]
        selected = [r for r in selected if (r['case'], r['coordinate'], r['state']) in specs]
    models, rows = {}, []
    started = time.perf_counter()
    for r in selected:
        row = {k: r[k] for k in ('case', 'coordinate', 'state')}
        try:
            key = tuple(r['quantized_theta'])
            if key not in models:
                models[key] = kernel.build(key)
            y, j = models[key].state(r['state'], r['coordinate'])
            if not np.all(np.isfinite(y)) or not np.all(np.isfinite(j)):
                raise ValueError('Nonfinite financial output')
            ve = abs(y - r['reference']) / np.maximum(1., np.abs(r['reference']))
            je = abs(j - r['reference_jacobian']) / np.maximum(1., np.abs(r['reference_jacobian']))
            a, b = np.unravel_index(je.argmax(), je.shape)
            row.update(values=y.tolist(), jacobian=j.tolist(), value_errors=ve.tolist(),
                       value_error=float(ve.max()), jacobian_error=float(je.max()),
                       jacobian_worst=[data['output_order'][a], data['jacobian_columns'][b], float(j[a,b]), r['reference_jacobian'][a][b]],
                       passed=bool(ve.max() <= 8e-7 and je.max() <= 2e-5))
        except (ValueError, ArithmeticError) as error:
            row.update(error=str(error), passed=False)
        rows.append(row)
    cases={c:all(r['passed'] for r in rows if r['case']==c) for c in {r['case'] for r in rows}}
    summary=dict(rows=len(rows), passed_rows=sum(r['passed'] for r in rows), cases=cases,
                 passed_cases=sum(cases.values()), max_value_error=max(r.get('value_error',0) for r in rows),
                 max_jacobian_error=max(r.get('jacobian_error',0) for r in rows))
    result=dict(stage='development only, not qualification', arithmetic=getattr(kernel, 'ARITHMETIC', 'one float32 word per financial scalar/tangent'),
                reference_archive_sha256=data['original_archive_sha256'], source_sha256=hashlib.sha256(source).hexdigest(),
                source_file=source_path.name, dependencies_sha256=dependencies,
                gates={'value_scaled':8e-7,'jacobian_scaled':2e-5}, summary=summary, rows=rows,
                diagnostic_seconds=time.perf_counter()-started)
    if source_path.read_bytes()!=source or any(hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h for n,h in dependencies.items()):
        raise ValueError('Kernel changed during run')
    with output.open('x') as f:
        json.dump(result,f,indent=2,allow_nan=False);f.write('\n')
    print(json.dumps(summary,indent=2))
    if witness_only:
        print(json.dumps([{k:v for k,v in r.items() if k!='jacobian'} for r in rows],indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--witness-only',action='store_true')
    p.add_argument('--kernel',choices=['stable_kernel','compensated_kernel'],default='stable_kernel')
    a=p.parse_args();run(a.output,a.witness_only,a.kernel)
