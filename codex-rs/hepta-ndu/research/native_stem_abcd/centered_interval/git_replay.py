"""Hosted Git-only replay of six new proof trees and 120 original binary64 weights.

Prior R21 Git WEIGHTS_HEX.csv fully reconstructs all original final tensors;
no missing conversation ZIP is silently replaced with invented parameters.
"""
import argparse,csv,hashlib,json,sys
from fractions import Fraction as F
from pathlib import Path
import numpy as np
from audit import verify_proof,must
from centered import old

def scores(path):
    with Path(path).open(newline='') as f:
        out={}
        for row in csv.DictReader(f):
            name=row['name'];must(name not in out,'duplicated score identity');out[name]=row
    must(len(out)==120,'incomplete scores')
    return out

def check(proof_root,legacy,reported,full_replay=False):
    proof_root=Path(proof_root);legacy=Path(legacy)
    report=scores(reported);old_report=scores(legacy/'SCORES.csv')
    weights={}
    with (legacy/'WEIGHTS_HEX.csv').open(newline='') as stream:
      for row in csv.DictReader(stream):
        nm=row['name'];must(nm not in weights,'duplicated weight identity');weights[nm]=row
    must(set(weights)==set(report)==set(old_report),'mismatched exact weight census')
    certs={}
    for width in (2,3,4):
      for mode in ('legacy','hybrid'):
        if full_replay:
            certs[width,mode]=verify_proof(proof_root/f'w{width}-{mode}',width,mode)
        else:
            proof=json.loads((proof_root/f'w{width}-{mode}/CERTIFICATE.json').read_text())
            certs[width,mode]=dict(global_lower=float(F(proof['global_lower'])),splits=proof['splits'])
    counts={2:[0,0],3:[0,0],4:[0,0]}
    for name,row in weights.items():
        n=int(row['width']);must(n in counts,'unknown width')
        theta=np.asarray([float.fromhex(v) for v in row['binary64_hex_vector'].split('|')],dtype='<f8')
        must(theta.size==n,'invalid tensor size')
        must(hashlib.sha256(theta.tobytes()).hexdigest()==row['tensor_sha256'],'modified binary64 tensor')
        pt=tuple((F(float(x)),F(float(x))) for x in theta)
        lower,upper=old.cost_bounds(pt)
        l0=F(json.loads((proof_root/f'w{n}-legacy/CERTIFICATE.json').read_text())['global_lower'])
        l1=F(json.loads((proof_root/f'w{n}-hybrid/CERTIFICATE.json').read_text())['global_lower'])
        g0=max(F(0),upper-l0);g1=max(F(0),upper-l1)
        source=report[name];parent=old_report[name]
        must(parent['strict_quality']==source['inherited_R21_classification'],'rewrote historical classification')
        must((g0<=old.TARGET)==(parent['strict_quality']=='True'),'altered original gate')
        must((g1<=old.TARGET)==(source['new_certified']=='True'),'false enhanced gate')
        must((g0<=old.TARGET)==(source['old_certified']=='True'),'false reproduced baseline')
        must(source['final_tensor_sha256']==row['tensor_sha256'],'altered source tensor identity')
        must(abs(float(g0)-float(source['old_strict_gap']))<1e-13,'corrupt original gap')
        must(abs(float(g1)-float(source['new_strict_gap']))<1e-13,'corrupt enhanced gap')
        counts[n][0]+=int(g0<=old.TARGET);counts[n][1]+=int(g1<=old.TARGET)
    must(counts=={2:[20,20],3:[0,19],4:[0,0]},'predefined actual evidence summary differs')
    return dict(cases=len(weights),original_successes=sum(x[0] for x in counts.values()),
                improved_successes=sum(x[1] for x in counts.values()),
                new_certifications=sum(x[1]-x[0] for x in counts.values()),
                source='unchanged Git R21 binary64 hex model index',full_proof_replay=full_replay,
                by_width=counts,production_authorized=False)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--proof-root',type=Path,required=True)
    p.add_argument('--legacy',type=Path,required=True);p.add_argument('--scores',type=Path,required=True)
    p.add_argument('--full-proof-replay',action='store_true')
    a=p.parse_args();print(json.dumps(check(a.proof_root,a.legacy,a.scores,a.full_proof_replay),sort_keys=True))
