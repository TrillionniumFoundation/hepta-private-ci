"""Verify only the declared CURRENT continuum-scope paragraph correction."""
from pathlib import Path
import hashlib,json
from datetime import datetime,timezone
root=Path(__file__).resolve().parents[1];repo=root/'hcsn-repo'
current=repo/'qualification/hcsn_differentiable/CURRENT.md'
original_sha='05383a803ea62d839dc77c612bcc722332c51978997436005c34818adfcbe55f'
new_sha='1ac67e067a180a9c6231b569b115bd8f1f4a4b98ba454ef726640d34703cf0f8'
old='''With fixed positive reset distance, negative drift has finite mean cycle
`d+x_r/(-mu)`. Zero drift hits almost surely but has infinite mean cycle time.
Positive drift has a nonzero escape probability and a finite total number of
future events almost surely. The constructor allows crossing zero; this does
not qualify a stationary firing-rate objective or a trainable domain.
'''
new='''For the fixed continuum diffusion/regenerative reference with `sigma > 0`
and a fixed positive reset distance, negative drift has finite mean cycle
`d+x_r/(-mu)`. Zero drift hits almost surely but has infinite mean cycle time.
Positive drift has a nonzero escape probability and a finite total number of
future events almost surely. The constructor allows crossing zero; this does
not qualify a stationary firing-rate objective or a trainable domain.
These continuum asymptotics do not qualify the finite QPR chain: its fixed
returning-tail reconstruction can change long-run recurrence and event rates.
'''
def identity(p):
 raw=p.read_bytes();return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
raw=current.read_bytes();assert hashlib.sha256(raw).hexdigest()==new_sha
assert raw.count(new.encode())==1
reconstructed=raw.replace(new.encode(),old.encode(),1)
assert hashlib.sha256(reconstructed).hexdigest()==original_sha
prior_path=root/'final-curation-delta-review-v2/execution/RESULT.json'
prior=json.loads(prior_path.read_bytes());assert prior['integrity_passed']
unchanged={}
for path in [repo/'proposals/localization-v3/README.md',repo/'qualification/hcsn_differentiable/evidence/p0p5-20261110/README.md',repo/'qualification/hcsn_differentiable/evidence/p0p5-20261110/p1/width16-v6/INDEX.md',repo/'qualification/hcsn_differentiable/evidence/p0p5-20261110/MANIFEST.json']:
    value=identity(path);assert value==prior['inputs'][str(path)];unchanged[str(path)]=value
math_expected={'MODEL.md':'8919ff5f44af1e8929f2a6838d765f8e0333c807190834f6a957db8a142b611b','operator.py':'cb3eed1bcfbd3b10cc331a193a5d4b6a3d4309db899e0d8f821477f97b7dbdc1','contract.py':'79e1127dc126fb8ac97ce7542bac2c9d70c71e0fd2d24416f146d4ec82be099e'}
for n,h in math_expected.items():
    p=repo/'qualification/hcsn_differentiable'/n;v=identity(p);assert v['sha256']==h;unchanged[str(p)]=v
report={'schema':'CURRENT-continuum-scope-closure-v1','created_utc':datetime.now(timezone.utc).isoformat(),'finding':'MATH-01','status':'closed_by_narrow_documentation_change','old_CURRENT_sha256':original_sha,'new_CURRENT':identity(current),'new_CURRENT_lines':len(raw.splitlines()),'reverse_exact_paragraph_replacement_reconstructs_old_sha256':True,'only_declared_paragraph_changed':True,'old_paragraph':old,'new_paragraph':new,'unchanged_companion_inputs':unchanged,'prior_review':identity(prior_path),'full_prefix_reaudit_performed':False,'scope':'Only CURRENT paragraph delta and unchanged companion documents/top manifest/math inputs; previous complete curation report remains immutable. Newly arrived terminal outcomes/archives are outside this closure.','mathematical_assessment':'The fixed continuum model and sigma>0 condition are explicit, and automatic transfer of long-run escape/recurrence to the finite returning-tail QPR chain is excluded. No finite-chain rate is asserted.','numerical_experiment_performed':False,'training_performed':False,'model_or_native_runtime_read':False,'scientific_admission':'HOLD'}
with Path(__file__).with_name('RESULT.json').open('x') as f:f.write(json.dumps(report,indent=2,sort_keys=True)+'\n')
print(json.dumps({'status':report['status'],'only_declared_paragraph_changed':True,'new_CURRENT':report['new_CURRENT'],'unchanged_companion_inputs':len(unchanged)}))
