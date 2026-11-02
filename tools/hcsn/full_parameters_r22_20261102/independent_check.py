"""Read-only raw replay; no imports from candidate dual/financial/verifier/reference."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('directory',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    start=time.process_time()
    here=Path(__file__).resolve().parent
    protocol=json.loads((here/'PROTOCOL.json').read_text())
    summary=json.loads((args.directory/'SUMMARY.json').read_text())
    counts=dict(cases=0,value_positions=0,jacobian_positions=0,finite_difference_positions=0)
    worst=dict(value_ratio=0.,jacobian_ratio=0.,finite_difference=0.,mass=0.)
    checks=[]
    with gzip.open(args.directory/'RAW.jsonl.gz','rt') as stream:
        for line in stream:
            row=json.loads(line)
            if 'failure' in row: checks.append(False);continue
            value=np.array(row['native']['values']);jac=np.array(row['native']['jacobian'])
            gold=np.array(row['reference']['values']);goldjac=np.array(row['reference']['jacobian'])
            checks.append(value.shape==(2001,) and jac.shape==(9,2001))
            vm=float(np.max(np.abs(value-gold)/(protocol['value_atol']+protocol['value_rtol']*np.abs(gold))))
            jm=float(np.max(np.abs(jac-goldjac)/(protocol['jacobian_atol']+protocol['jacobian_rtol']*np.abs(goldjac))))
            worst['value_ratio']=max(worst['value_ratio'],vm);worst['jacobian_ratio']=max(worst['jacobian_ratio'],jm)
            checks += [vm<=1,jm<=1,row['native']['lower']==row['reference']['lower']]
            for st in row['stencils']:
                j,h,d=st['coordinate'],st['h'],st['direction']
                samples={offset:np.array(sample) for offset,sample in zip(st['offsets'],st['samples'])}
                samples[0.]=value
                slopes=[]
                for step in [1.,.5,.25]:
                    if d:
                        slopes.append(d*((samples[d*step]-samples[0.])*4-(samples[2*d*step]-samples[0.]))/(2*step*h))
                    else:
                        slopes.append((samples[step]-samples[-step])/(2*step*h))
                for k in range(2):
                    derived=slopes[k+1]+(slopes[k+1]-slopes[k])/3
                    err=float(np.max(np.abs(derived-jac[j])/(1+np.abs(jac[j]))))
                    worst['finite_difference']=max(worst['finite_difference'],err)
                    checks.append(err<=protocol['finite_difference']['normalized_tolerance'])
                    counts['finite_difference_positions']+=2001
            q=value[1:1601].reshape(40,40);dq=jac[:,1:1601].reshape(9,40,40)
            masses=[np.max(abs(q.sum(axis=1))),np.max(abs(dq.sum(axis=2))),abs(value[-40:].sum()-1),np.max(abs(jac[:,-40:].sum(axis=1)))]
            worst['mass']=max(worst['mass'],float(max(masses)))
            checks.append(max(masses)<=protocol['mass_tolerance'])
            counts['cases']+=1;counts['value_positions']+=2001;counts['jacobian_positions']+=9*2001
    controls=json.loads((args.directory/'CONTROLS.json').read_text())
    checks.extend(row['exit_code']==2 and row['stdout']=='' for row in controls)
    source_match={name:hashlib.sha256((here/name).read_bytes()).hexdigest()==value for name,value in summary['source_sha256'].items()}
    checks += [all(source_match.values()),counts['cases']==summary['declared_cases'],summary['passed']]
    out=dict(passed=all(checks),checks=len(checks),counts=counts,maxima=worst,controls=len(controls),
             raw_gzip_sha256=hashlib.sha256((args.directory/'RAW.jsonl.gz').read_bytes()).hexdigest(),
             source_match=source_match,checker_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             parent_cpu_seconds=time.process_time()-start,
             cost_scope='Checker body after imports; complete process cost requires outer receipt.',
             independent_scope='Separate raw aggregation and finite-difference evaluation; this does not independently regenerate high-precision references or prove a uniform analytic error bound.')
    with args.output.open('x') as stream:json.dump(out,stream,indent=2,sort_keys=True);stream.write('\n')
    print(json.dumps(out,sort_keys=True),flush=True)
    raise SystemExit(not out['passed'])


if __name__=='__main__':main()
