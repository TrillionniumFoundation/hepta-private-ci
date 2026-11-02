"""Independent-PDE centered-difference step-stability supplement."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time
import traceback
import numpy as np
import torch
from . import joint_kernel_sensitivity as base

HERE=Path(__file__).resolve().parent


def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def run(protocol,result,calls):
    start,cpu=time.perf_counter(),time.process_time();columns=[]
    point=np.array(protocol['physical_point']);h=protocol['reference_fd_step']
    for coordinate,name in enumerate(base.NAMES):
        plus=point.copy();minus=point.copy();plus[coordinate]+=h;minus[coordinate]-=h
        a=base.pde_outputs(plus,480,protocol['duration']);b=base.pde_outputs(minus,480,protocol['duration'])
        calls.extend((a,b));columns.append((np.array(a['observable'])-np.array(b['observable']))/(2*h))
        print(json.dumps(dict(phase='halfstep_PDE480',coordinate=name)),flush=True)
    jacobian=np.stack(columns,-1);old=np.array(result['reference_centered_FD']['480'])
    delta=float(np.max(abs(jacobian-old)))
    errors={grid:dict(projected_ref_count=float(np.max(abs(np.array(j)[:6]-jacobian[:6]))),
                     strict_cdf=float(np.max(abs(np.array(j)[6:]-jacobian[6:]))))
            for grid,j in result['autodiff_jacobians'].items()}
    return dict(schema=protocol['schema'],passed=delta<protocol['gate_maximum_1e4_5e5_Jacobian_difference'],
      maximum_FD_step_difference=delta,halfstep_jacobian=jacobian.tolist(),base_jacobian=old.tolist(),
      errors_vs_halfstep=errors,reference_calls=calls,wall_seconds=time.perf_counter()-start,
      process_cpu_seconds=time.process_time()-cpu)


if __name__=='__main__':
    torch.set_num_threads(1)
    parser=argparse.ArgumentParser();parser.add_argument('--attempt',default='001');parser.add_argument('--published-source-commit',required=True)
    args=parser.parse_args();commit=args.published_source_commit
    if len(commit)!=40 or any(c not in '0123456789abcdef' for c in commit):raise ValueError('full published source commit required')
    protocol=json.loads((HERE/'joint_kernel_sensitivity_halfstep_protocol.json').read_text())
    result_path=HERE/protocol['base_result'];result=json.loads(result_path.read_text())
    if result.get('published_source_commit')!=protocol['base_source_commit'] or not result.get('sources_unchanged_at_end'):
        raise ValueError('base sensitivity input identity mismatch')
    if digest(HERE/'joint_kernel.py')!=protocol['kernel_sha256'] or digest(HERE/'joint_kernel_sensitivity.py')!=protocol['base_source_sha256']:
        raise ValueError('frozen kernel/base sensitivity changed')
    paths=[Path(__file__),HERE/'joint_kernel_sensitivity_halfstep_protocol.json',*map(Path,base.hashes())]
    before={str(p):digest(p) for p in paths};input_hash=digest(result_path)
    prefix=HERE/('joint_kernel_sensitivity_halfstep_attempt_'+args.attempt)
    with prefix.with_name(prefix.name+'_sources.json.gz').open('xb') as f:
        f.write(gzip.compress(json.dumps({str(p):p.read_text() for p in paths},sort_keys=True).encode(),mtime=0))
    calls=[]
    try:out=run(protocol,result,calls)
    except Exception:out=dict(schema=protocol['schema'],passed=False,error=traceback.format_exc(),reference_calls=calls)
    unchanged=all(digest(p)==h for p,h in before.items()) and digest(result_path)==input_hash
    out.update(published_source_commit=commit,base_input_sha256=input_hash,source_sha256=before,sources_unchanged_at_end=unchanged)
    out['passed']=out['passed'] and unchanged
    with prefix.with_suffix('.json').open('x') as f:json.dump(out,f,indent=2,sort_keys=True);f.write('\n')
    print(json.dumps({k:v for k,v in out.items() if k not in ('reference_calls','halfstep_jacobian','base_jacobian','source_sha256')},indent=2))
    raise SystemExit(0 if out['passed'] else 1)
