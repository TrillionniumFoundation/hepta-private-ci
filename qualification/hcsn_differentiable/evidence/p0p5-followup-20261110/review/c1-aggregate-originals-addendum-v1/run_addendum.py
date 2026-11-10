"""Bind newly recovered aggregate reports to the previously audited small bytes."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

if sys.flags.optimize:
    raise RuntimeError('Assertions must remain enabled')
root=Path(__file__).resolve().parents[1]
source=root/'c1-clock-outcomes-independent-review-v1/review_outcomes.py'
if hashlib.sha256(source.read_bytes()).hexdigest()!='7c2e28c1e82d25cc53e6a040d2e7230748a088d7aacf904e6f8284635ae6e875':
    raise RuntimeError('Prior recomputation source differs')
spec=importlib.util.spec_from_file_location('retained_outcomes_review',source)
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
audit.OUT=Path(__file__).resolve().parent/'execution';audit.OUT.mkdir(exist_ok=False)
first=root/'baseline36-c1-aggregate-originals-v1/v1-RESULT.json'
second=root/'baseline36-c1-aggregate-originals-v1/v2-RESULT.json'
v1=audit.obj(first);v2=audit.obj(second)
small=audit.SMALL
originals={p.stem:audit.obj(p) for p in sorted((small/'v1/output').glob('original-*.json'))}
children={p.stem:audit.obj(p) for p in sorted((small/'v1/output').glob('C1-*.json'))}
assert len(originals)==36 and len(children)==7
assert all(row==originals['original-'+row['name']] for row in v1['original_baseline_records'])
assert all(row==children['C1-'+row['name']] for row in v1['C1_records'])
assert v1['passed'] is False and v2['passed'] is True
assert v2['original36_reuse']['prior_result_sha256']==hashlib.sha256(first.read_bytes()).hexdigest()
assert v2['original36_reuse']['original36_passed_subrecords_reused']==36
assert not v2['original36_reuse']['baseline_fresh_forward_reexecuted']
assert v1['identity_checks']['pinned_inputs_unchanged'] and v1['identity_checks']['source_unchanged']
for report in [v1,v2]:
    assert not report['full42_final_audit'] and not report['training_performed']
    assert not report['confirmation_access'] and report['optimizer_steps_executed']==0
    assert report['scientific_admission']=='HOLD'
prior=audit.obj(root/'c1-clock-outcomes-independent-review-v1/RESULT.json')
assert prior['passed_scoped_recomputation'] and prior['full_results_read']==[]
sys.argv=[str(source),'--full-v1-result',str(first),'--full-v2-result',str(second)]
audit.main()
extra={'schema':'late-aggregate-originals-binding-v1','prior_small_review_preserved':True,'prior_had_not_read_full_results':True,'v1_original36_and_failed_C1_subrecords_equal':True,'v2_prior_result_hash_and36_reuse_verified':True,'new_full_results_sha256':{1:hashlib.sha256(first.read_bytes()).hexdigest(),2:hashlib.sha256(second.read_bytes()).hexdigest()},'scope':'Recovered aggregate report consistency and repeated local JSON calculations only; no new checkpoint, tensor, model, native process or external asset readback.'}
with (audit.OUT/'ADDENDUM.json').open('x') as f:f.write(json.dumps(extra,indent=2,sort_keys=True)+'\n')
