"""Frozen complete nine-parameter sensitivity campaign; no clipping or retries by error."""
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

from reference import evaluate

HERE = Path(__file__).resolve().parent
RUSTC = '/tmp/hcsn-r15-runtime-tools/rustup/toolchains/1.95.0-x86_64-unknown-linux-gnu/bin/rustc'


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')


def native(binary, points, mode=None):
    command = [str(binary)] + ([] if mode is None else [mode])
    text = ''.join(' '.join(map(repr, map(float, row))) + '\n' for row in points)
    call = subprocess.run(command, input=text.encode(), capture_output=True)
    if call.returncode:
        raise RuntimeError(dict(command=command, stderr=call.stderr.decode(), code=call.returncode))
    rows = list(map(json.loads, call.stdout.splitlines()))
    if len(rows) != len(points):
        raise ValueError('Native batch count mismatch')
    return rows


def stencil(binary, point, coordinate, original, protocol):
    lo, hi = protocol['lower'][coordinate], protocol['upper'][coordinate]
    h0 = (hi - lo) * protocol['finite_difference']['width_fraction']
    # Halving depends ONLY on domain admission and reset-regime identity.
    for halving in range(protocol['finite_difference']['maximum_halvings'] + 1):
        h = h0 / 2 ** halving
        direction = 0 if lo <= point[coordinate]-h and point[coordinate]+h <= hi else (1 if point[coordinate]+2*h <= hi else -1)
        offsets = [-1., -.5, -.25, .25, .5, 1.] if direction == 0 else [direction*.25, direction*.5, direction, direction*2.]
        points = []
        for offset in offsets:
            theta = point.copy()
            theta[coordinate] += offset * h
            points.append(theta)
        try:
            rows = native(binary, points, '--values')
        except RuntimeError:
            continue
        if any(row['lower'] != original['lower'] for row in rows):
            continue
        values = {offset: np.asarray(row['values']) for offset, row in zip(offsets, rows)}
        values[0.] = np.asarray(original['values'])
        if direction == 0:
            slopes = [(values[scale]-values[-scale])/(2*scale*h) for scale in [1., .5, .25]]
        else:
            slopes = [direction*(-3*values[0.]+4*values[direction*scale]-values[direction*2*scale])/(2*scale*h)
                      for scale in [1., .5, .25]]
        extrapolated = [(4*slopes[i+1]-slopes[i])/3 for i in range(2)]
        jacobian = np.asarray(original['jacobian'])[coordinate]
        errors = [float(np.max(abs(row-jacobian)/(1+abs(jacobian)))) for row in extrapolated]
        return dict(coordinate=coordinate, direction=direction, h=h, halvings=halving, offsets=offsets,
                    samples=[row['values'] for row in rows], errors=errors,
                    passed=bool(max(errors) <= protocol['finite_difference']['normalized_tolerance']))
    raise ValueError('No admitted finite-difference stencil within registered halving cap')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--formal', action='store_true')
    args = parser.parse_args()
    start, cpu = time.monotonic(), time.process_time()
    child_start = resource.getrusage(resource.RUSAGE_CHILDREN)
    protocol = json.loads((HERE/'PROTOCOL.json').read_text())
    identities = {name: hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in protocol['sources']}
    if args.formal:
        receipt = json.loads((HERE/'PUBLICATION.json').read_text())
        if not receipt['readback_verified'] or identities != receipt['source_sha256']:
            raise ValueError('Source/protocol/transitive dependency freeze mismatch')
    args.output.mkdir(exist_ok=False)
    binary = args.output/'financial'
    build_command = [RUSTC, '--edition=2024', '-D', 'warnings', '-O', str(HERE/'main.rs'), '-o', str(binary)]
    build = subprocess.run(build_command, capture_output=True)
    (args.output/'build.stdout').write_bytes(build.stdout)
    (args.output/'build.stderr').write_bytes(build.stderr)
    write(args.output/'BUILD.json', dict(command=build_command, exit_code=build.returncode, source_sha256=identities))
    build.check_returncode()
    baseline = protocol['baseline']
    if args.formal:
        points = list(itertools.product(*zip(protocol['lower'], protocol['upper'])))
        rng = np.random.default_rng(protocol['confirmation_namespace'])
        points += rng.uniform(protocol['lower'], protocol['upper'], (protocol['random_interior_cases'], 9)).tolist()
        for coordinate in range(9):
            for endpoint in [protocol['lower'][coordinate], protocol['upper'][coordinate]]:
                theta = baseline.copy()
                theta[coordinate] = endpoint
                points.append(theta)
        points.append(baseline)
    else:
        points = [[.08,.02,.6,.27,6.39,61.68,sigma,liquidity,maturity]
                  for sigma,liquidity,maturity in itertools.product([.15,.4],[.002,.04],[.5,2.])]
        points.append(baseline)
    maxima = {k:0. for k in ['values_normalized','jacobian_normalized','finite_difference_normalized',
                            'generator_mass','jacobian_mass','prior_mass','prior_jacobian_mass']}
    gates = dict(value_reference=True, all_parameter_jacobian_reference=True, all_array_finite_difference=True,
                 finite_generator_and_mass=True, all_cases_admitted=True, guards=True)
    cases, failures, changed = 0, [], [0.] * 9
    raw_path = args.output/'RAW.jsonl.gz'
    with raw_path.open('xb') as raw_stream, gzip.GzipFile(fileobj=raw_stream, filename='', mode='wb', mtime=0) as zipped:
        for index, theta in enumerate(points):
            try:
                original = native(binary, [theta])[0]
                gold = evaluate(theta)
                values, jacobian = np.asarray(original['values']), np.asarray(original['jacobian'])
                if values.shape != (2001,) or jacobian.shape != (9,2001) or gold['lower'] != original['lower']:
                    raise ValueError('Array shape or reference regime mismatch')
                vm = float(np.max(abs(values-gold['values'])/(protocol['value_atol']+protocol['value_rtol']*abs(gold['values']))))
                jm = float(np.max(abs(jacobian-gold['jacobian'])/(protocol['jacobian_atol']+protocol['jacobian_rtol']*abs(gold['jacobian']))))
                stencils = [stencil(binary, list(theta), coordinate, original, protocol) for coordinate in range(9)]
                q, dq = values[1:1601].reshape(40,40), jacobian[:,1:1601].reshape(9,40,40)
                mass = dict(generator_mass=float(np.max(abs(q.sum(1)))), jacobian_mass=float(np.max(abs(dq.sum(2)))),
                            prior_mass=abs(float(values[-40:].sum())-1), prior_jacobian_mass=float(np.max(abs(jacobian[:,-40:].sum(1)))))
                offdiagonal=q.copy(); np.fill_diagonal(offdiagonal,0)
                structural = bool(np.min(offdiagonal)>=0 and np.min(values[-40:])>=0 and max(mass.values())<=protocol['mass_tolerance'])
                gates['value_reference'] &= vm<=1
                gates['all_parameter_jacobian_reference'] &= jm<=1
                gates['all_array_finite_difference'] &= all(row['passed'] for row in stencils)
                gates['finite_generator_and_mass'] &= structural
                maxima['values_normalized']=max(maxima['values_normalized'],vm)
                maxima['jacobian_normalized']=max(maxima['jacobian_normalized'],jm)
                maxima['finite_difference_normalized']=max(maxima['finite_difference_normalized'],max(max(row['errors']) for row in stencils))
                for key,value in mass.items(): maxima[key]=max(maxima[key],value)
                for j in range(9): changed[j]=max(changed[j],float(np.max(abs(jacobian[j]))))
                record=dict(index=index,theta=list(theta),native=original,
                            reference={k:(v.tolist() if isinstance(v,np.ndarray) else v) for k,v in gold.items()},
                            stencils=stencils,reference_normalized_errors=[vm,jm],mass=mass,structural_passed=structural)
                cases+=1
            except Exception as error:
                gates['all_cases_admitted']=False
                record=dict(index=index,theta=list(theta),failure=repr(error))
                failures.append(record)
            zipped.write(json.dumps(record,separators=(',',':'),sort_keys=True,allow_nan=False).encode()+b'\n')
    controls=[]
    def reject(label,text,args_extra=None):
        call=subprocess.run([str(binary)]+(args_extra or []),input=text.encode(),capture_output=True)
        row=dict(label=label,stdin=text,arguments=args_extra or [],exit_code=call.returncode,
                 stdout=call.stdout.decode(),stderr=call.stderr.decode(),passed=call.returncode==2 and not call.stdout)
        controls.append(row)
    for j in range(9):
        width=protocol['upper'][j]-protocol['lower'][j]
        for label,value in [('low',protocol['lower'][j]-.01*width),('high',protocol['upper'][j]+.01*width),('nan','nan')]:
            theta=baseline.copy();theta[j]=value
            reject(f'coordinate{j}_{label}',' '.join(map(str,theta))+'\n')
    reject('empty','')
    reject('arity8',' '.join(map(str,baseline[:8]))+'\n')
    reject('arity10',' '.join(map(str,baseline+[1]))+'\n')
    reject('mode',' '.join(map(str,baseline))+'\n',['--unknown'])
    reject('batch129',(' '.join(map(str,baseline))+'\n')*129)
    reject('capacity','0'*1048577)
    knot=baseline.copy();knot[6]=.15;knot[7]=.002;knot[8]=1.0602625344670003
    reject('retained_R20_knot',' '.join(map(str,knot))+'\n')
    gates['guards']=all(row['passed'] for row in controls)
    gates['all_nine_coordinates_active']=all(value>0 for value in changed)
    gates={k:bool(v) for k,v in gates.items()}
    write(args.output/'CONTROLS.json',controls)
    child=resource.getrusage(resource.RUSAGE_CHILDREN)
    summary=dict(passed=all(gates.values()),gates=gates,maxima=maxima,cases=cases,declared_cases=len(points),
                 failures=failures,controls=len(controls),maximum_absolute_gradient_by_coordinate=changed,
                 source_sha256=identities,binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                 raw_gzip_sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                 namespace=protocol['confirmation_namespace'] if args.formal else None,
                 parent_cpu_seconds=time.process_time()-cpu,
                 child_cpu_seconds=child.ru_utime+child.ru_stime-child_start.ru_utime-child_start.ru_stime,
                 wall_seconds=time.monotonic()-start,cost_scope='Verifier interval including native build/calls; external full-process receipt supersedes for complete accounting; excludes final summary write.',
                 production_activation=False,all_blockers_closed=False)
    print(json.dumps(summary,sort_keys=True),flush=True)
    write(args.output/'SUMMARY.json',summary)
    raise SystemExit(not summary['passed'])


if __name__=='__main__': main()
