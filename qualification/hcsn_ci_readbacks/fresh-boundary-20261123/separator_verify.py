"""Post-outcome exact affine-separation capacity on the 48 released first-prefix rows.

python separator_verify.py                    # rebuild features from released data and verify JSON
python separator_verify.py --stored-only      # two exact arithmetic checks, Python stdlib only
python separator_verify.py --write            # regenerate the certificate from the frozen inputs

The 17-row basis was found by a numerical LP. Only exact feasibility and duality
checks are used to certify the result. All 19 coordinates, including bias, cost L1.
"""
import argparse
import base64
from fractions import Fraction as F
from hashlib import sha256
from io import BytesIO
import json
from math import comb, lcm
from pathlib import Path
from struct import iter_unpack
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
DEST = HERE / 'separator-certificate.json'
MATRIX_WIDTH = 19
PRICE = F(3, 10)
SOURCE_FILES = {
    'audio.npz': 'f4d1cd97b64b80cd8dfee99b61d6bf5b6caa2c5bbe8e66d66251e7e33f660480',
    'free.npz': '5be8322e0e256f70119facde0b312b1d878b0ca76d870b32bb61e80b5be8d6c9',
    'camera.npz': 'c72730270654a850e5c5939e327d24eeae3d6d2a04eec3fda349f8f83f14e5fb',
    'roster.json': 'd4a0146197403ffe5e425e09593968329fde5db7e063f1add87df6ee190edcd9',
    'actions.json': 'b76f924fef28528cefcab1bbe97f98e4a9e4627d841ed7c97f1668536496905a',
    'front_weights.json': '8feca0900f68d8041a963b449b8b641f1d8b9bf747ad823a968f7efcf429bd66',
    'fit.json': '5ab2265238dd1085e26e6c57bc2cf3f3d0f5a70b7128d30efe0eb546231a51de',
}
BASIS_ROWS = [0,3,5,6,8,9,10,20,22,24,25,33,35,36,38,43,46]
BASIS_COLS = [0,1,2,3,4,6,7,8,9,10,11,12,13,14,15,16,17]
BASIS_SIGNS = [1,1,1,1,-1,-1,-1,-1,1,1,1,-1,-1,1,1,-1,-1]
STRICT_NUMERATORS = [-2006,4113,1070,23442,3033,12024,-17631,-1282,-2139,-19514,-6290,10123,-1039,15048,5580,-7907,-620,7272,28125]
UTILITY_DELTA_NUMERATORS = [0,0,0,44981304,0,-95531148,0,0,0,0,0,9308000,-139416516,0,218952670,78676745,-190553278,0,58163903]
UTILITY_EXPECTED = '100000001011000000001100111100000111100011011111'


def dot(a,b):
    return sum((u*v for u,v in zip(a,b,strict=True)),F())


def packed_data():
    import numpy as np
    qual=HERE.parents[1]
    def member(archive, name):
        with ZipFile(archive) as z:
            b=z.read(name)
        key=name.split('/')[-1]
        assert sha256(b).hexdigest()==SOURCE_FILES[key],key
        return b
    old=qual/'hcsn_intervention_value/evidence/records-04.zip'
    af=json.loads(member(old,'primary/discovery/front_weights.json'))['final']['audio']
    fit=json.loads(member(qual/'hcsn_blocker_followup/evidence/locked_heads.zip','fit.json'))['full-svd-.1']
    raw=HERE/'evaluation.zip'
    def arrays(n):
        with np.load(BytesIO(member(raw,n)),allow_pickle=False) as v:
            return dict(v)
    rows=json.loads(member(raw,'roster.json'))
    free=arrays('free.npz')
    cam=arrays('camera.npz')
    assert list(cam['query_id'])==[r['query_id'] for r in rows]
    z=np.clip((arrays('audio.npz')['audio']-af['center'])/af['scale'],-8,8)
    project=np.linalg.qr(np.random.default_rng(420111).normal(size=(52,8)),mode='reduced')[0]
    f,g=free['scores'][:,0,1],free['gallery_audio'][:,0,1]
    m,v=2*f-1,2*g-1
    raw18=np.c_[m,abs(m),m*m,f>=.5,v,abs(v),abs(m-v),m*v,(f>=.5)!=(g>=.5),m*abs(m),(z@project)[:,0,:]]
    X=np.c_[np.clip((raw18-fit['mean'])/fit['std'],-5,5),np.ones(len(rows))].astype('<f8')
    assert X.shape==(48,19)
    original=np.r_[fit['beta'],fit['bias']]
    assert (X@original>.30).astype(int).tolist()==json.loads(member(raw,'actions.json'))['svd']['action']
    free_guess=free['scores'][:,0].argmax(-1); paid_guess=cam['probability'][:,0].argmax(-1)
    records=[dict(query_id=r['query_id'],group=r['group'],free_hit=bool(a==r['label']),paid_hit=bool(b==r['label']))
             for r,a,b in zip(rows,free_guess,paid_guess,strict=True)]
    buf=X.tobytes(order='C')
    return dict(shape=[48,19],design_storage='little-endian IEEE binary64, C row order, final column 1',
                source_sha256=SOURCE_FILES,design_sha256=sha256(buf).hexdigest(),
                design_f64_base64=base64.b64encode(buf).decode(),old_svd_weight_hex=[float(x).hex() for x in original],
                rows=records)


def unpack(data):
    buf=base64.b64decode(data['design_f64_base64'],validate=True)
    assert sha256(buf).hexdigest()==data['design_sha256'] and len(buf)==48*19*8
    X=[[F(k) for k in row] for row in iter_unpack('<19d',buf)]
    old=[F(float.fromhex(s)) for s in data['old_svd_weight_hex']]
    sign=[1 if r['paid_hit'] and not r['free_hit'] else -1 for r in data['rows']]
    assert len(X)==len(sign)==48 and sign.count(1)==17 and all(row[-1]==1 for row in X)
    return X,old,sign


def solve(matrix,rhs):
    """Gauss-Jordan on a fixed rational basis, with exact pivot checks."""
    n=len(rhs)
    a=[list(r)+[F(v)] for r,v in zip(matrix,rhs,strict=True)]
    for j in range(n):
        pivot=next(i for i in range(j,n) if a[i][j])
        a[j],a[pivot]=a[pivot],a[j]
        a[j]=[c/a[j][j] for c in a[j]]
        for i in range(n):
            if i!=j and a[i][j]:
                factor=a[i][j]
                a[i]=[u-factor*v for u,v in zip(a[i],a[j],strict=True)]
    return [row[-1] for row in a]


def exact_sign(v):
    wins=sum(x>0 for x in v);n=sum(x!=0 for x in v)
    return F(sum(comb(n,k) for k in range(wins,n+1)),2**n)


def utility(data,actions):
    rows=data['rows']
    vals=[10*int(r['paid_hit'] if a else r['free_hit'])-3*a for r,a in zip(rows,actions,strict=True)]
    groups=sorted({r['group'] for r in rows})
    df={};dp={}
    for g in groups:
        ii=[i for i,r in enumerate(rows) if r['group']==g]
        assert len(ii)==4
        df[g]=F(sum(vals[i]-10*rows[i]['free_hit'] for i in ii),40)
        dp[g]=F(sum(vals[i]-(10*rows[i]['paid_hit']-3) for i in ii),40)
    return dict(buys=sum(actions),rescues=sum(a and not r['free_hit'] and r['paid_hit'] for a,r in zip(actions,rows)),
                redundantly_buy_when_both_correct=sum(a and r['free_hit'] and r['paid_hit'] for a,r in zip(actions,rows)),
                source_macro_utility=str(F(sum(vals),480)),mean_minus_free=str(sum(df.values())/12),
                mean_minus_paid=str(sum(dp.values())/12),worst_minus_free=str(min(df.values())),
                one_sided_sign_p_vs_free_paid=[str(exact_sign(df.values())),str(exact_sign(dp.values()))])


def certificate(data):
    X,base,sign=unpack(data)
    A=[[s*x for x in row] for s,row in zip(sign,X)]
    b=[s*(dot(row,base)-PRICE) for s,row in zip(sign,X)]
    ids=[r['query_id'] for r in data['rows']]
    strict=[F(x,100000) for x in STRICT_NUMERATORS]
    margins=[s*(dot(row,strict)-PRICE) for row,s in zip(X,sign)]
    assert min(margins)>0
    cost=sum(abs(w-o) for w,o in zip(strict,base))
    # For A delta + b >= 0, any lambda>=0 with ||A' lambda||_inf<=1 certifies
    # ||delta||_1 >= -lambda' b. Matching primal feasibility proves sharpness.
    square=[[A[i][j] for j in BASIS_COLS] for i in BASIS_ROWS]
    solution=solve(square,[-b[i] for i in BASIS_ROWS])
    weak=[F(0)]*19
    for j,x in zip(BASIS_COLS,solution,strict=True):weak[j]=x
    assert all(base_margin+dot(a,weak)>=0 for a,base_margin in zip(A,b))
    dual=solve(list(zip(*square)),BASIS_SIGNS)
    assert all(v>0 for v in dual)
    magnitude=max(abs(dot([A[i][j] for i in BASIS_ROWS],dual)) for j in range(19))
    lower=-dot([b[i] for i in BASIS_ROWS],dual)
    assert magnitude==1 and lower==sum(map(abs,weak)) and 1<lower<cost
    assert any(sign[i]==1 for i in BASIS_ROWS)
    binary_price=F(float(.30))
    b64=[s*(dot(row,base)-binary_price) for s,row in zip(sign,X)]
    lower64=-dot([b64[i] for i in BASIS_ROWS],dual)
    assert lower64>1 and all(s*(dot(row,strict)-binary_price)>0 for s,row in zip(sign,X))
    total=sum(dual)
    upper_unit=(1-lower)/total
    assert upper_unit<0
    d=[F(x,10**9) for x in UTILITY_DELTA_NUMERATORS]
    alt=[a+b for a,b in zip(base,d)]
    edge=[dot(row,alt)-PRICE for row in X]
    actions=[int(x>0) for x in edge]
    assert ''.join(map(str,actions))==UTILITY_EXPECTED
    alt_perf=utility(data,actions)
    assert (alt_perf['buys'],alt_perf['rescues'],alt_perf['redundantly_buy_when_both_correct'])==(21,17,4)
    assert alt_perf['one_sided_sign_p_vs_free_paid']==['1/256','1/1024'] and alt_perf['worst_minus_free']=='0'
    return dict(
        scope='Post-outcome capacity of this fixed first-prefix design on 48 known windows only.',
        decision='buy iff affine score exceeds price 3/10; original machine-comparison threshold checked separately',
        fixed_price=str(PRICE), old_machine_threshold=str(binary_price), required_buys=17,required_stops=31,
        strict_witness=dict(weight_numerators=STRICT_NUMERATORS,weight_denominator=100000,
            cost_l1_from_old_svd=str(cost),minimum_signed_margin=str(min(margins)),
            signed_margins_by_query=dict(zip(ids,map(str,margins))),outcome=utility(data,[int(s==1) for s in sign])),
        perfect_action_l1_lower_bound=dict(
            scope='Exact infimum for exact 3/10; a convex combination of the weak optimum and strict witness approaches it. A positive dual multiplier on a buy row rules out attainment with strict buys.',
            weak_optimum_delta=[str(v) for v in weak],infimum=str(lower),infimum_decimal=float(lower),
            dual_multipliers={ids[i]:str(v) for i,v in zip(BASIS_ROWS,dual)},dual_infinity_norm=str(magnitude),
            objective_and_primal_cost_agree=True,unit_ball_uniform_signed_margin_upper=str(upper_unit),
            machine_threshold_certified_l1_lower_bound=str(lower64),unit_ball_perfect_classification=False),
        practical_utility_witness=dict(
            scope='Separately discovered using all 48 released outcomes. This head buys four correct-free windows.',
            delta_numerators=UTILITY_DELTA_NUMERATORS,delta_denominator=10**9,
            cost_l1_from_old_svd=str(sum(map(abs,d))),minimum_buy_margin=str(min(x for x in edge if x>0)),
            minimum_abs_margin=str(min(map(abs,edge))),actions=actions,
            outcome=alt_perf),input=data)


def integer_recheck(doc):
    """Independently clear common denominators and use signed integer products."""
    X,base,sign=unpack(doc['input'])
    def lift(vals):
        den=lcm(*(v.denominator for v in vals))
        return [v.numerator*(den//v.denominator) for v in vals],den
    flat,dx=lift([v for row in X for v in row])
    Z=[flat[i:i+19] for i in range(0,len(flat),19)]
    def clear_margin(w,p):
        lifted,d=lift(w+[p])
        return [sum(x*t for x,t in zip(row,lifted[:-1]))-dx*lifted[-1] for row in Z],dx*d
    ids=[r['query_id'] for r in doc['input']['rows']]
    witness=doc['strict_witness']
    w=[F(n,witness['weight_denominator']) for n in witness['weight_numerators']]
    mm,dd=clear_margin(w,PRICE)
    for i,(s,t) in enumerate(zip(sign,mm)):
        stored=F(witness['signed_margins_by_query'][ids[i]])
        assert s*t>0 and s*t*stored.denominator==dd*stored.numerator
    bound=doc['perfect_action_l1_lower_bound']
    ds=[F(s) for s in bound['weak_optimum_delta']]
    weaknum,weakden=clear_margin([v+d for v,d in zip(base,ds)],PRICE)
    assert all(s*t>=0 for s,t in zip(sign,weaknum))
    lam,ld=lift([F(bound['dual_multipliers'].get(k,'0')) for k in ids])
    negbound=F(bound['infimum'])
    assert all(l>=0 for l in lam) and any(l>0 and s>0 for l,s in zip(lam,sign))
    for j in range(19):
        assert abs(sum(l*s*r[j] for l,s,r in zip(lam,sign,Z)))<=ld*dx
    bn,bd=clear_margin(base,PRICE)
    negative_sum=-sum(l*s*t for l,s,t in zip(lam,sign,bn))
    assert negative_sum*negbound.denominator==ld*bd*negbound.numerator
    numer,den=lift(ds)
    assert sum(map(abs,numer))*negbound.denominator==den*negbound.numerator and negbound>1
    extra=doc['practical_utility_witness']
    k=[F(n,extra['delta_denominator']) for n in extra['delta_numerators']]
    nums,_=clear_margin([a+b for a,b in zip(base,k)],PRICE)
    assert [int(x>0) for x in nums]==extra['actions']


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    choice=cli.add_mutually_exclusive_group()
    choice.add_argument('--write',action='store_true')
    choice.add_argument('--stored-only',action='store_true')
    args=cli.parse_args()
    published=None if args.write else json.loads(DEST.read_bytes())
    data=published['input'] if args.stored_only else packed_data()
    computed=certificate(data)
    integer_recheck(computed)
    if args.write:
        DEST.write_text(json.dumps(computed,sort_keys=True,indent=2)+'\n')
    else:
        assert computed==published
    print(f"48 strict margins, 17 dual rows, 19 dual coordinates; exact infimum {computed['perfect_action_l1_lower_bound']['infimum_decimal']:.12f}; SHA-256 {sha256(DEST.read_bytes()).hexdigest()}")


if __name__=='__main__':
    main()
