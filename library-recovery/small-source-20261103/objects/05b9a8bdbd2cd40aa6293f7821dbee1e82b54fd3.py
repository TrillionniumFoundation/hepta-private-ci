#!/usr/bin/env python3
"""Replay bounded, unauthenticated local P0/P1 correctness checks."""
import hashlib,json,platform,subprocess,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent
RESULTS=ROOT/'results'
RESULTS.mkdir(exist_ok=True)

def run(label,argv,expected=0):
    process=subprocess.run([sys.executable,*argv],cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    (RESULTS/f'{label}.log').write_text(process.stdout,encoding='utf-8')
    if process.returncode!=expected:raise RuntimeError(f'{label} exit {process.returncode}, expected {expected}:\n{process.stdout[-2000:]}')
    return process.stdout

def main():
    manifest=json.loads((ROOT/'source_manifest.json').read_text())
    for path,sha in manifest['files_sha256'].items():
        actual=hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
        if actual!=sha:raise RuntimeError(f'source manifest mismatch: {path}')
    tests=run('tests',['-m','pytest','-q','-p','no:cacheprovider','.'])
    if '46 passed' not in tests:raise RuntimeError('unexpected local test count')
    p0=run('p0_known_lq',['p0_recompute.py'])
    p0_data=json.loads((ROOT/'p0_independent_recomputation.json').read_text())
    if not p0_data['checks_passed']:raise RuntimeError('known-LQ rerun failed')
    toy=run('nonlinear_counterexample',['run_nonlinear_counterexample.py'])
    neg=json.loads((ROOT/'nonlinear_counterexample_receipt.json').read_text())
    if neg['status']!='REJECT_OBSERVED_OUTPUT' or neg['authority']!='DENY_ALL':raise RuntimeError('missing nonlinear risk denial')
    deny=run('fail_closed',['verify.py','qualification.json'],expected=1)
    if not deny.startswith('HOLD_NO_GO'):raise RuntimeError('evidence gate did not deny')
    from test_paired_superiority import study_fixture
    from paired_superiority import evaluate
    reports={}
    for label,strong in (('synthetic_favorable',True),('synthetic_negative',False)):
        r=evaluate(study_fixture(strong_ndu=strong,bootstrap_replicates=2000))
        if r['status']!='HOLD_NO_GO' or r['scientific_superiority_proven'] or r['authority']!='DENY_ALL':raise RuntimeError('scientific authority bypass')
        reports[label]={'provisional_pass':r['all_provisional_gates_pass'],'scientific_superiority_proven':r['scientific_superiority_proven'],'status':r['status']}
        (RESULTS/(label+'.json')).write_text(json.dumps(r,indent=2)+'\n',encoding='utf-8')
    if not reports['synthetic_favorable']['provisional_pass'] or reports['synthetic_negative']['provisional_pass']:
        raise RuntimeError('synthetic positive/negative acceptance regression')
    receipt={'schema':'hepta-local-bounded-replay-v1','test_count':46,'tests':'PASS',
             'p0_known_LQ':True,'p0_max_abs_difference':max(p0_data['absolute_differences'].values()),
             'nonlinear_counterexample':'REJECT_OBSERVED_OUTPUT','p1_synthetic':reports,
             'execution_tier':'local-CPU-no-target-host-attestation',
             'scientific_efficacy_established':False,'independent_science_acceptance':False,
             'production_authorized':False,'authority':'DENY_ALL','overall':'HOLD_NO_GO',
             'python':platform.python_version(),'source_manifest_sha256':hashlib.sha256((ROOT/'source_manifest.json').read_bytes()).hexdigest()}
    (RESULTS/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt,indent=2))
    return 0

if __name__=='__main__':raise SystemExit(main())
