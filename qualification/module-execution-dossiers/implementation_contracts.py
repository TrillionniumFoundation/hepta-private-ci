#!/usr/bin/env python3
"""Read-only implementation-document checks and bounded qualification oracles.

No API here authenticates a production principal, grants capabilities, installs
artifacts or proves native/physical/longitudinal behavior. Repository verification
requires a complete clean checkout; bundle verification explicitly does not.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import subprocess
import sys
import unittest
from fractions import Fraction
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REL = Path('qualification/module-execution-dossiers')
LANES = {'A': 'LANE-A-FOUNDATION', 'B': 'LANE-B-RUNTIME', 'C': 'LANE-C-MEMORY',
         'D': 'LANE-D-OBJECTIVE-VALUE', 'E': 'LANE-E-LEARNING',
         'F': 'LANE-F-ADAPTIVE-POLICY', 'G': 'LANE-G-ENGINEERING'}
COUNTS = {'A': 7, 'B': 11, 'C': 9, 'D': 3, 'E': 4, 'F': 5, 'G': 1}
PHASES = ('prepared', 'admission_stopped', 'drained', 'old_writer_fenced',
          'snapshotted', 'migrated', 'validated', 'new_writer_fenced',
          'route_published', 'retired')

class Invalid(ValueError):
    """The declared bounded fixture/profile is invalid or unsupported."""

def integer(value: Any, lo: int = 0, hi: int = (1 << 63)-1) -> int:
    if type(value) is not int or not lo <= value <= hi:
        raise Invalid('integer range/type')
    return value

def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, val in items:
        if key in out:
            raise Invalid('duplicate JSON key: ' + key)
        out[key] = val
    return out

def read_json(path: Path) -> Any:
    if path.stat().st_size > 2_000_000:
        raise Invalid('document byte budget')
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=pairs,
                      parse_constant=lambda v: (_ for _ in ()).throw(Invalid(v)))

def blob(data: bytes) -> str:
    return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()

def next_sequence(value: int, maximum: int = (1 << 63)-1) -> int:
    integer(maximum, 1)
    integer(value, 0, maximum)
    if value == maximum:
        raise Invalid('sequence exhaustion before mutation')
    return value+1

def rescale(value: int, source: int, target: int, rounding: str = 'ties_even') -> int:
    integer(value, -(1 << 63), (1 << 63)-1)
    integer(source, 1); integer(target, 1)
    product = value*target
    if not -(1 << 127) <= product < (1 << 127):
        raise Invalid('wide overflow')
    q, r = divmod(abs(product), source)
    if rounding == 'ties_even':
        q += int(2*r > source or (2*r == source and q % 2 == 1))
    elif rounding != 'toward_zero':
        raise Invalid('rounding profile')
    result = q if product >= 0 else -q
    return integer(result, -(1 << 63), (1 << 63)-1)

def covariance_2d(c: tuple[int, int, int], b: tuple[int, int]) -> tuple[Fraction, Fraction]:
    """Exact 2x2 symmetric positive-definite algebra oracle, not estimation."""
    if len(c) != 3 or len(b) != 2:
        raise Invalid('covariance shape')
    a, x, d = (Fraction(v) for v in c)
    det = a*d-x*x
    if a <= 0 or det <= 0:
        raise Invalid('singular/indefinite covariance')
    p, q = map(Fraction, b)
    return ((p*d-q*x)/det, (q*a-p*x)/det)

def centered_scalar(samples: list[tuple[Fraction, Fraction]]) -> Fraction:
    if not 2 <= len(samples) <= 4096:
        raise Invalid('sample count')
    n = len(samples)
    mean_m = sum(Fraction(m) for m, _ in samples)/n
    mean_u = sum(Fraction(u) for _, u in samples)/n
    cov = sum((Fraction(m)-mean_m)**2 for m, _ in samples)/n
    cross = sum((Fraction(u)-mean_u)*(Fraction(m)-mean_m) for m, u in samples)/n
    if cov <= 0:
        raise Invalid('unsupported covariance')
    return cross/cov

def sequential_dr(rows: list[dict[str, Fraction]], terminal: Fraction = Fraction(0)) -> Fraction:
    if not 1 <= len(rows) <= 128:
        raise Invalid('trajectory horizon')
    result = Fraction(terminal)
    for row in reversed(rows):
        if set(row) != {'v','q','reward','behavior','evaluation','discount'}:
            raise Invalid('trajectory fields')
        pb, pe, g = (Fraction(row[k]) for k in ('behavior','evaluation','discount'))
        if not 0 < pb <= 1 or not 0 <= pe <= 1 or not 0 <= g <= 1:
            raise Invalid('support/discount')
        result = Fraction(row['v']) + pe/pb*(Fraction(row['reward'])+g*result-Fraction(row['q']))
    return result

def ess_floor(n: int, floors: list[int]) -> int:
    integer(n, 1, 1_000_000)
    if len(floors) > 128:
        raise Invalid('threshold count')
    return max([400, (n+9)//10] + [integer(v, 0, 1_000_000) for v in floors])

def threshold_intersection(rows: list[dict[str, Any]]) -> tuple[Fraction, Fraction]:
    if not 1 <= len(rows) <= 128:
        raise Invalid('threshold count')
    expected = ('unit', 'estimand', 'scope')
    for row in rows:
        if set(row) != set(expected) | {'lower','upper'}:
            raise Invalid('threshold fields')
        if any(not isinstance(row[k], str) or not row[k] for k in expected):
            raise Invalid('threshold identity')
        if any(row[k] != rows[0][k] for k in expected):
            raise Invalid('incompatible thresholds')
    lower = max(Fraction(row['lower']) for row in rows)
    upper = min(Fraction(row['upper']) for row in rows)
    if lower > upper:
        raise Invalid('empty threshold intersection')
    return lower, upper

def topo(nodes: list[str], edges: list[tuple[str, str]]) -> list[str]:
    if not 1 <= len(nodes) <= 256 or len(set(nodes)) != len(nodes) or len(edges) > 4096:
        raise Invalid('graph bounds/duplicates')
    if any(not isinstance(n, str) or not n for n in nodes):
        raise Invalid('node identity')
    outgoing = {n:set() for n in nodes}; incoming = dict.fromkeys(nodes, 0)
    for a,b in edges:
        if a not in outgoing or b not in outgoing or b in outgoing[a]:
            raise Invalid('unknown/duplicate edge')
        outgoing[a].add(b); incoming[b] += 1
    ready = sorted(n for n in nodes if incoming[n] == 0); ordered=[]
    while ready:
        n=ready.pop(0); ordered.append(n)
        for other in sorted(outgoing[n]):
            incoming[other]-=1
            if incoming[other] == 0:
                ready.append(other); ready.sort()
    if len(ordered) != len(nodes):
        raise Invalid('initialization/fallback cycle')
    return ordered

def partition(source: list[str], targets: dict[str,list[str]]) -> None:
    if not 1 <= len(source) <= 4096 or len(set(source)) != len(source) or not 1 <= len(targets) <= 32:
        raise Invalid('partition bounds/identity')
    flat = [v for records in targets.values() for v in records]
    if len(flat) != len(set(flat)) or set(flat) != set(source):
        raise Invalid('non-total or non-disjoint authoritative partition')

def handoff(phase: str, old_valid: bool, new_valid: bool, old_open: bool, new_open: bool,
            old_fence: int, new_fence: int, unknown_effects: int = 0) -> None:
    if phase not in PHASES or any(type(v) is not bool for v in (old_valid,new_valid,old_open,new_open)):
        raise Invalid('phase/boolean')
    integer(old_fence); integer(new_fence); integer(unknown_effects)
    if new_fence <= old_fence:
        raise Invalid('non-advancing fence')
    pos = PHASES.index(phase)
    expected = (pos < 3, pos >= 7, pos == 0, pos >= 8)
    if (old_valid,new_valid,old_open,new_open) != expected:
        raise Invalid('lease/admission mismatch')
    if pos >= 3 and unknown_effects:
        raise Invalid('unresolved effect at cutover')

def rollback_required_delta(new_writes: int, preserved_delta: int, compatible: bool, revoked: bool) -> None:
    integer(new_writes); integer(preserved_delta)
    if type(compatible) is not bool or type(revoked) is not bool or not compatible or revoked:
        raise Invalid('ineligible predecessor')
    if preserved_delta != new_writes:
        raise Invalid('rollback loses accepted successor history')

def admit(entry_epoch: int, current_epoch: int, authorized_digest: str, final_digest: str) -> None:
    integer(entry_epoch); integer(current_epoch)
    if any(re.fullmatch('[0-9a-f]{64}', d) is None for d in (authorized_digest,final_digest)):
        raise Invalid('digest')
    if entry_epoch != current_epoch or authorized_digest != final_digest:
        raise Invalid('revoked or changed final payload')

def response_time(c: int, blocking: int, deadline: int, higher: list[tuple[int,int]]) -> int:
    integer(c,1,1_000_000); integer(blocking,0,1_000_000); integer(deadline,1,10_000_000)
    if len(higher) > 32:
        raise Invalid('task count')
    for hc,period in higher:
        integer(hc,1,1_000_000); integer(period,1,10_000_000)
    value=c+blocking
    for _ in range(64):
        if value > deadline:
            raise Invalid('deadline miss')
        nxt=c+blocking+sum(((value+t-1)//t)*hc for hc,t in higher)
        if nxt == value:
            return value
        value=nxt
    raise Invalid('response-time solve exhausted')

def cart_step(x: Fraction, v: Fraction, dt: Fraction = Fraction(1,100)) -> tuple[Fraction,Fraction,Fraction]:
    x,v,dt = Fraction(x),Fraction(v),Fraction(dt)
    if dt != Fraction(1,100) or abs(x)>1 or abs(v)>1:
        raise Invalid('outside cart pilot profile')
    u=max(Fraction(-2),min(Fraction(2),-4*x-4*v))
    return x+dt*v, v+dt*u, u

def cart_brake(x: Fraction, v: Fraction) -> tuple[Fraction,Fraction,Fraction]:
    """Ideal simulator-only brake; no physical stop or robustness certificate."""
    x,v=Fraction(x),Fraction(v)
    dt=Fraction(1,100)
    if abs(x)>1 or abs(v)>1 or abs(x)+v*v/4+abs(v)*dt>1:
        raise Invalid('outside qualified ideal stopping margin')
    u=max(Fraction(-2),min(Fraction(2),-v/dt))
    return x+dt*v,v+dt*u,u

def inside(root: Path, relative: str) -> Path:
    if not isinstance(relative,str) or not relative or Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise Invalid('unsafe repository path')
    path=(root/relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise Invalid('path escape')
    return path

def verify_bundle(root: Path) -> dict[str, Any]:
    base=root/REL
    profiles=read_json(base/'IMPLEMENTATION_PROFILES.json')
    if profiles['schema'] != 'hepta.module-implementation-profiles.v1' or type(profiles['schemaVersion']) is not int or profiles['schemaVersion'] != 1 or profiles['planId'] != 'HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN' or profiles['planVersion'] != '8.0.0':
        raise Invalid('profile identity')
    rows=profiles['modules']
    if profiles['moduleCount'] != 40 or len(rows) != 40 or len({r['module'] for r in rows}) != 40:
        raise Invalid('module closed world')
    claim_keys={'productTestsExecuted','deploymentQualified','longitudinalEfficacy','functionalBiomimicry','selfIteration','autonomousPropagation','independentAcceptance','allGapsClosed'}
    if set(profiles['claimBoundary']) != claim_keys or any(v is not False for v in profiles['claimBoundary'].values()):
        raise Invalid('positive document capability claim')
    if {lane:sum(r['lane']==lane for r in rows) for lane in COUNTS} != COUNTS:
        raise Invalid('lane counts')
    for row in rows:
        mid=row['module']
        if not re.fullmatch('[a-z]+[.][a-z]+',mid) or row['lane'] not in LANES:
            raise Invalid('module/lane identity')
        if row['guide'] != f'docs/modules/{mid}/TECHNICAL.md' or row['design'] != str(REL/'detail'/f'{mid}.md'):
            raise Invalid('stable document binding')
        for key in ('apiContract','stateAndEncoding','linearizationAndRecovery','algorithmAndBounds','acceptanceOracle'):
            if not isinstance(row[key],str) or len(row[key]) < 80:
                raise Invalid(mid+': missing concrete '+key)
        if row['implementationState'] != 'specified_not_product_evidence' or row['nativeMappingRequired'] is not True or row['productTestsExecuted'] is not False or row['deploymentQualified'] is not False:
            raise Invalid(mid+': false source or deployment closure')
        if not row['declaredRoots'] or not row['workPackages']:
            raise Invalid(mid+': absent canonical references')
        for path in row['declaredRoots']:
            inside(root,path)
    # Paths whose prior versions are retained need not be present in an exported
    # partial bundle. All newly delivered shared specifications must be present.
    for path in profiles['readWith']:
        if path.endswith('/README.md'):
            continue
        if not inside(root,path).is_file():
            raise Invalid('missing companion: '+path)
    completion=read_json(base/'IMPLEMENTATION_COMPLETION.json')
    if completion['allGapsClosed'] is not False or completion['independentReviewPassed'] is not False:
        raise Invalid('false global closure')
    reqs=completion['designRequirements']
    if len(reqs) != 16 or [r['id'] for r in reqs] != [f'IMP-{i:02d}' for i in range(1,17)]:
        raise Invalid('design requirement index')
    for req in reqs:
        if req['state'] != 'specified' or not req['remainingEvidence']:
            raise Invalid('design/evidence conflation')
        for path in req['documents']:
            if not inside(root,path).is_file():
                raise Invalid('missing traced document')
    if completion['externalGateIds'] != [f'RDY-EXT-{i:03d}' for i in range(1,10)]:
        raise Invalid('external gate projection')
    native=read_json(base/'NATIVE_BINDINGS.json')
    if native['evidenceClass'] != 'source_observation_only' or native['productExecutionProved'] is not False:
        raise Invalid('source/consumer conflation')
    for row in native['observations']:
        if not re.fullmatch('[0-9a-f]{40}',row['blobSha']) or not row['exports']:
            raise Invalid('source observation identity')
        inside(root,row['path'])
    return {'kind':'documentation_bundle_conformance','modules':40,'designRequirements':16,
            'sourceObservations':len(native['observations']),'repositoryBindingsChecked':False,
            'nativeProductTestsExecuted':False,'independentReview':False,'allGapsClosed':False}

def git(root: Path,*args: str) -> bytes:
    result=subprocess.run(['git','-C',str(root),*args],check=False,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
    if result.returncode:
        raise Invalid('required Git read failed: '+' '.join(args))
    return result.stdout

def verify_repository(root: Path) -> dict[str,Any]:
    if Path(git(root,'rev-parse','--show-toplevel').decode().strip()).resolve() != root.resolve():
        raise Invalid('complete repository root required')
    result=verify_bundle(root)
    modules=read_json(root/'docs/modules/MODULES.json')['modules']
    bindings=read_json(root/'docs/modules/SOURCE_BINDINGS.json')['bindings']
    packages=read_json(root/'docs/delivery/WORK_PACKAGES.json')['packages']
    ready=read_json(root/'docs/readiness/READINESS.json')
    canonical={r['id'] for r in modules}; roots={r['module']:r['declaredRoots'] for r in bindings}
    binding_by_module={r['module']:r for r in bindings}
    lanes={m:l['id'] for l in ready['implementationLanes'] for m in l['modules']}
    profiles=read_json(root/REL/'IMPLEMENTATION_PROFILES.json')
    if canonical != {r['module'] for r in profiles['modules']} or len(modules) != 40 or len(bindings) != 40:
        raise Invalid('canonical module coverage')
    known_packages={r['id'] for r in packages}
    for row in profiles['modules']:
        mid=row['module']
        if row['declaredRoots'] != roots[mid] or LANES[row['lane']] != lanes[mid] or not set(row['workPackages']) <= known_packages:
            raise Invalid(mid+': canonical root/lane/package drift')
        binding=binding_by_module[mid]
        existing=set(binding['existingDeclaredRoots']); missing=set(binding['missingDeclaredRoots'])
        if existing & missing or existing | missing != set(row['declaredRoots']):
            raise Invalid(mid+': source materialization partition drift')
        for path in existing | {row['guide'],row['design']}:
            if not inside(root,path).exists():
                raise Invalid(mid+': missing registered existing path')
        for path in missing:
            if inside(root,path).exists() or binding['bootstrapWorkPackage'] not in known_packages:
                raise Invalid(mid+': missing-root or bootstrap declaration drift')
    for row in read_json(root/REL/'NATIVE_BINDINGS.json')['observations']:
        data=inside(root,row['path']).read_bytes()
        if blob(data) != row['blobSha'] or any(re.search(r'\b'+re.escape(s)+r'\b',data.decode()) is None for s in row['exports']):
            raise Invalid('native observation drift; re-review required: '+row['path'])
    # Verify the revised canonical NDU document is bound to its actual bytes.
    algorithm=read_json(root/'docs/learning/ALGORITHM_SPECS.json')
    ndu=next(d for d in algorithm['documents'] if d['id']=='ALG-NDU-FBSDE')
    if blob(inside(root,ndu['path']).read_bytes()) != ndu['blobSha']:
        raise Invalid('canonical NDU blob mismatch')
    required=profiles['readWith']+[str(REL/name) for name in ('IMPLEMENTATION_PROFILES.json','IMPLEMENTATION_COMPLETION.json','NATIVE_BINDINGS.json','COGNITIVE_STORE.sql','implementation_contracts.py','test_implementation_contracts.py')]
    for path in required:
        if git(root,'show','HEAD:'+path) != inside(root,path).read_bytes():
            raise Invalid('uncommitted candidate document: '+path)
    result.update(kind='repository_document_binding_conformance',repositoryBindingsChecked=True,
                  sourceSha=git(root,'rev-parse','HEAD').decode().strip())
    return result

def self_test(base: Path) -> int:
    suite=unittest.defaultTestLoader.discover(str(base),pattern='test_implementation_contracts.py')
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({'kind':'local_qualification_oracles','testsRun':result.testsRun,
                      'skipped':len(result.skipped),'passed':result.wasSuccessful(),
                      'nativeProductTestsExecuted':False,'hardwareProof':False,
                      'longitudinalProof':False,'independentAcceptance':False},sort_keys=True))
    return 0 if result.wasSuccessful() else 1

def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['self-test','verify-bundle','verify-repository'])
    parser.add_argument('--root',type=Path,default=ROOT)
    args=parser.parse_args()
    try:
        if args.command == 'self-test':
            return self_test(args.root/REL)
        report=verify_repository(args.root) if args.command=='verify-repository' else verify_bundle(args.root)
        print(json.dumps(report,sort_keys=True)); return 0
    except (Invalid,OSError,KeyError,ValueError,TypeError,StopIteration,subprocess.TimeoutExpired) as exc:
        print('FAIL_IMPLEMENTATION_CONTRACTS: '+str(exc),file=sys.stderr); return 1

if __name__=='__main__':
    raise SystemExit(main())
