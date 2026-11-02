"""Create raw numerical evidence; exit0 is not the independent result gate."""
import argparse,gzip,hashlib,json,sys,time
from pathlib import Path
import numpy as np
from compiled import Kernel

ROOT=Path(__file__).resolve().parent
MODES=('float64','float32','compensated32')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def dump(path,value):
    data=(json.dumps(value,separators=(',',':'),allow_nan=False)+'\n').encode()
    with path.open('xb') as f:f.write(gzip.compress(data,mtime=0) if path.suffix=='.gz' else data)
    return {'file':path.name,'sha256':sha(path),'bytes':path.stat().st_size}
def seal(protocol,path,expected):
    if sha(path)!=expected:raise ValueError('Protocol hash mismatch')
    for name,digest in protocol['source_sha256'].items():
        if sha(ROOT/name)!=digest:raise ValueError('Source changed: '+name)
    for name,key in [('recovered.so','binary_sha256'),('RECOVERY_CASES_V1.json','manifest_sha256'),('RECOVERED_BUILD.json','build_receipt_sha256')]:
        if sha(ROOT/name)!=protocol[key]:raise ValueError('Binary/manifest/build seal mismatch')

def run(protocol_path,expected,output,oracle_path):
    if output.exists():raise ValueError('Output directory is create-only')
    protocol=json.loads(protocol_path.read_text());seal(protocol,protocol_path,expected)
    sys.path.insert(0,str(oracle_path));sys.path.insert(0,str(ROOT/'frozen_input'))
    import frozen_reference as oracle
    from mpmath import mp
    ctx=mp.clone();ctx.dps=80;cv=lambda v:ctx.mpf(str(v));eps=ctx.mpf(2)**-23
    points=json.loads((ROOT/'RECOVERY_CASES_V1.json').read_text())['rows'];kernel=Kernel(ROOT/'recovered.so')
    cases=[];reference=[];actual={mode:[] for mode in MODES};output.mkdir();start=time.perf_counter()
    for index,point in enumerate(points):
        theta=point['theta'];case={'id':point['id'],'theta':theta,'independently_valid':False}
        try:
            r,d,s,al,tax,l,m,c,p=map(cv,theta);b=oracle.fields(theta,0.,'log_distance')[0]
            flow=d*b-(1-tax)*c+(al*b-p)/m;scale=abs(d*b)+abs((1-tax)*c)+(abs(al*b)+abs(p))/m
            valid=bool(ctx.isfinite(b) and b>0 and ctx.isfinite(flow) and flow<-64*eps*max(1,scale))
            case.update(independently_valid=valid,boundary=str(b),flow=str(flow),scale=str(scale))
            if not valid:raise ArithmeticError('Independently inadmissible boundary')
            a=(r-d-s*s/2)/(s*s);zt=ctx.sqrt(a*a+2*(r+l)/(s*s));limit=min(cv('.002'),cv('.02')*s*ctx.sqrt(m),cv('.05')/(1+abs(a)+zt))
            states=[('log_distance',0.),('log_distance',float(np.float32(float(cv('.75')*limit)))),('log_distance',1.),
                    ('asset',float(np.float32(float(b*(1-cv('1e-6')))))),('asset',float(np.float32(float(b*(1+cv('1e-6')))))),('asset',100.)]
        except Exception as error:
            case['error']=repr(error);cases.append(case)
            for slot in range(6):
                reference.append({'case':point['id'],'slot':slot,'error':repr(error)})
                for mode in MODES:actual[mode].append({'case':point['id'],'slot':slot,'status':-1,'error':'Unresolved independent input'})
            continue
        cases.append(case)
        for slot,(coordinate,state) in enumerate(states):
            identity={'case':point['id'],'slot':slot,'coordinate':coordinate,'state':state};ref=dict(identity)
            try:
                values=np.asarray([float(v) for v in oracle.fields(theta,state,coordinate)])
                j1=oracle.jacobian(theta,state,coordinate,step='1e-18');j2=oracle.jacobian(theta,state,coordinate,step='5e-19')
                if not all(np.all(np.isfinite(v)) for v in (values,j1,j2)):raise ArithmeticError('Nonfinite oracle')
                ref.update(values=values.tolist(),jacobian=j2.tolist(),jacobian_first=j1.tolist())
            except Exception as error:ref['error']=repr(error)
            reference.append(ref)
            for mode in MODES:
                row=dict(identity)
                try:
                    y,j,status=kernel.batch([theta],[state],[coordinate],mode);row['status']=int(status[0])
                    if status[0]!=0 or not np.all(np.isfinite(y)) or not np.all(np.isfinite(j)):raise ArithmeticError('Failed/nonfinite financial evaluation')
                    row.update(values=y[0].tolist(),jacobian=j[0].tolist())
                except Exception as error:row.setdefault('status',-1);row['error']=repr(error)
                actual[mode].append(row)
        if (index+1)%8==0:print(json.dumps({'completed_points':index+1,'rows':len(reference)}),flush=True)
    seal(protocol,protocol_path,expected)
    common={'protocol_sha256':expected,'binary_sha256':protocol['binary_sha256'],'source_sha256':protocol['source_sha256']}
    artifacts={'reference':dump(output/'REFERENCE.json.gz',{**common,'cases':cases,'rows':reference})}
    for mode in MODES:artifacts[mode]=dump(output/(mode+'.json.gz'),{**common,'mode':mode,'reference_sha256':artifacts['reference']['sha256'],'rows':actual[mode]})
    result={**common,'schema':'hcsn.recovered-raw-evaluation.v1','artifacts':artifacts,'point_count':len(cases),'rows':len(reference),
            'invalid_points':sum(not c['independently_valid'] for c in cases),'elapsed_seconds':time.perf_counter()-start,
            'scientific_gate':'Not assessed by this writer. Run recovery_check.py independently.','original_data_loss_disclosed':True}
    dump(output/'INDEX.json',result);print(json.dumps(result,indent=2),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--protocol',type=Path,required=True);p.add_argument('--protocol-sha256',required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--oracle-pythonpath',type=Path,required=True)
    a=p.parse_args();run(a.protocol,a.protocol_sha256,a.output,a.oracle_pythonpath)
