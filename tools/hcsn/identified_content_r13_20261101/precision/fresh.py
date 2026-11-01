"""Frozen fresh LHS and pressure verification; no outcome-dependent sampling."""

import gzip
import hashlib
import json
from pathlib import Path
import sys
import time
import warnings

import numpy as np
from scipy.stats import qmc

import ds_kernel
from development import error

ROOT=Path(__file__).resolve().parent
OLD=ROOT.parents[1]/"unified_cell_r12_20261031"/"numerics"
sys.path.insert(0,str(OLD))
import experiment as reference_tools
import stable32


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name,data):
    path=ROOT/name
    if path.exists():
        raise ValueError(f"Refusing to overwrite {name}")
    raw=(json.dumps(data,indent=2,allow_nan=False)+'\n').encode()
    path.write_bytes(gzip.compress(raw,mtime=0) if name.endswith('.gz') else raw)


def check_freeze():
    frozen=json.loads((ROOT/"FROZEN.json").read_text())
    assert all(sha(ROOT/n)==v for n,v in frozen['sources'].items())
    return sha(ROOT/"FROZEN.json")


def prepare():
    receipt=check_freeze()
    protocol=json.loads((ROOT/"FRESH_PROTOCOL.json").read_text())
    lo=np.r_[stable32.k.LOWER,1e-8]
    hi=np.r_[stable32.k.UPPER,2.]
    units=qmc.LatinHypercube(d=10,scramble=True,seed=protocol['lhs']['seed']).random(128)
    values=lo+(hi-lo)*units
    for d in protocol['lhs']['log_mapped_dimensions']:
        values[:,d]=np.exp(np.log(lo[d])+(np.log(hi[d])-np.log(lo[d]))*units[:,d])
    rows=[dict(name=f'lhs_{i}',group='lhs128',theta=row[:9].astype(np.float32).astype(float).tolist(),
        state=float(np.float32(row[9])),coordinate='log_distance') for i,row in enumerate(values)]
    for config in protocol['pressure']['configurations']:
        theta=stable32.k.BASE.copy()
        for i,value in config['edits'].items():
            theta[int(i)]=value
        theta=theta.astype(np.float32).astype(float)
        for x in protocol['pressure']['states_log_distance']:
            rows.append(dict(name=f"{config['name']}_x{x}",group='pressure_log64',theta=theta.tolist(),
                state=float(np.float32(x)),coordinate='log_distance'))
        boundary=float(reference_tools.fields(theta,.1,'log_distance')[0])
        for u in (-1e-5,0.,1e-5):
            state=float(np.float32(boundary*(1+u)))
            rows.append(dict(name=f"{config['name']}_asset{u}",group='pressure_asset24',theta=theta.tolist(),
                state=state,coordinate='asset',relative_boundary_offset=u,
                represented_distance_to_reference_boundary=state-boundary))
    write('FRESH_INPUTS.json',dict(freeze_sha256=receipt,protocol_sha256=sha(ROOT/'FRESH_PROTOCOL.json'),rows=rows))


def audit():
    receipt=check_freeze()
    inputs=json.loads((ROOT/'FRESH_INPUTS.json').read_text())
    result=[]
    started=time.perf_counter()
    for i,row in enumerate(inputs['rows']):
        theta,state,coordinate=row['theta'],row['state'],row['coordinate']
        tick=time.perf_counter()
        ref=np.asarray(reference_tools.fields(theta,state,coordinate),dtype=np.float64)
        j1=reference_tools.jac(theta,state,coordinate,'1e-18')
        j2=reference_tools.jac(theta,state,coordinate,'5e-19')
        item=dict(**row,reference=ref.tolist(),reference_jacobian=j2.tolist(),
            reference_halving_error=error(j1,j2),reference_seconds=time.perf_counter()-tick,modes={})
        modes={
          'single32':lambda:stable32.evaluate(theta,state,coordinate=coordinate,mode='float32',diagnostic_outside_box=True),
          'double_single':lambda:ds_kernel.evaluate(theta,state,coordinate=coordinate,diagnostic_outside_box=True),
          'mixed64':lambda:stable32.evaluate(theta,state,coordinate=coordinate,mode='mixed32',candidate=False,diagnostic_outside_box=True)}
        for label,call in modes.items():
            tick=time.perf_counter()
            with warnings.catch_warnings(record=True) as seen:
                warnings.simplefilter('always')
                try:
                    v,j=call()
                    if not np.isfinite(v).all() or not np.isfinite(j).all():
                        raise ValueError('nonfinite output or tangent')
                    ve,je=error(v,ref),error(j,j2)
                    record=dict(value_error=ve,jacobian_error=je,actual=v.tolist(),jacobian=j.tolist(),
                        passed=ve<=8e-7 and je<=2e-5 and item['reference_halving_error']<=1e-12)
                except (ValueError,ArithmeticError) as exc:
                    record=dict(passed=False,error=str(exc))
                record.update(seconds=time.perf_counter()-tick,warnings=sorted(set(str(w.message) for w in seen)))
            item['modes'][label]=record
        result.append(item)
        if i%8==0 or not item['modes']['double_single']['passed']:
            print(i,row['name'],{k:(v.get('value_error'),v.get('jacobian_error'),v['passed']) for k,v in item['modes'].items()},flush=True)
    summary={}
    for group in ('lhs128','pressure_log64','pressure_asset24'):
        subset=[r for r in result if r['group']==group]
        summary[group]={mode:dict(rows=len(subset),passed=sum(r['modes'][mode]['passed'] for r in subset),
            rejected=sum('error' in r['modes'][mode] for r in subset),
            max_value_error=max(r['modes'][mode].get('value_error',0) for r in subset),
            max_jacobian_error=max(r['modes'][mode].get('jacobian_error',0) for r in subset),
            kernel_seconds=sum(r['modes'][mode]['seconds'] for r in subset)) for mode in modes}
    assert check_freeze()==receipt
    payload=dict(freeze_sha256=receipt,inputs_sha256=sha(ROOT/'FRESH_INPUTS.json'),rows=result,
        summary=summary,seconds=time.perf_counter()-started)
    write('FRESH_RESULTS.json.gz',payload)
    write('FRESH_SUMMARY.json',{k:v for k,v in payload.items() if k!='rows'})
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':
    prepare() if sys.argv[1]=='prepare' else audit()
