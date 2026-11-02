"""Separate stored-data replay; imports no candidate, primary reference or R11."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time
import numpy as np


def main():
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    start=time.process_time();here=Path(__file__).resolve().parent;protocol=json.loads((here/'PROTOCOL.json').read_text())
    summary=json.loads((args.directory/'SUMMARY.json').read_text());raw=gzip.decompress((args.directory/'RAW.json.gz').read_bytes());data=json.loads(raw)
    checks=[hashlib.sha256(raw).hexdigest()==summary['raw_sha256'],not data['failures']];counts=dict(points=0,values=0,jacobian_positions=0,reference_positions=0,finite_difference_positions=0)
    worst=dict(reference_ratio=0.,finite_difference=0.)
    for row in data['rows']:
        if 'native' not in row:checks.append(False);continue
        value=np.array(row['native']['values']);jac=np.array(row['native']['jacobian']);checks += [value.shape==(5,),jac.shape==(5,10)]
        for target in [row['reference'],row['r11']]:
            for name,actual in [('values',value),('jacobian',jac)]:
                gold=np.array(target[name]);ratio=float(np.max(np.abs(actual-gold)/(protocol[name+'_atol']+protocol[name+'_rtol']*np.abs(gold))))
                worst['reference_ratio']=max(worst['reference_ratio'],ratio);checks.append(ratio<=1);counts['reference_positions']+=gold.size
        for stencil in row['stencils']:
            h,d,j=stencil['h'],stencil['direction'],stencil['coordinate'];samples={o:np.array(v) for o,v in zip(stencil['offsets'],stencil['samples'])};samples[0.]=value
            slopes=[]
            for scale in [1.,.5,.25]:
                if d: slopes.append(d*(4*(samples[d*scale]-value)-(samples[2*d*scale]-value))/(2*scale*h))
                else:slopes.append((samples[scale]-samples[-scale])/(2*scale*h))
            for k in range(2):
                slope=slopes[k+1]+(slopes[k+1]-slopes[k])/3;err=float(np.max(abs(slope-jac[:,j])/(1+abs(jac[:,j]))));worst['finite_difference']=max(worst['finite_difference'],err);checks.append(err<=protocol['finite_difference_tolerance']);counts['finite_difference_positions']+=5
        checks.append(value[0]>0 and value[1]>=-protocol['values_atol'] and 0<=value[2]<=1+1e-12 and 0<=value[3]<=value[2]+1e-12 and value[4]>0)
        counts['points']+=1;counts['values']+=5;counts['jacobian_positions']+=50
    checks += [row['exit_code']==2 and not row['stdout'] for row in data['controls']]
    sources={name:hashlib.sha256((here/name).read_bytes()).hexdigest()==digest for name,digest in summary['source_sha256'].items()}
    checks += [all(sources.values()),counts['points']==summary['cases'],summary['passed']]
    result=dict(passed=bool(all(checks)),checks=len(checks),counts=counts,maxima=worst,controls=len(data['controls']),source_hashes_match=sources,raw_sha256=summary['raw_sha256'],checker_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),body_cpu_seconds=time.process_time()-start,cost_scope='After imports; full external meter is authoritative for complete process CPU.')
    with args.output.open('x') as stream:json.dump(result,stream,indent=2,sort_keys=True);stream.write('\n')
    print(json.dumps(result,sort_keys=True),flush=True);raise SystemExit(not result['passed'])


if __name__=='__main__':main()
