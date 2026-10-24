import hashlib,json,datetime
from pathlib import Path
P=Path(__file__).resolve().parent
old=P.parent/'cell-head-calibration-research'
H=lambda b:hashlib.sha256(b).hexdigest()
plan={
 'profile':'harrier-head-budget-independent-historical-v1',
 'question':'Does a fixed logistic head benefit relative to centroid when only its training sample budget increases?',
 'primary_estimands':['logistic-minus-centroid test accuracy at n=2560','paired gain in logistic-minus-centroid accuracy from n=320 to n=2560'],
 'training_budgets':[320,640,1280,2560], 'test_rows':1600,
 'selection':{'salt':'hepta-head-budget-v1-20261024','ranking':'sha256(salt|official_split|component_key); prefix nesting for training; first 1600 eligible test components','labels':'Not stratified. No test class counts or scores consulted for selection. Missing training class aborts without reseeding.', 'groups':'Union records sharing NFKC whitespace-collapsed casefolded title OR full text. Component key is minimum full-text hash. Remove whole components spanning official train/test, containing conflicting labels, or intersecting any of the old 960 selected full-text groups. Select lowest source row index in each remaining component.'},
 'dataset':{k:v for k,v in json.loads((old/'plan.json').read_text())['dataset'].items()},
 'old_rows_sha256':H((old/'rows.json').read_bytes()),
 'encoder':json.loads((old/'plan.json').read_text())['encoder'],
 'heads':{'centroid':json.loads((old/'plan.json').read_text())['heads']['centroid'],'logistic':json.loads((old/'plan.json').read_text())['heads']['logistic']},
 'analysis':{'fixed_before_test':'No validation tuning, temperature scaling or conformal selection in this experiment. Fit and save all four heads before scoring any test head. All four curves reported, no winning-budget selection.', 'bootstrap':'10000 paired row resamples, PCG64 seed 2026102401. Each of two primary estimands gets two-sided 97.5% percentile interval (Bonferroni family target 95%; descriptive, not an exact finite-sample guarantee). Claim budget-related benefit only if both lower bounds > 0. Otherwise report inconclusive/no demonstrated benefit, not equivalence.', 'secondary':'Accuracy for both heads at all four budgets, training CE/objective and final gradient L2, wall time, RSS. No additional significance claims.', 'optimization':'Same fixed 200 Adam steps at each budget; this measures fixed-training-procedure budget benefit, not an optimal linear classifier. Report gradient norm; never repair optimizer after seeing test.'},
 'resource_budget':{'rows_to_encode':4160,'expected_feature_bytes':4160*640*4,'threads':2,'batch_size':8,'prior_extraction_seconds_960':133.02,'linear_projection_seconds_4160':133.02*4160/960,'planning_limit_minutes':30,'rss_stop_gib':3.5,'disk_limit_gib':4,'download_status':'Not initiated. Existing runtime/cache absent; restoration to be coordinated by parent. No paid compute or giant model.'},
 'power_planning':{'not_data_estimated':True,'test_accuracy_difference_se':'sqrt((discordance-delta**2)/1600); discordance scenarios 0.05,0.10,0.20. Rough 80% power delta=(z_0.9875+z_0.8)*sqrt(discordance/1600). Gain estimand has additional covariance and no assured power.', 'no_optional_stopping':'Fixed n=1600; do not expand test or tune sample budget on observed scores.'},
 'limits':['New disjoint historical same-source sample, NOT unseen source-family or future data.','Title/full-text unions do not remove semantic story overlap or training contamination.','Removal of duplicate components changes sampled population and may bias difficulty.','One nested training draw, test-row intervals conditional on this draw; cannot infer training-set sampling variability.','200-step fixed optimization may confound data budget with optimization quality.','The old negative head and LAC findings remain intact.','This is only head-budget diagnosis, not five-model replacement or deployment qualification.'],
 'sources':['https://huggingface.co/microsoft/harrier-oss-v1-270m','https://www.tensorflow.org/datasets/catalog/ag_news_subset','https://arxiv.org/abs/1509.01626','https://arxiv.org/abs/2103.10948'],
 'license':'AG News research/non-commercial terms only; raw text stays local, no commercial or redistribution rights inferred; Harrier model card MIT.'}
b=(json.dumps(plan,indent=2,sort_keys=True)+'\n').encode()
with (P/'protocol.json').open('xb') as f:f.write(b)
receipt={'protocol_sha256':H(b),'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'local pre-data-selection/pre-new-feature/pre-test-score freeze, not external preregistration','new_test_scores_seen':False}
with (P/'protocol-freeze.json').open('x') as f:json.dump(receipt,f,indent=2)
print(json.dumps(receipt))
