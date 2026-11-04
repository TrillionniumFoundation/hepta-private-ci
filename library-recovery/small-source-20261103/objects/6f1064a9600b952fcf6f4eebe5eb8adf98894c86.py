"""Reproducible local research evidence builder. Does NOT award scientific success."""
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import platform
import shutil
import subprocess
import sys
import time
import zipfile

BASE = Path('/mnt/data/hepta_mgp_local')
ROOT = Path('/mnt/data/hepta_mgp_local_20261022_verified')
ROOT.mkdir(parents=True, exist_ok=True)


def sha(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def run(label, cmd, cwd):
    t0 = time.perf_counter()
    res = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         encoding='utf-8', errors='replace', timeout=120)
    (ROOT / f'{label}.log').write_text(res.stdout)
    return {'label': label, 'cmd': ' '.join(cmd), 'exit_code': res.returncode,
            'seconds': round(time.perf_counter() - t0, 5), 'log_sha256':sha(ROOT/f'{label}.log')}

checks = [
    run('P1_local_pytest_36', [sys.executable, '-m', 'pytest', '-q'], str(BASE)),
    run('P0_independent_LQ', [sys.executable, 'recompute.py'], '/mnt/data/ndu_p0_independent'),
    run('P0_P4_evidence_unittest_5', [sys.executable, '-m', 'unittest', 'discover', '-v'], '/mnt/data/ndu_mgp_gates'),
]
q=run('P0_P4_production_gate_expected_denial', [sys.executable, 'verify.py', 'qualification.json'], '/mnt/data/ndu_mgp_gates')
checks.append(q)
assert [x['exit_code'] for x in checks] == [0,0,0,1], checks
assert 'HOLD_NO_GO' in (ROOT/'P0_P4_production_gate_expected_denial.log').read_text()

sys.path.insert(0,str(BASE))
from paired_superiority import evaluate
from test_paired_superiority import study_fixture
favorable = evaluate(study_fixture(strong_ndu=True, bootstrap_replicates=2000))
unfavorable = evaluate(study_fixture(strong_ndu=False, bootstrap_replicates=2000))
assert favorable['all_provisional_gates_pass'] and not unfavorable['all_provisional_gates_pass']
assert favorable['status'] == unfavorable['status'] == 'HOLD_NO_GO'
assert not favorable['scientific_superiority_proven'] and not unfavorable['scientific_superiority_proven']
(ROOT/'P1_synthetic_favorable_2000_bootstraps.json').write_text(json.dumps(favorable,indent=2)+'\n')
(ROOT/'P1_synthetic_negative_2000_bootstraps.json').write_text(json.dumps(unfavorable,indent=2)+'\n')
files = ['paired_superiority.py','test_paired_superiority.py','decoded_risk.py',
         'test_decoded_risk.py','observed_output.py','test_observed_output.py',
         'run_nonlinear_counterexample.py']
for file in files:
    shutil.copyfile(BASE/file, ROOT/file)
shutil.copyfile('/mnt/data/ndu_p0_independent/recompute.py', ROOT/'p0_recompute.py')
shutil.copyfile('/mnt/data/ndu_p0_independent/recomputation.json', ROOT/'P0_independent_LQ.json')
shutil.copyfile('/mnt/data/ndu_mgp_gates/verify.py', ROOT/'evidence_verify.py')
shutil.copyfile('/mnt/data/ndu_mgp_gates/test_verify.py', ROOT/'test_evidence_verify.py')
receipt = {
    'date_utc':datetime.now(timezone.utc).isoformat(),
    'execution_scope':'LOCAL_CPU_ONLY_NOT_PROJECT_RUNNER',
    'machine':{'python': platform.python_version(),'system':platform.platform(),
               'cpu_count':__import__('os').cpu_count(), 'torch':__import__('torch').__version__,
               'numpy':__import__('numpy').__version__, 'scipy':__import__('scipy').__version__},
    'github_pr': 'https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3251',
    'committed_source_blobs': {'paired_superiority.py':'25b59c9a30bd7846660a27d47cbf123cf021f740',
                               'test_paired_superiority.py':'23a8779de8e5a475a667bebb4b69457ba9df3535'},
    'checks': checks,
    'P1_synthetic_negative_control':{'bootstrap_replicates':2000,
                                     'favorable_fixture_provisional': True,
                                     'unfavorable_fixture_provisional': False,
                                     'both_result':'HOLD_NO_GO'},
    'P0_math_subproblem_pass':True,
    'P0_full_five_seed_prospective_holdout_completed':False,
    'P1_real_model_ndu_superiority_confirmed':False,
    'P2_real_masked_diffusion_model_tested':False,
    'P3_real_natural_multimodal_streaming_qualified':False,
    'P4_real_joint_training_qualified':False,
    'scientific_qualification':'HOLD_NO_GO',
    'runtime_authority':'DENY_ALL',
    'included_files_sha256': {p.name:sha(p) for p in sorted(ROOT.iterdir()) if p.is_file()},
}
(ROOT/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
zip_path = Path('/mnt/data/hepta_mgp_local_p1_evidence_20261022.zip')
with zipfile.ZipFile(zip_path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=7) as z:
    for p in sorted(ROOT.iterdir()):
        if p.is_file():z.write(p,arcname='hepta_mgp_local_p1/'+p.name)
print(json.dumps({'artifact':str(zip_path),'zip_sha256':sha(zip_path),'checks':checks,
                  'scientific_qualification':receipt['scientific_qualification']},indent=2))
