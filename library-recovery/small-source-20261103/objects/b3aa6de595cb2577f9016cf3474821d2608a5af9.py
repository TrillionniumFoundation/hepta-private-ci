"""Research-only exact synthetic negative control for protected task admission."""
import json, sys, runpy, importlib.util, hashlib, platform
from pathlib import Path
import numpy, torch

here=Path(__file__).resolve().parent
upstream=Path('/mnt/data/hepta_p1_protected_coverage_20261022')
sys.path.insert(0,str(upstream))
# Constructs 3x512 paired synthetic outcomes and returns the input study.
old=runpy.run_path(str(upstream/'attack_all_protected_fail.py'))
study=old['study']
# Same frozen policy values for both runs; the original evaluator ignores them.
study['protocol']['min_protected_ndu_quality'] = 0.80
study['protocol']['min_protected_ndu_completion'] = 0.80
newpath=here/'paired_superiority.py'
spec=importlib.util.spec_from_file_location('patched_shadow_eval',newpath)
new=importlib.util.module_from_spec(spec)
spec.loader.exec_module(new)
rec=new.evaluate(study)
assert old['r']['all_provisional_gates_pass'] is True
assert rec['all_provisional_gates_pass'] is False
for name in new.CONTROLS:
  assert rec['comparison'][name]['gates']['protected_task_absolute_service'] is False
  assert rec['comparison'][name]['gates']['protected_task_no_regression'] is True
  assert rec['comparison'][name]['gates']['cvar90_incremental_superiority'] is True
out={
  'scope':'SYNTHETIC_SHADOW_ONLY_NOT_SCIENTIFIC',
  'protocol':'paired synthetic 3 seeds x 512 worlds, 8 independently labelled protected original sources per seed',
  'pre_patch_all_provisional_gates_pass':old['r']['all_provisional_gates_pass'],
  'post_patch_all_provisional_gates_pass':rec['all_provisional_gates_pass'],
  'before_protected_gate_true':all(x['gates']['protected_task_no_regression'] for x in old['r']['comparison'].values()),
  'after_relative_protected_gate_true':all(x['gates']['protected_task_no_regression'] for x in rec['comparison'].values()),
  'after_new_absolute_protected_gate_true':all(x['gates']['protected_task_absolute_service'] for x in rec['comparison'].values()),
  'protected_independent_source_counts':rec['protected_original_sources_per_seed'],
  'protected_quality_by_seed':rec['ndu_protected_source_equal_quality_by_seed'],
  'protected_completion_by_seed':rec['ndu_protected_source_equal_completion_by_seed'],
  'registered_quality_threshold':rec['registered_min_protected_ndu_quality'],
  'registered_completion_threshold':rec['registered_min_protected_ndu_completion'],
  'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [here/'paired_superiority.py',here/'test_paired_superiority.py']},
  'versions':{'python':platform.python_version(),'numpy':numpy.__version__,'torch':torch.__version__},
  'not_a_production_acceptance_receipt': True,'no_source_authentication': True,
}
(here/'REPRODUCTION.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out,indent=2))
