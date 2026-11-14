"""Local adversarial falsification of a movable protected-task cohort; synthetic only."""
import hashlib
import importlib.util
import json
from pathlib import Path

root = Path(__file__).resolve().parent
previous = Path('/mnt/data/hepta_p1_protected_service_20261022/paired_superiority.py')

def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

prior = load(previous, 'research_parent_without_frozen_labels')
fixed = load(root/'paired_superiority.py', 'research_with_frozen_labels')
from test_paired_superiority import study_fixture
study = study_fixture(bootstrap_replicates=2000)
for world in study['worlds']:
    if world['protected_task']:
        for score in world['outcomes']['ndu']['decoded_draw_scores']:
            score['quality'] = 0.70

def scored_digest():
    raw = [{k:world[k] for k in ('seed','world_id','source_group_id','public_input_digest','outcomes')}
           for world in study['worlds']]
    return hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

before_digest = scored_digest()
old_before = prior.evaluate(study)
new_before = fixed.evaluate(study)
for world in study['worlds']:
    world['protected_task'] = int(world['world_id'].rsplit('-', 1)[1])%4 == 2
old_after = prior.evaluate(study)
blocked = False
try:
    fixed.evaluate(study)
except fixed.EvidenceGap as exc:
    blocked = 'protected-task label differs from frozen heldout manifest' in str(exc)
assert blocked
assert before_digest == scored_digest()
assert old_before['all_provisional_gates_pass'] is False
assert old_after['all_provisional_gates_pass'] is True
assert new_before['all_provisional_gates_pass'] is False
assert all(x == 0.7 for x in old_before['ndu_protected_source_equal_quality_by_seed'])
assert all(x == 0.92 for x in old_after['ndu_protected_source_equal_quality_by_seed'])
output = {'kind': 'synthetic_adversarial_regression_not_frozen_real_model',
          'seeds':3,'worlds_per_seed':32,'bootstrap_replicates':2000,
          'unchanged_decoder_outputs_and_costs_sha256':before_digest,
          'original_protected_sources_per_seed':[8,8,8],
          'after_relabel_protected_sources_per_seed':[8,8,8],
          'prior_before_provisional':old_before['all_provisional_gates_pass'],
          'prior_after_provisional':old_after['all_provisional_gates_pass'],
          'amended_before_provisional':new_before['all_provisional_gates_pass'],
          'amended_after_relabel_rejected':blocked,
          'scientific_success':False,'authority':'DENY_ALL',
          'classification':'P1 local science admission correctness only'}
(root/'PROTECTED_LABEL_ATTACK.json').write_text(json.dumps(output,indent=2)+'\n')
print(json.dumps(output,indent=2))
