#!/usr/bin/env python3
"""Independent numeric pilot review, never a model-origin or NDU attestation."""
from __future__ import annotations
import argparse,hashlib,json,math
from pathlib import Path
MODELS={'granite_97m_r2':('835ad14087e140460703cf0fae09f97d469d65c2',384),
'mmbert_small':('0eb3d056ec1d6333cf4e19b0966dfde342a41a3a',384),
'embeddinggemma_2_text':('914f7f89142e33e77833254d9c9b90c3cef7303b',256)}
CORE_MODELS = {
 'granite_97m_r2':('835ad14087e140460703cf0fae09f97d469d65c2',384),
 'mmbert_small':('0eb3d056ec1d6333cf4e19b0966dfde342a41a3a',384),
 'modernbert_base':('fa3113d09d6dacfe5528708803dd92a62240237a',768)}
CORE_REPOS = {
 'granite_97m_r2':'ibm-granite/granite-embedding-97m-multilingual-r2',
 'mmbert_small':'jhu-clsp/mmBERT-small',
 'modernbert_base':'answerdotai/ModernBERT-base'}
class Invalid(ValueError):pass
def pairs(seq):
 d={}
 for k,v in seq:
  if k in d:raise Invalid('duplicate JSON key')
  d[k]=v
 return d
def read(path):
 b=Path(path).read_bytes()
 if not 10<len(b)<4*1024*1024:raise Invalid('missing/oversized artifact')
 return json.loads(b,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(Invalid('nonfinite JSON')))
def canonical(obj):return json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def sha(b):return hashlib.sha256(b).hexdigest()
def evaluate(panel,reports,*,core=False):
 if type(core) is not bool:raise Invalid('explicit registered study family required')
 models=CORE_MODELS if core else MODELS
 if type(panel) is not dict or panel.get('schema')!='hepta.stem.agnews-binary-capability-panel.v1' or panel.get('case_count')!=224 or panel.get('cross_sectional_not_future') is not True or panel.get('production_promotion')!='DENY_ALL':
  raise Invalid('invalid public panel')
 cases=panel['cases'];bycase={c['case_id']:c for c in cases}
 if len(bycase)!=224 or len(cases)!=224:raise Invalid('duplicate public source case')
 observed={c['case_id'] for c in cases if c['split'] in ('calibration','test')}
 panel_sha=sha(canonical(panel))
 if set(reports)!=set(models):raise Invalid('three model execution records required')
 metrics={};prediction_map={};resource_summary={};training=None
 for model,report in reports.items():
  revision,width=models[model]
  if (type(report) is not dict or report.get('schema')!='hepta.e1-english-public-pretrained-head.v1' or
      report.get('model')!=model or report.get('model_revision')!=revision or report.get('feature_width')!=width or
      report.get('public_panel_sha256')!=panel_sha or report.get('authority')!='DENY_ALL' or
      report.get('production_promotion_permitted') is not False or report.get('english_only') is not True or
      report.get('public_dataset_is_chronological_future') is not False or
      report.get('actual_pretrained_local_weight_execution_claimed') is not True or
      report.get('model_origin_independently_authenticated') is not False):
   raise Invalid('source/model/control identity drift')
  fit=report.get('fitting')
  if type(fit) is not dict or fit.get('steps')!=40 or fit.get('seed')!=20261014 or fit.get('learning_rate')!=.15 or fit.get('training_test_labels_accessed') is not False:
   raise Invalid('optimizer/test-label boundary mismatch')
  n=fit.get('head_parameter_count')
  if type(n) is not int or not 0<n<=2048:raise Invalid('wrong complete Head parameter budget')
  if core and (n!=2*width+2 or report.get('model_name')!=CORE_REPOS[model]):
   raise Invalid('incorrect full private linear Head or publisher model identity')
  current=(fit.get('train_case_ids_sha256'),fit['steps'],fit['seed'],fit['learning_rate'])
  if training is None:training=current
  elif training!=current:raise Invalid('unmatched train group or optimizer')
  tokens=report.get('tokens_per_case');features=report.get('features_q24_identity')
  if type(tokens) is not dict or type(features) is not dict or set(tokens)!=set(bycase) or set(features)!=set(bycase):
   raise Invalid('incomplete same-source token/feature coverage')
  if any(type(x) is not int or not 1<=x<=512 for x in tokens.values()):raise Invalid('truncated/missing token count')
  if any(type(x) is not str or len(x)!=64 or any(c not in '0123456789abcdef' for c in x) for x in features.values()):
   raise Invalid('invalid feature digest')
  measures=report.get('physical_observations')
  latency=measures.get('encode_ms_by_case') if type(measures) is dict else None
  if (type(measures) is not dict or type(latency) is not dict or set(latency)!=set(bycase) or
      measures.get('local_model_api_requests')!=224 or
      measures.get('physical_transformer_forward_count_attested') is not False or
      report.get('physical_transformer_forward_count_attested') is not False):
   raise Invalid('incomplete or overclaimed physical cost envelope')
  measurements=[report.get('wall_ms'),report.get('cpu_process_ms'),
                report.get('process_lifetime_peak_rss_bytes'),
                measures.get('load_ms'),fit.get('train_time_ms')]
  if (any(type(x) not in (float,int) or not math.isfinite(x) or x<=0 for x in measurements) or
      any(type(x) not in (float,int) or not math.isfinite(x) or x<=0 for x in latency.values())):
   raise Invalid('nonpositive or missing measured runtime/RSS')
  if core:
   publisher=measures.get('publisher_file_inventory_sha256')
   if (measures.get('local_all_saved_model_tensors_checked_by_loader') is not True or
       measures.get('publisher_files_checked_by_local_acquisition') is not True or
       measures.get('local_encoder_forward_calls_observed')!=224 or
       type(publisher) is not str or len(publisher)!=64 or publisher=='0'*64 or
       any(c not in '0123456789abcdef' for c in publisher) or
       measures.get('reference_transformers_runtime_version')!='4.57.1'):
    raise Invalid('missing local tensor/publisher/physical forward source checks')
  elif model=='mmbert_small':
   flag=measures.get('mmbert_pretrained_complete_tied_table_verified')
   identity=measures.get('mmbert_local_complete_table_sha256')
   full=measures.get('mmbert_all_serialized_weights_byte_verified')
   state=measures.get('mmbert_whole_pretrained_checkpoint_sha256')
   count=measures.get('mmbert_verified_source_tensor_count')
   if (flag is not True or type(identity) is not str or len(identity)!=64 or identity=='0'*64 or
       any(c not in '0123456789abcdef' for c in identity) or
       full is not True or type(state) is not str or len(state)!=64 or state=='0'*64 or
       any(c not in '0123456789abcdef' for c in state) or
       type(count) is not int or count < 100):
    raise Invalid('mmBERT full pretrained model parameter source not verified')
  elif measures.get('mmbert_pretrained_complete_tied_table_verified') is not None:
   raise Invalid('non-mmBERT arm forged mmBERT provenance')
  encoded=sum(latency.values())
  if report['wall_ms'] + .001 < measures['load_ms'] + encoded + fit['train_time_ms']:
   raise Invalid('whole-lifecycle physical time undercounts completed operations')
  resource_summary[model]={'observed_total_process_wall_ms':report['wall_ms'],
    'observed_process_cpu_ms':report['cpu_process_ms'],
    'observed_lifetime_peak_rss_bytes':report['process_lifetime_peak_rss_bytes'],
    'reported_encoder_load_ms':measures['load_ms'],
    'reported_all_unique_input_encode_ms':encoded,
    'reported_train_ms':fit['train_time_ms'],
    'reported_unique_model_requests':measures['local_model_api_requests'],
    'model_specific_token_count_range':[min(tokens.values()),max(tokens.values())],
    'complete_Head_parameters':n,
    'energy_joules':None,'request_p99_verified':False,
    'backend_batch_physical_count_verified':False}
  controls=fit.get('controls')
  if type(controls) is not dict or set(controls)!={'frozen_head','learned_head'}:raise Invalid('missing frozen/learned Head')
  metrics[model]={};prediction_map[model]={}
  for control,ob in controls.items():
   if (type(ob) is not dict or type(ob.get('head_sha256')) is not str or len(ob['head_sha256'])!=64 or
       ob.get('calibration_temperature') not in (.5,.75,1.,1.5,2.,3.,4.)):
    raise Invalid('bad Head digest/calibration')
   rows=ob.get('predictions')
   if type(rows) is not list or len(rows)!=96:raise Invalid('incomplete paired probabilities')
   predictions={}
   for p in rows:
    key=p.get('case_id')
    if key not in observed or key in predictions or p.get('joint_input_digest')!=bycase[key]['joint_input_digest'] or p.get('split')!=bycase[key]['split']:
     raise Invalid('swapped/missing prediction source')
    v=p.get('positive_probability')
    if type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1:raise Invalid('bad probability')
    predictions[key]=float(v)
   if set(predictions)!=observed:raise Invalid('missing independent holdout')
   prediction_map[model][control]=predictions
   result={}
   for split in ('calibration','test'):
    rows=[c for c in cases if c['split']==split]
    result[split]={'n':len(rows),'correct':sum(int((predictions[c['case_id']]>=.5)==bool(c['label'])) for c in rows),
                   'brier':sum((predictions[c['case_id']]-c['label'])**2 for c in rows)/len(rows)}
   metrics[model][control]=result
 comparisons={}
 for i,left in enumerate(models):
  for right in list(models)[i+1:]:
   l=prediction_map[left]['learned_head'];r=prediction_map[right]['learned_head'];wins=[0,0]
   for case in cases:
    if case['split']!='test':continue
    lc=(l[case['case_id']]>=.5)==bool(case['label'])
    rc=(r[case['case_id']]>=.5)==bool(case['label'])
    if lc and not rc:wins[0]+=1
    if rc and not lc:wins[1]+=1
   n=sum(wins)
   pval=min(1.,2.*sum(math.comb(n,k) for k in range(min(wins)+1))/(2**n)) if n else 1.
   comparisons[left+'__'+right]={'left_only_correct':wins[0],'right_only_correct':wins[1],'unadjusted_exact_mcnemar_p':pval}
 return {'schema':('hepta.e1-core-triad-real-cpu-numeric.v1' if core else
                   'hepta.e1-english-three-pretrained-numeric.v1'),
         'registered_core_triad':core,'cases':len(cases),'scores':metrics,
 'pairwise_test':comparisons,'resource_observations':resource_summary,'new_chinese_or_code_tasks_tested':False,
 'chronological_future_windows_tested':False,
 'independent_model_origin_and_run_signatures_verified':False,
 'independent_labels_or_ndu_verified':False,
 'same_host_total_lifecycle_budget_and_energy_verified':False,
 'Reader_sufficient_evidence_qualified':False,
 'production_no_change_checkpoint_authenticated':False,
 'true_future_three_window_evidence_available':False,'stem_winner_selected':False,
 'production_promotion_permitted':False,'authority':'DENY_ALL'}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--panel',type=Path,required=True)
 for model in MODELS:p.add_argument('--'+model.replace('_','-'),type=Path,required=True)
 p.add_argument('--output',type=Path,required=True);args=p.parse_args()
 reports={name:read(getattr(args,name)) for name in MODELS}
 panel=read(args.panel)
 if sha(canonical(panel))!='2f7a013648e16b60c74614b0fcf1496aa06475f7285f215adddaa51fe29e01a4':
  raise Invalid('not the preregistered archived 224-case source selection')
 result=evaluate(panel,reports)
 with args.output.open('x',encoding='utf8') as h:json.dump(result,h,sort_keys=True,indent=2,allow_nan=False);h.write('\n')
if __name__=='__main__':main()
