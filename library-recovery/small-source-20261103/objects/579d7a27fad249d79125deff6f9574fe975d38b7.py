"""STAGING FIXTURE ONLY. Uses padded mmBERT features, NOT real ModernBERT weights."""
from pathlib import Path
import hashlib, shutil, sys, json
import numpy as np
from safetensors.numpy import load, save
from unittest.mock import patch
root=Path('/mnt/data/hepta_cross_e1e2')
sys.path.insert(0,str(root))
from experiments.shared_stem_cell.wire import canonical, sha
from experiments.shared_stem_cell.e2_modern_budget import produce
from experiments.shared_stem_cell.e2_modern_review import review_sweep as modern_review
from experiments.shared_stem_cell.e1_e2_joint_review import audit
from experiments.shared_stem_cell.e2_budget_review import review_sweep as baseline_review
source=Path('/mnt/data/hepta_round_next/pr1808/hepta-public-study')
original=source/'execution'
base_report_sha=hashlib.sha256((original/'report.json').read_bytes()).hexdigest()
mm_sweep=Path('/mnt/data/hepta_e2_real/actual_results')
fixture=root/'fixture_768d_NOT_REAL_MODERNBERT'
if fixture.exists():shutil.rmtree(fixture)
fixture.mkdir()
plan=json.loads((source/'manifest.json').read_bytes())
plan['model']={'path':'fixture-no-weights','kind':'masked_lm',
               'model_id':'answerdotai/ModernBERT-base',
               'revision':'fa3113d09d6dacfe5528708803dd92a62240237a',
               'files':{'model.safetensors':'0'*64},'conversion':None}
(fixture/'dataset.jsonl').write_bytes((source/'dataset.jsonl').read_bytes())
(fixture/'manifest.json').write_bytes(canonical(plan))
producer=fixture/'execution'
(producer/'frozen-features').mkdir(parents=True)
old=np.asarray(load((original/'frozen-features/features.safetensors').read_bytes())['features'],dtype=np.float32)
assert old.shape==(128,384)
x=np.concatenate((old,old),axis=1).astype(np.float32)
raw=save({'features':x})
(producer/'frozen-features/features.safetensors').write_bytes(raw)
new_model_identity=sha(canonical(plan['model']))
manifest=json.loads((original/'frozen-features/manifest.json').read_bytes())
manifest['file_sha256']=sha(raw)
manifest['file_bytes']=len(raw)
manifest['shape']=[128,768]
manifest['tensor_bytes']=x.nbytes
manifest['tensor_sha256']=sha(canonical(['torch.float32',[128,768]])+x.tobytes())
manifest['binding']['stem_sha256']=new_model_identity
manifest['binding']['manifest_sha256']=sha((fixture/'manifest.json').read_bytes())
manifest['binding']['feature_profile_sha256']=sha(canonical({
  'width':768,'representation':'masked_mean_float32','model':new_model_identity,
  'maximum_tokens':plan.get('maximum_tokens',512)}))
(producer/'frozen-features/manifest.json').write_bytes(canonical(manifest))
report=json.loads((original/'report.json').read_bytes())
report['manifest_sha256']=sha((fixture/'manifest.json').read_bytes())
report['encoding']['model_digest']=new_model_identity
report['frozen_features']['manifest_sha256']=sha((producer/'frozen-features/manifest.json').read_bytes())
report['frozen_features']['shape']=[128,768]
report['frozen_features']['tensor_bytes']=x.nbytes
(producer/'report.json').write_bytes(canonical(report))
(producer/'predictions.json').write_bytes((original/'predictions.json').read_bytes())
ref=sha((producer/'report.json').read_bytes())
source_rec={'model_manifest_sha256':new_model_identity}
with patch('experiments.shared_stem_cell.e2_modern_budget.replay',return_value=source_rec):
  result=produce(fixture/'manifest.json',producer,fixture/'modern_sweep',report_sha256=ref)
print('SYNTHETIC 768d test producer:',len(result['artifacts']), result['feature_width'])
with patch('experiments.shared_stem_cell.e2_modern_review.replay',return_value=source_rec):
  rr=modern_review(fixture/'manifest.json',producer,ref,fixture/'modern_sweep')
print('SYNTHETIC 768d test review:',rr['physical_head_checkpoint_count'],rr['independently_replayed_prediction_vectors'],rr['max_prediction_abs_diff'])
with patch('experiments.shared_stem_cell.e2_modern_review.replay',return_value=source_rec):
  joint=audit(source/'manifest.json',original,base_report_sha,mm_sweep,
              fixture/'manifest.json',producer,ref,fixture/'modern_sweep')
print('SYNTHETIC joint controls:',joint['original_paired_holdout_items'],len(joint['per_budget_results']),joint['per_cell_sample_stream_identical_across_stems'])
assert joint['research_winner_selected'] is False
assert joint['production_accepted'] is False
assert joint['five_head_budgets_both_stems_executed'] is True
print('IMPORTANT: this is a synthetic 768d padded mmBERT FEATURE FIXTURE, not a ModernBERT result!')
