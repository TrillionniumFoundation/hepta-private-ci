"""Independent checker: cheap hard rejection, then fresh MP80 recalculation."""
import argparse,gzip,hashlib,io,json,math,struct,sys
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parent
MODES=('float64','float32','compensated32')
class Invalid(Exception):pass
def need(test,message):
    if not test:raise Invalid(message)
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):
    raw=path.read_bytes();need(len(raw)<=4_000_000,'Oversized file')
    if path.suffix=='.gz':
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as f:raw=f.read(8_000_001)
    need(len(raw)<=8_000_000,'Oversized decoded file')
    return json.loads(raw,parse_constant=lambda value:(_ for _ in ()).throw(Invalid('Nonfinite JSON token')))
def num(v):
    need(type(v) in (float,int) and math.isfinite(v),'Nonfinite/non-numeric entry');return float(v)
def word(v):return struct.pack('f',num(v))
def array(v,n):
    need(type(v) is list and len(v)==n,'Wrong vector length');return [num(x) for x in v]
def fields(row,first=False):
    values=array(row['values'],5);jac=row['jacobian_first' if first else 'jacobian'];need(type(jac) is list and len(jac)==5,'Wrong Jacobian row count')
    return np.asarray(values),np.asarray([array(line,10) for line in jac])
def identity(row):return (row['case'],row['slot'],row['coordinate'],word(row['state']))

def check(protocol_path,expected,evidence,oracle_path):
    need(sha(protocol_path)==expected,'Wrong frozen protocol');p=read(protocol_path)
    for name,digest in p['source_sha256'].items():need(sha(ROOT/name)==digest,'Frozen source changed: '+name)
    need(sha(ROOT/'recovered.so')==p['binary_sha256'],'Wrong binary')
    need(sha(ROOT/'RECOVERY_CASES_V1.json')==p['manifest_sha256'],'Wrong input manifest')
    need(sha(ROOT/'RECOVERED_BUILD.json')==p['build_receipt_sha256'],'Wrong build receipt')
    build=read(ROOT/'RECOVERED_BUILD.json')
    built_sources={name:p['source_sha256'][name] for name in ('kernel.cpp','arithmetic.hpp','constants.hpp','compiled.py','generate_constants.py','DEVELOPMENT_PROTOCOL.json')}
    need(build['returncode']==0 and build['source_unchanged'] is True and build['source_sha256_before']==built_sources and build['source_sha256_after']==built_sources,'Build source/result mismatch')
    need(build['binary_sha256']==p['binary_sha256'] and build['compiler_version']==p['compiler_version'] and build['command'][1:1+len(p['compiler_flags'])]==p['compiler_flags'],'Build binary/compiler mismatch')
    points=read(ROOT/'RECOVERY_CASES_V1.json')['rows'];need(len(points)==128 and len({r['id'] for r in points})==128,'Wrong/duplicate parameter cases')
    index=read(evidence/'INDEX.json');need(index['protocol_sha256']==expected and index['binary_sha256']==p['binary_sha256'],'Index identity mismatch')
    bound_paths={'protocol':protocol_path,'manifest':ROOT/'RECOVERY_CASES_V1.json','build':ROOT/'RECOVERED_BUILD.json','index':evidence/'INDEX.json'}
    payload={};native_bad=set()
    for mode in ('reference',)+MODES:
        entry=index['artifacts'][mode];name='REFERENCE.json.gz' if mode=='reference' else mode+'.json.gz'
        need(entry['file']==name and sha(evidence/name)==entry['sha256'],'Artifact binding mismatch');bound_paths[mode]=evidence/name;payload[mode]=read(evidence/name)
        need(payload[mode]['protocol_sha256']==expected and payload[mode]['binary_sha256']==p['binary_sha256'],'Payload identity mismatch')
        need(payload[mode]['source_sha256']==p['source_sha256'],'Payload source mismatch')
        need(len(payload[mode]['rows'])==768,'Missing/extra state rows')
    evidence_hashes={name:sha(path) for name,path in bound_paths.items()}
    ref=payload['reference'];need(len(ref['cases'])==128,'Missing parameter metadata')
    expected_slots=[(point['id'],slot) for point in points for slot in range(6)]
    need([(r['case'],r['slot']) for r in ref['rows']]==expected_slots,'Reference ID/slot mismatch')
    for point,case in zip(points,ref['cases']):
        need(point['id']==case['id'] and point['theta']==case['theta'] and case.get('independently_valid') is True and 'error' not in case,'Rejected/unbound parameter point')
        theta=array(point['theta'],9);need(all(struct.unpack('f',word(v))[0]==v for v in theta),'Input not quantized once to FP32')
    for row in ref['rows']:
        need('error' not in row,'Failed oracle row');fields(row);fields(row,True)
    for mode in MODES:
        need(payload[mode]['mode']==mode and payload[mode]['reference_sha256']==index['artifacts']['reference']['sha256'],'Mode/reference mismatch')
        for ri,(row,gold) in enumerate(zip(payload[mode]['rows'],ref['rows'])):
            need(identity(row)==identity(gold),'Input binding mismatch');need(type(row.get('status')) is int and row['status'] in (-1,0,1,2),'Invalid execution status')
            if row['status']!=0 or 'error' in row:
                need(mode=='float32','Required mode rejected/error state');native_bad.add(ri);continue
            y,j=fields(row)
            if mode!='float64':need(all(struct.unpack('f',word(v))[0]==v for v in y.tolist()+j.reshape(-1).tolist()),'Non-FP32 transported output')
    # Numerical references are recomputed only after all cheap shape/hash/count/status checks.
    sys.path.insert(0,str(oracle_path));sys.path.insert(0,str(ROOT/'frozen_input'));import frozen_reference as oracle
    from mpmath import mp
    ctx=mp.clone();ctx.dps=80;cv=lambda v:ctx.mpf(str(v));eps=ctx.mpf(2)**-23
    counts={mode:0 for mode in MODES};maxv={mode:0. for mode in MODES};maxj={mode:0. for mode in MODES};case_pass={mode:0 for mode in MODES}
    branches=[];right=[];reference_checks=[]
    for ci,(point,case) in enumerate(zip(points,ref['cases'])):
        theta=point['theta'];t=list(map(cv,theta));r,d,s,al,tax,l,m,c,principal=t;b=oracle.fields(theta,0.,'log_distance')[0]
        flow=d*b-(1-tax)*c+(al*b-principal)/m;scale=abs(d*b)+abs((1-tax)*c)+(abs(al*b)+abs(principal))/m
        need(ctx.isfinite(b) and b>0 and flow<-64*eps*max(1,scale),'Independent domain rejection')
        need(str(b)==case['boundary'] and str(flow)==case['flow'],'Recorded independent boundary mismatch')
        a=(r-d-s*s/2)/(s*s);zt=ctx.sqrt(a*a+2*(r+l)/(s*s));limit=min(cv('.002'),cv('.02')*s*ctx.sqrt(m),cv('.05')/(1+abs(a)+zt))
        states=[('log_distance',0.),('log_distance',float(np.float32(float(cv('.75')*limit)))),('log_distance',1.),
                ('asset',float(np.float32(float(b*(1-cv('1e-6')))))),('asset',float(np.float32(float(b*(1+cv('1e-6')))))),('asset',100.)]
        neighbors=[]
        for step in ['1e-18','5e-19']:
            for col,value in enumerate(t):
                for sign in [-1,1]:
                    shifted=t.copy();shifted[col]+=sign*cv(step)*max(cv('.01'),abs(value));boundary=oracle.fields(shifted,0.,'log_distance')[0]
                    neighbors.append({'step':step,'column':col,'sign':sign,'shifted_parameter':str(shifted[col]),'boundary':str(boundary)})
        case_good={mode:True for mode in MODES};asset_details=[]
        for slot,(coordinate,state) in enumerate(states):
            row=ref['rows'][ci*6+slot];need(row['coordinate']==coordinate and word(row['state'])==word(state),'State preparation mismatch')
            independent=[float(v) for v in oracle.fields(theta,state,coordinate)];j1=oracle.jacobian(theta,state,coordinate,'1e-18');j2=oracle.jacobian(theta,state,coordinate,'5e-19')
            ry,rj=fields(row);_,rj1=fields(row,True)
            need(np.array_equal(ry,independent) and np.array_equal(rj,j2) and np.array_equal(rj1,j1),'Stored reference differs from independent MP80 recalculation')
            halving=float(np.max(abs(j1-j2)/np.maximum(1.,abs(j2))));need(math.isfinite(halving) and halving<=1e-12,'Oracle halving failed')
            reference_checks.append({'case':point['id'],'slot':slot,'halving_error':halving})
            for mode in MODES:
                if mode=='float32' and ci*6+slot in native_bad:case_good[mode]=False;continue
                y,j=fields(payload[mode]['rows'][ci*6+slot]);ve=float(np.max(abs(y-ry)/np.maximum(1.,abs(ry))));je=float(np.max(abs(j-rj)/np.maximum(1.,abs(rj))))
                ok=ve<=p['gates'][mode]['value_scaled'] and je<=p['gates'][mode]['jacobian_scaled'];counts[mode]+=int(ok);case_good[mode]&=ok;maxv[mode]=max(maxv[mode],ve);maxj[mode]=max(maxj[mode],je)
            if coordinate=='asset':
                v=cv(state);side=1 if v>b else -1 if v<b else 0;need(side!=0,'Exact asset seam is not a classical two-sided derivative')
                checks=[]
                for ni,n in enumerate(neighbors):
                    bp=cv(n['boundary']);observed=1 if v>bp else -1 if v<bp else 0;need(observed==side,'Parameter finite difference crosses default')
                    checks.append({'boundary_neighbor_index':ni,'side':observed})
                for step in ['1e-18','5e-19']:
                    for sign in [-1,1]:
                        at=v+sign*cv(step)*max(cv('.01'),abs(v));observed=1 if at>b else -1 if at<b else 0;need(observed==side,'State finite difference crosses default')
                        checks.append({'step':step,'sign':sign,'state':str(at),'side':observed})
                asset_details.append({'slot':slot,'state':state,'side':side,'checks':checks})
            if slot==0:
                f0=oracle.fields(theta,0.,'log_distance');samples=[]
                for step in ['1e-18','5e-19']:
                    h=cv(step)*cv('.01');f1=oracle.fields(theta,h,'log_distance');f2=oracle.fields(theta,2*h,'log_distance');derivative=np.asarray([float((-3*v+4*x-y)/(2*h)) for v,x,y in zip(f0,f1,f2)])
                    err=float(np.max(abs(derivative-rj[:,9])/np.maximum(1.,abs(rj[:,9]))));need(err<=1e-12,'Continuation right derivative mismatch')
                    samples.append({'h':str(h),'at_zero':[str(v) for v in f0],'at_h':[str(v) for v in f1],'at_2h':[str(v) for v in f2],'scaled_error':err})
                right.append({'case':point['id'],'samples':samples})
        branches.append({'case':point['id'],'boundary':str(b),'parameter_neighbors':neighbors,'asset_rows':asset_details})
        for mode in MODES:case_pass[mode]+=int(case_good[mode])
        if (ci+1)%8==0:print(json.dumps({'independently_checked_points':ci+1}),flush=True)
    for name,digest in p['source_sha256'].items():need(sha(ROOT/name)==digest,'Source changed during checker')
    need(sha(ROOT/'recovered.so')==p['binary_sha256'],'Binary changed during checker')
    need({name:sha(path) for name,path in bound_paths.items()}==evidence_hashes,'Protocol/manifest/raw evidence changed during checker')
    passed=counts['compensated32']==768 and counts['float64']==768
    return {'schema':'hcsn.recovered-independent-check.v1','gate_passed':passed,'protocol_sha256':expected,'binary_sha256':p['binary_sha256'],
            'evidence_sha256':evidence_hashes,'source_sha256':p['source_sha256'],'manifest_sha256':p['manifest_sha256'],'build_receipt_sha256':p['build_receipt_sha256'],
            'summaries':{mode:{'rows':768,'passed_rows':counts[mode],'passed_points':case_pass[mode],
                              'rejected_or_error_rows':len(native_bad) if mode=='float32' else 0,
                              'max_value_error':maxv[mode] if mode!='float32' or len(native_bad)<768 else None,
                              'max_jacobian_error':maxj[mode] if mode!='float32' or len(native_bad)<768 else None} for mode in MODES},
            'ordinary_fp32_admitted':False,'right_boundary_rows':len(right),'asset_neighbor_checks':sum(len(a['checks']) for b in branches for a in b['asset_rows']),
            'reference_checks':reference_checks,'raw_branch_checks':branches,'raw_right_checks':right,'original_raw_loss_not_replaced':True}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--protocol',type=Path,required=True);p.add_argument('--protocol-sha256',required=True);p.add_argument('--evidence',type=Path,required=True)
    p.add_argument('--oracle-pythonpath',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();need(not a.output.exists(),'Receipt is create-only')
    try:result=check(a.protocol,a.protocol_sha256,a.evidence,a.oracle_pythonpath)
    except (Invalid,ValueError,KeyError,TypeError,OverflowError,OSError) as e:result={'gate_passed':False,'error':str(e)}
    encoded=(json.dumps(result,separators=(',',':'),allow_nan=False)+'\n').encode()
    with a.output.open('xb') as f:f.write(gzip.compress(encoded,mtime=0) if a.output.suffix=='.gz' else encoded)
    print(json.dumps({k:v for k,v in result.items() if k not in ['reference_checks','raw_branch_checks','raw_right_checks']},indent=2));raise SystemExit(0 if result['gate_passed'] else 1)
