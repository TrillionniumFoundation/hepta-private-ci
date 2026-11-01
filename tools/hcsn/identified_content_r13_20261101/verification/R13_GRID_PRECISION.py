"""Frozen DS financial backend on every center of all eight fitted R13 models.

This extends finite-point financial-kernel evidence, not whole-SNN precision.
It neither changes the frozen kernel nor reruns any task confirmation.
"""

import gzip
import hashlib
import json
from pathlib import Path
import sys
import time
import warnings

import numpy as np

ROOT=Path(__file__).resolve().parent
R13=ROOT.parent
sys.path.insert(0,str(R13/'precision'))
import ds_kernel
from fresh import reference_tools,check_freeze
from development import error


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(suffix,payload):
    path=ROOT/('R13_GRID_PRECISION.'+suffix)
    if path.exists():
        raise FileExistsError(f'Refusing to overwrite {path}')
    raw=(json.dumps(payload,indent=2,allow_nan=False)+'\n').encode()
    path.write_bytes(gzip.compress(raw,mtime=0) if suffix.endswith('.gz') else raw)


def main():
    ds_freeze=check_freeze()
    task_freeze=json.loads((R13/'evidence/FREEZE.json').read_text())
    protocol=json.loads((R13/'PROTOCOL.json').read_text())
    fixtures=[]
    fit_hashes={}
    for seed in protocol['seeds']:
        name=f'fits/{seed}_hx_distribution.json'
        path=R13/'evidence'/name
        fit_hashes[name]=sha(path)
        assert fit_hashes[name]==task_freeze['fit_sha256'][name]
        fit=json.loads(path.read_text())
        theta=fit['shared_model']['theta']
        centers=fit['shared_model']['centers']
        assert len(centers)==56 and len(theta)==9
        for i,x in enumerate(centers):
            fixtures.append(dict(seed=seed,index=i,theta_original=theta,state_original=x))
    specification=dict(ds_freeze_sha256=ds_freeze,task_freeze_sha256=sha(R13/'evidence/FREEZE.json'),
        script_sha256=sha(Path(__file__)),fit_sha256=fit_hashes,rows=len(fixtures),
        reference='Unchanged 80-digit literal R11 A5/A7; centered Jacobian differences at 1e-18 and 5e-19 for FP32-represented inputs; original-grid inputs also checked at 1e-18',
        gates=dict(value=8e-7,jacobian=2e-5,reference_halving=1e-12),
        comparisons=['arithmetic at same quantized input','total financial-output deviation from original FP64 fitted theta/grid inputs'],
        qualification='Only these eight fitted financial parameter tuples and 56 centers; no whole-SNN pure-FP32, full-parameter-box, or policy-quality claim')
    write('protocol.json',specification)
    results=[]
    start=time.perf_counter()
    for i,fixture in enumerate(fixtures):
        theta=np.array(fixture['theta_original'])
        x=fixture['state_original']
        qt=theta.astype(np.float32).astype(float)
        qx=float(np.float32(x))
        tick=time.perf_counter()
        expected=np.asarray(reference_tools.fields(qt,qx,'log_distance'),float)
        j1=reference_tools.jac(qt,qx,'log_distance','1e-18')
        j2=reference_tools.jac(qt,qx,'log_distance','5e-19')
        original=np.asarray(reference_tools.fields(theta,x,'log_distance'),float)
        original_j=reference_tools.jac(theta,x,'log_distance','1e-18')
        row=dict(**fixture,theta_quantized=qt.tolist(),state_quantized=qx,
            reference_quantized=expected.tolist(),reference_quantized_jacobian=j2.tolist(),
            reference_original=original.tolist(),reference_original_jacobian=original_j.tolist(),
            reference_halving_error=error(j1,j2),reference_seconds=time.perf_counter()-tick)
        tick=time.perf_counter()
        with warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter('always')
            try:
                values,jac=ds_kernel.evaluate(theta,x)
                if not np.isfinite(values).all() or not np.isfinite(jac).all():
                    raise ValueError('nonfinite DS output or Jacobian')
                ve,je=error(values,expected),error(jac,j2)
                vo,jo=error(values,original),error(jac,original_j)
                row.update(actual=values.tolist(),jacobian=jac.tolist(),value_error_quantized=ve,
                    jacobian_error_quantized=je,value_error_original=vo,jacobian_error_original=jo,
                    arithmetic_pass=bool(ve<=8e-7 and je<=2e-5 and row['reference_halving_error']<=1e-12),
                    original_input_comparison_pass=bool(vo<=8e-7 and jo<=2e-5))
            except (ValueError,ArithmeticError) as exc:
                row.update(error=str(exc),arithmetic_pass=False,original_input_comparison_pass=False)
            row['warnings']=sorted(set(str(w.message) for w in seen))
        row['ds_seconds']=time.perf_counter()-tick
        results.append(row)
        if i%28==0 or not row['arithmetic_pass'] or not row['original_input_comparison_pass']:
            print(i,fixture['seed'],fixture['index'],qx,row.get('value_error_quantized'),
                  row.get('jacobian_error_quantized'),row.get('value_error_original'),row.get('jacobian_error_original'),flush=True)
    summary=dict(rows=len(results),arithmetic_pass=sum(r['arithmetic_pass'] for r in results),
        original_input_comparison_pass=sum(r['original_input_comparison_pass'] for r in results),
        errors=sum('error' in r for r in results),warnings=sum(bool(r['warnings']) for r in results),
        state_min=min(r['state_original'] for r in results),state_max=max(r['state_original'] for r in results),
        max_value_error_quantized=max(r.get('value_error_quantized',0) for r in results),
        max_jacobian_error_quantized=max(r.get('jacobian_error_quantized',0) for r in results),
        max_value_error_original=max(r.get('value_error_original',0) for r in results),
        max_jacobian_error_original=max(r.get('jacobian_error_original',0) for r in results),
        max_reference_halving_error=max(r['reference_halving_error'] for r in results),
        ds_seconds=sum(r['ds_seconds'] for r in results),reference_seconds=sum(r['reference_seconds'] for r in results),
        total_seconds=time.perf_counter()-start)
    assert check_freeze()==ds_freeze
    assert all(sha(R13/'evidence'/name)==h for name,h in fit_hashes.items())
    write('json.gz',dict(specification=specification,summary=summary,rows=results))
    write('json',dict(specification=specification,summary=summary))
    files=[p for p in ROOT.glob('R13_GRID_PRECISION.*') if p.name!='R13_GRID_PRECISION.manifest.json']
    write('manifest.json',dict(files={p.name:sha(p) for p in sorted(files)}))
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':
    main()
