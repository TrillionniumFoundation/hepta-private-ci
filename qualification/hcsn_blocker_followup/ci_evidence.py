"""Portable standard-library check of the published decisions and affine counterexample."""
import argparse
from fractions import Fraction
import hashlib
import io
import json
from pathlib import Path
import tempfile
from zipfile import ZipFile
from qualification.hcsn_intervention_value.replay import unpack
from .verify_selector import verify


def read(path):
    return json.loads(path.read_text())


def sha(data):
    return hashlib.sha256(data).hexdigest()


def check(evidence):
    parent=evidence.parent
    inputs=read(evidence/'affine_inputs.json')
    points={q:[float.fromhex(v) for v in r['state_hex']]+[1.] for q,r in inputs.items()}
    with tempfile.TemporaryDirectory() as tmp:
        fresh=Path(tmp)/'bundle'
        unpack(evidence,fresh)
        out=fresh/'outcomes'
        scalar=verify(out)
        seen=set()
        train_dev=read(out/'train_dev_traces.json')
        for split,tr in [('train',train_dev['train_out_of_source']),('dev',train_dev['dev']),('test',read(out/'test_traces.json'))]:
            for i,q in enumerate(tr['query_id']):
                r=inputs[q]
                actual=(split,tr['group'][i],tr['target'][i],tr['free_answer'][i],tr['paid_answer'][i])
                if q in seen or actual!=(r['split'],r['source'],r['target'],r['free'],r['paid']):
                    raise ValueError('stored affine inputs and observed labels differ')
                seen.add(q)
        if seen!=set(inputs):raise ValueError('extra input')
        initial=read(out/'fit.json')['full-svd-.1']
        base=initial['beta']+[initial['bias']]
        seal=read(out/'edit_seal.json')
        if sha((out/'edit_seal.json').read_bytes())!=read(evidence/'edit_seal.json')['sha256']:
            raise ValueError('secondary selection binding')
        if sha((out/'seal.json').read_bytes())!=sha((evidence/'policy_seal.json').read_bytes()):
            raise ValueError('primary selection binding')
        bounded=read(out/'edit_test.json'); count=0
        for method,options in seal['rows'].items():
            for radius,record in options.items():
                delta=record['delta']
                if sum(map(abs,delta))>float(radius)+1e-7:raise ValueError('edit displacement')
                weights=[u+v for u,v in zip(base,delta,strict=True)]
                totals={}
                for q,r in inputs.items():
                    value=sum(a*b for a,b in zip(points[q],weights,strict=True))
                    buy=value>.30
                    hit=r['target']==r['paid' if buy else 'free']
                    vals=totals.setdefault((r['split'],r['source']),[])
                    vals.append((int(buy),int(hit),hit-.30*buy));count+=1
                for (split,g),vals in totals.items():
                    actual=record[split] if split!='test' else bounded['rows'][method][radius]
                    s=actual['sources'][g]
                    if (s['buy']!=sum(v[0] for v in vals) or abs(s['value']-sum(v[2] for v in vals)/len(vals))>1e-12
                            or abs(s['accuracy']-sum(v[1] for v in vals)/len(vals))>1e-12):
                        raise ValueError('bounded head source statistics')
        checked=0
        for name,rec in read(evidence/'joint_capacity.json')['panels'].items():
            if rec['separation']['feasible']:continue
            rows=rec['signed_support'];side=[Fraction(0)]*19;mass=Fraction(0);ids=set()
            for w in rows:
                q=w['query'];r=inputs[q];lam=Fraction(w['positive_rational_weight'])
                rescue=r['paid']==r['target'] and r['free']!=r['target']
                if (lam<=0 or q in ids or r['split'] not in name.split('+') or r['source']!=w['source']
                        or rescue!=w['rescue']):raise ValueError('invalid member')
                ids.add(q);mass+=lam
                signed=lam if rescue else -lam
                side=[v+signed*Fraction(x) for v,x in zip(side,points[q],strict=True)]
            if mass!=1 or any(side):raise ValueError('signed coordinates differ from exact zero')
            checked+=1
        movement=parent/'wait/evidence';parts=read(movement/'archive_parts.json')
        binaries=[]
        for name,v in parts['parts'].items():
            b=(movement/name).read_bytes()
            if sha(b)!=v['sha256'] or len(b)!=v['size']:raise ValueError('sensor fragment differs')
            binaries.append(b)
        archive=b''.join(binaries)
        if sha(archive)!=parts['zip_sha256'] or len(archive)!=parts['zip_size']:raise ValueError('reassembled native archive digest')
        with ZipFile(io.BytesIO(archive)) as z:
            if z.testzip() is not None:raise ValueError('movement archive integrity')
    return {'passed':True,'independent_selector_decisions':scalar['row_decisions'],'bounded_edit_decisions':count,
            'exact_convex_intersections':checked,'registered_queries':len(inputs),'native_archive_verified':True}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('evidence',type=Path)
    print(json.dumps(check(p.parse_args().evidence),indent=2))
