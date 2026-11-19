"""R23: exact nested-risk scalar supporting minorants and complete B&B transcripts.

Never assume convexity in the *parameters*: only conditional entropic utility
as a function of terminal residual is strongly convex. Every proof affecting
quantity is Fraction; binary64 affects merely queue priority and runtime.
"""
from __future__ import annotations
import hashlib
import json
import resource
import sys
import time
from fractions import Fraction as F
from heapq import heappop, heappush
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'centered_interval'))
sys.path.insert(0, str(HERE.parent / 'width4_interval'))
import centered
old = centered.old
G = old.G


def residual_range(box, x):
    """Full signed forward residual interval, before the last Bernoulli noise."""
    if x not in (-1, 1) or len(box) not in (2, 3, 4):
        raise ValueError('invalid residual law')
    n = len(box)
    a, b = box[:2]
    c = box[2] if n >= 3 else (F(0), F(0))
    d = box[3] if n >= 4 else (F(0), F(0))
    h1 = old.add(old.scale(a, F(x)), c)
    v = old.add(a, old.scale(b, -1))
    extra = old.add(
        old.add(old.scale(old.square(v), F(1, 4)), old.qr(a, old.ETA)),
        old.qr(v, old.KAPPA),
    )
    r = old.add(old.add(old.mult(b, h1), old.scale(old.mult(d, old.square(h1)), F(1, 4))), extra)
    return old.plus(r, -F(x) - 1)


def phi_anchor(r):
    """Exact rational *interval* for Phi(r), Phi'(r): both preference CE layers.

    Phi(r) includes one X branch and average over the two P0 values.
    In symbols J(theta)=Phi(r_-(theta))+Phi(r_+(theta))+sum(theta^2)/4.
    """
    r = F(r)
    v = centered.D((r, r), ((F(1), F(1)),))
    agg = centered.D.const(1, 0)
    for p0 in (0, 1):
        outer = []
        for e1 in (-1, 1):
            p1 = p0 ^ int(e1 == 1)
            leaves = []
            for e2 in (-1, 1):
                p2 = p1 ^ int(e2 == 1)
                leaves.append((v + F(e2, 10)).square() + F(p2, 50))
            rho1 = F(1, 2) if p1 == 0 else F(1)
            outer.append(F(p1, 20) + centered.dual_ce(leaves[0], leaves[1], rho1) * G)
        rho0 = F(1, 2) if p0 == 0 else F(1)
        agg = agg + centered.dual_ce(outer[0], outer[1], rho0) * (G / F(4))
    return agg.v[0], agg.v[1], agg.g[0]


def precompute_anchors(n):
    if n not in old.CANDIDATES:
        raise ValueError('unknown width')
    theta = tuple((F(z), F(z)) for z in old.CANDIDATES[n])
    return {x: (residual_range(theta, x)[0],) + phi_anchor(residual_range(theta, x)[0])
            for x in (-1, 1)}


def interval_mul_lower(a, b):
    return old.mult(a, b)[0]


def quadratic_tangent_min(delta, gradient):
    """Exact joint minimization of g*delta+G²/2*delta², not loose terms."""
    l,h=delta;gl,gh=gradient
    if l>h or gl>gh:
        raise ValueError('reversed tangent interval')
    possibilities=[]
    for ll,hh,g in ((l,min(h,F(0)),gh),(max(l,F(0)),h,gl)):
        if ll>hh:
            continue
        # The global quadratic vertex is projected exactly to this signed segment.
        stationary=-g/(G*G)
        t=max(ll,min(hh,stationary))
        possibilities.append(g*t+(G*G/F(2))*t*t)
    if not possibilities:
        raise AssertionError('tangent segment cover missing')
    return min(possibilities)


def scalar_minorant(box, anchors):
    """Rigorous sum of 1D supporting parabolae plus exact L2 interval.

    Minimize the *joint* affine-plus-curvature quadratic on each signed
    residual interval; splitting its minima into separate parts is looser.
    """
    if len(box) not in (2, 3, 4) or any(l > h for l, h in box):
        raise ValueError('invalid parameter box')
    lo = sum(old.square(v)[0] for v in box) / 4
    # Phi''(r) >= G**2: inner terminal squared loss curvature >= 2,
    # both entropic risk operators convex and coordinatewise increasing.
    for x in (-1, 1):
        r0, phi_l, _phi_u, grad_iv = anchors[x]
        interval = residual_range(box, x)
        delta = old.plus(interval, -r0)
        lo += phi_l + quadratic_tangent_min(delta, grad_iv)
    return lo


def score(box, mode, anchors=None):
    if mode not in ('risk', 'risk_centered'):
        raise ValueError('unknown certificate method')
    if anchors is None:
        anchors = precompute_anchors(len(box))
    lower = max(old.cost_bounds(box)[0], scalar_minorant(box, anchors))
    if mode == 'risk_centered':
        lower = max(lower, centered.centered_lower(box))
    return lower


def cert(n, out, mode='risk', cap=4000, threshold=F(1, 100)):
    if n not in (2, 3, 4) or mode not in ('risk', 'risk_centered') or cap <= 0 or threshold <= 0:
        raise ValueError('invalid certification configuration')
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    start = time.perf_counter()
    cpu = time.process_time()
    anchors = precompute_anchors(n)
    candidate = tuple((F(v), F(v)) for v in old.CANDIDATES[n])
    candidate_l, candidate_u = old.cost_bounds(candidate)
    if candidate_u >= F(9, 4):
        raise ValueError('outside-cube lower bound not admissible')
    root = tuple((-old.DOMAIN, old.DOMAIN) for _ in range(n))
    root_lower = score(root, mode, anchors)
    heap = [(float(root_lower), 0, root_lower, root)]
    seq = splits = pruned = 0
    peak = 1
    progress = []
    with (out / 'SPLITS.jsonl').open('x') as stream:
        while heap and splits < cap:
            current_best = min([candidate_l] + [e[2] for e in heap])
            if candidate_u - current_best <= threshold:
                break
            _, idx, lower, box = heappop(heap)
            axis, child_l, child_r = old.bisect(box)
            line = dict(parent_id=idx, parent_box=old.encode_box(box), parent_lower=str(lower),
                        axis=axis, children=[])
            for child in (child_l, child_r):
                bound = score(child, mode, anchors)
                seq += 1
                keep = bound < candidate_u
                if keep:
                    heappush(heap, (float(bound), seq, bound, child))
                else:
                    pruned += 1
                line['children'].append(dict(id=seq, box=old.encode_box(child),
                                             lower=str(bound), kept=keep))
            stream.write(json.dumps(line, separators=(',', ':')) + '\n')
            splits += 1
            peak = max(peak, len(heap))
            if splits in (100, 500, 1000, 2000, 4000):
                best = min([candidate_l] + [e[2] for e in heap])
                progress.append(dict(splits=splits, regret=str(candidate_u-best),
                                     cpu=time.process_time()-cpu, frontier=len(heap)))
    with (out/'FRONTIER.jsonl').open('x') as stream:
        for _,idx,low,box in sorted(heap,key=lambda e:e[1]):
            stream.write(json.dumps(dict(id=idx, lower=str(low), box=old.encode_box(box)),
                                    separators=(',',':'))+'\n')
    final_lower = min([candidate_l]+[e[2] for e in heap])
    gap = max(F(0), candidate_u-final_lower)
    meta = dict(schema='hepta.ndu.r23.risk-scalar-minorants.v1',width=n,mode=mode,
        parent_r22='575b1121dfdcc9b1089cb9e915d0e0c037f1611d',
        candidate=old.CANDIDATES[n],candidate_lower=str(candidate_l),candidate_upper=str(candidate_u),
        root_lower=str(root_lower),root_box=old.encode_box(root),global_lower=str(final_lower),
        regret_upper=str(gap),threshold=str(threshold),node_cap=cap,splits=splits,pruned=pruned,
        frontier_count=len(heap),peak_frontier=peak,qualifies=gap<=threshold,
        failure_reason=None if gap<=threshold else 'precommitted split cap reached',
        anchors={str(x):dict(r0=str(t[0]),phi_lower=str(t[1]),phi_upper=str(t[2]),
                derivative=[str(t[3][0]),str(t[3][1])]) for x,t in anchors.items()},
        rigorous_float_free_scores=True,priority_only_float=True,trainings=0,
        continuous_law_global_certificate=False,model_weight_global_uniqueness=False,
        elapsed_wall=time.perf_counter()-start,elapsed_cpu=time.process_time()-cpu,
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        split_sha256=hashlib.sha256((out/'SPLITS.jsonl').read_bytes()).hexdigest(),
        frontier_sha256=hashlib.sha256((out/'FRONTIER.jsonl').read_bytes()).hexdigest(),progress=progress)
    (out/'CERTIFICATE.json').write_text(json.dumps(meta,indent=2,sort_keys=True)+'\n')
    print(json.dumps({x:meta[x] for x in ('width','mode','splits','regret_upper','qualifies','elapsed_cpu')},sort_keys=True),flush=True)
    return meta

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('--width',type=int,choices=(2,3,4),required=True)
    p.add_argument('--mode',choices=('risk','risk_centered'),required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    cert(a.width,a.out,mode=a.mode)
