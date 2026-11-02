"""Native five-channel ten-coordinate validation with frozen finite information."""
import argparse
import gzip
import hashlib
import itertools
import json
import os
from pathlib import Path
import resource
import subprocess
import time

import numpy as np

from reference import evaluate as high_precision
import r11_kernel_snapshot as r11

HERE=Path(__file__).resolve().parent
RUSTC='/tmp/hcsn-r15-runtime-tools/rustup/toolchains/1.95.0-x86_64-unknown-linux-gnu/bin/rustc'
ORDER=[0,1,6,2,3,7,8,4,5]
INVERSE=[0,1,3,4,7,8,2,5,6,9]


def write(path,value):
    with path.open('x') as stream:json.dump(value,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')


def native(binary,points,mode=None):
    text=''.join(' '.join(map(repr,map(float,p)))+'\n' for p in points)
    call=subprocess.run([str(binary)]+([] if mode is None else [mode]),input=text.encode(),capture_output=True)
    if call.returncode:raise ValueError(dict(exit_code=call.returncode,stderr=call.stderr.decode()))
    rows=list(map(json.loads,call.stdout.splitlines()))
    if len(rows)!=len(points):raise ValueError('Batch count mismatch')
    return rows


def stencil(binary,point,j,original,protocol):
    lower=(protocol['lower']+[protocol['state_box'][0]])[j]
    upper=(protocol['upper']+[protocol['state_box'][1]])[j]
    h=(upper-lower)*protocol['finite_difference_width_fraction']
    d=0 if point[j]-h>=lower and point[j]+h<=upper else (1 if point[j]+2*h<=upper else -1)
    offsets=[-1.,-.5,-.25,.25,.5,1.] if not d else [d*.25,d*.5,d,d*2.]
    points=[]
    for offset in offsets:
        p=point.copy();p[j]+=offset*h;points.append(p)
    rows=native(binary,points,'--values')
    samples={offset:np.array(row['values']) for offset,row in zip(offsets,rows)};samples[0.]=np.array(original['values'])
    slopes=[]
    for scale in [1.,.5,.25]:
        slopes.append((samples[scale]-samples[-scale])/(2*scale*h) if not d else
                      d*(-3*samples[0.]+4*samples[d*scale]-samples[2*d*scale])/(2*scale*h))
    errors=[float(np.max(abs((4*slopes[k+1]-slopes[k])/3-np.array(original['jacobian'])[:,j])/(1+abs(np.array(original['jacobian'])[:,j])))) for k in range(2)]
    return dict(coordinate=j,h=h,direction=d,offsets=offsets,samples=[row['values'] for row in rows],errors=errors,
                passed=max(errors)<=protocol['finite_difference_tolerance'])


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--formal',action='store_true');args=parser.parse_args()
    start=time.monotonic();cpu=time.process_time();child_start=resource.getrusage(resource.RUSAGE_CHILDREN)
    protocol=json.loads((HERE/'PROTOCOL.json').read_text())
    identity={name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in protocol['sources']}
    if args.formal:
        pub=json.loads((HERE/'PUBLICATION.json').read_text())
        if not pub['readback_verified'] or pub['source_sha256']!=identity:raise ValueError('Unfrozen source or transitive dependency')
    args.output.mkdir(exist_ok=False)
    binary=args.output/'channels';command=[RUSTC,'--edition=2024','-D','warnings','-O',str(HERE/'main.rs'),'-o',str(binary)]
    call=subprocess.run(command,capture_output=True);(args.output/'build.stdout').write_bytes(call.stdout);(args.output/'build.stderr').write_bytes(call.stderr)
    write(args.output/'BUILD.json',dict(command=command,exit_code=call.returncode,source_sha256=identity));call.check_returncode()
    raw_stream=(args.output/'RAW.json.gz').open('xb')
    os.posix_fallocate(raw_stream.fileno(),0,protocol['output_reservation_bytes'])
    if args.formal:
        rng=np.random.default_rng(protocol['confirmation_namespace'])
        parameters=rng.uniform(protocol['lower'],protocol['upper'],(64,9)).tolist()+[protocol['baseline']]
        states=protocol['formal_states']
    else:
        parameters=[[.08,.02,.6,.27,6.39,61.68,sigma,liquidity,maturity] for sigma,liquidity,maturity in itertools.product([.15,.4],[.002,.04],[.5,2.])]+[protocol['baseline']]
        states=[.01,.2]
    points=[list(theta)+[state] for theta in parameters for state in states]
    rows=[];failures=[];gates=dict(admission=True,high_precision_values=True,high_precision_jacobians=True,r11_values=True,r11_jacobians=True,finite_difference=True,financial_range=True,controls=True)
    maxima={key:0. for key in ['hp_values_ratio','hp_jacobian_ratio','r11_values_ratio','r11_jacobian_ratio','finite_difference_normalized']}
    for index,point in enumerate(points):
        try:
            got=native(binary,[point])[0];gold=high_precision(point)
            values,jac=np.array(got['values']),np.array(got['jacobian'])
            if values.shape!=(5,) or jac.shape!=(5,10):raise ValueError('Output shape')
            rv,rj=r11.evaluate(np.array(point[:9])[ORDER],point[9],coordinate='log_distance');rj=rj[:,INVERSE]
            comparisons={}
            for name,target in [('hp',gold),('r11',dict(values=rv,jacobian=rj))]:
                ratios=[]
                for kind,actual in [('values',values),('jacobian',jac)]:
                    ref=np.array(target[kind]);ratio=float(np.max(abs(actual-ref)/(protocol[kind+'_atol']+protocol[kind+'_rtol']*abs(ref))))
                    maxima[name+'_'+('jacobian' if kind=='jacobian' else 'values')+'_ratio']=max(maxima[name+'_'+('jacobian' if kind=='jacobian' else 'values')+'_ratio'],ratio)
                    gates[('high_precision_' if name=='hp' else 'r11_')+('jacobians' if kind=='jacobian' else 'values')] &= ratio<=1
                    ratios.append(ratio)
                comparisons[name]=ratios
            stencils=[stencil(binary,point,j,got,protocol) for j in range(10)]
            fd=max(max(row['errors']) for row in stencils);maxima['finite_difference_normalized']=max(maxima['finite_difference_normalized'],fd);gates['finite_difference'] &= fd<=protocol['finite_difference_tolerance']
            physical=bool(values[0]>0 and values[1]>=-protocol['values_atol'] and 0<=values[2]<=1+1e-12 and 0<=values[3]<=values[2]+1e-12 and values[4]>0)
            gates['financial_range'] &= physical
            rows.append(dict(index=index,point=point,native=got,reference=gold,r11=dict(values=rv.tolist(),jacobian=rj.tolist()),stencils=stencils,ratios=comparisons,financial_range=physical))
        except Exception as error:
            gates['admission']=False;failure=dict(index=index,point=point,error=repr(error));failures.append(failure);rows.append(failure)
    controls=[]
    def reject(label,text,extra=None):
        c=subprocess.run([str(binary)]+(extra or []),input=text.encode(),capture_output=True)
        controls.append(dict(label=label,stdin=text,arguments=extra or [],exit_code=c.returncode,stdout=c.stdout.decode(),stderr=c.stderr.decode(),passed=c.returncode==2 and not c.stdout))
    baseline=protocol['baseline']+[.2]
    for j in range(10):
        lower=(protocol['lower']+[protocol['state_box'][0]])[j];upper=(protocol['upper']+[protocol['state_box'][1]])[j]
        for name,value in [('low',lower-.01*(upper-lower)),('high',upper+.01*(upper-lower)),('nan','nan')]:
            p=baseline.copy();p[j]=value;reject(f'coordinate{j}_{name}',' '.join(map(str,p))+'\n')
    reject('default_boundary_state',' '.join(map(str,baseline[:9]+[0]))+'\n')
    reject('empty','');reject('arity9',' '.join(map(str,baseline[:9]))+'\n');reject('arity11',' '.join(map(str,baseline+[0]))+'\n')
    reject('unknown_mode',' '.join(map(str,baseline))+'\n',['--asset']);reject('batch129',(' '.join(map(str,baseline))+'\n')*129);reject('byte_capacity','0'*1048577)
    gates['controls']=all(row['passed'] for row in controls);gates={k:bool(v) for k,v in gates.items()}
    payload=dict(rows=rows,controls=controls,failures=failures)
    raw=json.dumps(payload,separators=(',',':'),sort_keys=True,allow_nan=False).encode();compressed=gzip.compress(raw,mtime=0)
    if len(compressed)>protocol['output_reservation_bytes']:raise ValueError('Registered raw output capacity exceeded')
    raw_stream.seek(0);raw_stream.write(compressed);raw_stream.truncate(len(compressed));raw_stream.flush();os.fsync(raw_stream.fileno());raw_stream.close()
    child=resource.getrusage(resource.RUSAGE_CHILDREN)
    summary=dict(passed=all(gates.values()),gates=gates,maxima=maxima,cases=len(points),failures=len(failures),controls=len(controls),source_sha256=identity,
                 namespace=protocol['confirmation_namespace'] if args.formal else None,binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),raw_sha256=hashlib.sha256(raw).hexdigest(),
                 parent_cpu_seconds=time.process_time()-cpu,child_cpu_seconds=child.ru_utime+child.ru_stime-child_start.ru_utime-child_start.ru_stime,wall_seconds=time.monotonic()-start,
                 cost_scope='Inner scientific body after imports; native build/calls included. Do not add inner costs to complete external process receipt.',all_blockers_closed=False,production_activation=False)
    print(json.dumps(summary,sort_keys=True),flush=True);write(args.output/'SUMMARY.json',summary);raise SystemExit(not summary['passed'])


if __name__=='__main__':main()
