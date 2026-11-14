#!/usr/bin/env python3
"""Run the portable *local subproblem* test suite; no scientific acceptance."""
from __future__ import annotations
from hashlib import sha256
from pathlib import Path
from datetime import datetime, timezone
import json, os, platform, subprocess, sys, time
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'evidence'
OUT.mkdir(exist_ok=True)

def sha(p):
    return sha256(Path(p).read_bytes()).hexdigest()

def execute(label, command, expected):
    start=time.perf_counter()
    run=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
    log=OUT/(label+'.log')
    log.write_text(run.stdout+run.stderr)
    return {'label':label,'command':command,'exit_code':run.returncode,
            'expected_exit':expected,'passed':run.returncode==expected,
            'elapsed_seconds':round(time.perf_counter()-start,5),
            'log_sha256':sha(log)}

checks=[execute('pytest_52',[sys.executable,'-m','pytest','-q'],0),
        execute('independent_lq',[sys.executable,'experiments/ndu_mgp_gates/p0_recompute.py'],0),
        execute('production_gate_expected_deny',[sys.executable,'experiments/ndu_mgp_gates/verify.py',
            'experiments/ndu_mgp_gates/qualification.json'],1)]
assert '52 passed' in (OUT/'pytest_52.log').read_text(), 'test count changed'
assert '"checks_passed": true' in (OUT/'independent_lq.log').read_text()
assert 'HOLD_NO_GO' in (OUT/'production_gate_expected_deny.log').read_text()
p1=ROOT/'experiments'/'ndu_mgp_gates'
import subprocess as sp
blobs={fn:sp.check_output(['git','hash-object',str(p1/fn)],text=True).strip()
       for fn in ('paired_superiority.py','test_paired_superiority.py')}
expected={'paired_superiority.py':'776ff36ad2df5a23151abd5011a0a54d16e14c73',
          'test_paired_superiority.py':'0bee7e537e7581d8ffa0df3ba7a0a9557766803d'}
assert blobs==expected, 'locally tested files differ from GitHub source'
receipt={'schema':'hepta.local.p1.protected.v1',
    'date_utc':datetime.now(timezone.utc).isoformat(),
    'scope':'portable local Python numerical/research-subproblem only',
    'environment':{'python':platform.python_version(), 'platform':platform.platform(),
                   'num_cpus':os.cpu_count(), 'numpy':__import__('numpy').__version__,
                   'scipy':__import__('scipy').__version__, 'torch':__import__('torch').__version__},
    'github_pr':'https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3332',
    'source_git_blobs':blobs, 'checks':checks,
    'all_local_checks_pass':all(x['passed'] for x in checks),
    'actual_five_seed_p0_heldout_completed':False,
    'scientific_ndu_superiority_proven':False,
    'independent_external_observer_authenticated':False,
    'p2_actual_diffusion_llm_verified':False,
    'p3_natural_crossmodal_outputs_verified':False,
    'p4_independent_joint_training_verified':False,
    'overall':'HOLD_NO_GO', 'production_authority':'DENY_ALL',
    'untrusted_fixture_manifest':True}
assert receipt['all_local_checks_pass']
(OUT/'run_receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(receipt,ensure_ascii=False,indent=2))
