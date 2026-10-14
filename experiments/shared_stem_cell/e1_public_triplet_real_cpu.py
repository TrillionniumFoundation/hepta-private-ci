#!/usr/bin/env python3
"""Pinned real CPU Encoder + actual <=2K Head public pilot. English AG News only.

Loads reviewed separate research model interfaces; no stub fallback, no production
Neuron, FinalUse, source signer, longitudinal NDU or physical attestation.
"""
from __future__ import annotations
import argparse, copy, hashlib, json, math, resource, sys, time
from pathlib import Path

MODELS={
 'granite_97m_r2':('granite-97m-multilingual-r2','835ad14087e140460703cf0fae09f97d469d65c2',384),
 'mmbert_small':('mmbert-small','0eb3d056ec1d6333cf4e19b0966dfde342a41a3a',384),
 'embeddinggemma_2_text':('google/embeddinggemma-2','914f7f89142e33e77833254d9c9b90c3cef7303b',256)}
SPLITS={'train':128,'calibration':32,'test':64}
SOURCE_FILES={'train':'cc35afe9d5e7ff01878c9aeba08bb0bdfa16947702789530b216a580a1bc09d5',
 'calibration_test':'3171d3aeee227372165bb0f9e84ebf2bfaf5fc870d034f33a5fc568e7995c672'}
TEMPERATURES=(.5,.75,1.,1.5,2.,3.,4.)
class Invalid(ValueError):pass
def canonical(v):
 return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf8')
def sha(b):return hashlib.sha256(b).hexdigest()
def pairs(p):
 d={}
 for k,v in p:
  if k in d:raise Invalid('duplicate JSON field')
  d[k]=v
 return d
def load_panel(path):
 raw=Path(path).read_bytes()
 if not 10<len(raw)<4*1024*1024:raise Invalid('unbounded dataset')
 panel=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(Invalid('nonfinite JSON')))
 if (panel.get('schema')!='hepta.stem.agnews-binary-capability-panel.v1' or
     panel.get('dataset')!='szhuggingface/ag_news' or panel.get('dataset_commit_prefix')!='98c5322' or
     panel.get('dataset_file_sha256')!=SOURCE_FILES or panel.get('label_mapping')!={'world':0,'sports':1} or
     panel.get('case_count')!=224 or panel.get('cross_sectional_not_future') is not True or
     panel.get('production_promotion')!='DENY_ALL'):raise Invalid('wrong source panel provenance')
 cases=panel.get('cases')
 if type(cases) is not list or len(cases)!=224:raise Invalid('case count')
 counts={k:0 for k in SPLITS};seen=set()
 for c in cases:
  if type(c) is not dict or c.get('split') not in SPLITS or type(c.get('label')) is not int or c['label'] not in (0,1):
   raise Invalid('invalid case')
  x=c.get('joint_input')
  if (type(x) is not dict or set(x)!={'state','question','options'} or x['options']!=['world','sports'] or
      x['question']!='Which category does the news report describe?' or type(x['state']) is not str or not x['state']):
   raise Invalid('altered question, options or text')
  source=sha(x['state'].encode())
  if (c.get('case_id')!=source[:24] or c.get('source_digest')!=source or c.get('group_id')!=source or
      c.get('joint_input_digest')!=sha(canonical(x)) or source in seen):raise Invalid('input leakage')
  seen.add(source);counts[c['split']]+=1
 if counts!=SPLITS:raise Invalid('altered source splits')
 return panel,sha(canonical(panel))
def encode_pretrained(cases,model,compact_dir,gemma_dir,manifest):
 name,revision,width=MODELS[model];begin=time.perf_counter_ns()
 if model!='embeddinggemma_2_text':
  sys.path.insert(0,str(Path(compact_dir)/'qualification/neuron-stem'))
  from compact_stem_trial import FrozenCompactStem
  backend=FrozenCompactStem(name,revision,device='cpu',max_tokens=512)
 else:
  sys.path.insert(0,str(Path(gemma_dir)/'qualification/neuron-dynamic-learning'))
  from embeddinggemma2_shadow import FrozenGemmaShadow
  backend=FrozenGemmaShadow(Path(manifest),device='cpu')
  if backend.manifest['revision']!=revision or backend.manifest['profile']!='text' or backend.manifest['dimension']!=256:
   raise Invalid('unexpected Gemma identity')
 load_ms=(time.perf_counter_ns()-begin)/1e6
 vectors={};tokens={};digests={};durations={}
 for c in cases:
  key=c['case_id'];joint=c['joint_input'];start=time.perf_counter_ns()
  if model!='embeddinggemma_2_text':
   feature,proof,meta=backend.encode(joint,allow_truncation=False)
   values=feature.detach().cpu().reshape(-1).tolist()
   n=meta['original_tokens'];digests[key]=proof['research_only_feature_sha256']
  else:
   text=canonical(joint).decode('utf8')
   prompt=backend.model.prompts.get('Classification')
   if type(prompt) is not str:raise Invalid('missing official classification prompt')
   n=len(backend.model.tokenizer(prompt+text,truncation=False,add_special_tokens=True)['input_ids'])
   request={'scope_id':'public.agnews','principal_id':'shadow.cpu','purpose_id':'capability.noeffects',
            'cell_id':'case.'+key,'generation':1,'authority_epoch':1,
            'input':{'modality':'text','role':'classification','value':text,'sha256':sha(text.encode())}}
   result=backend.encode_cells([request])
   if result.get('physical_local_model_execution') is not True or len(result.get('rows',[]))!=1:
    raise Invalid('missing physical Gemma execution')
   item=result['rows'][0];q=item.get('features_q24')
   if item.get('input_digest')!=request['input']['sha256'] or type(q) is not list or len(q)!=width:
    raise Invalid('Gemma Q24/source drift')
   values=[float(v)/(1<<24) for v in q];digests[key]=item['feature_digest']
  if type(n) is not int or not 1<=n<=512 or len(values)!=width or not all(math.isfinite(float(x)) and -8<=float(x)<=8 for x in values):
   raise Invalid('truncated or nonfinite feature')
  vectors[key]=[round(float(x)*(1<<24))/(1<<24) for x in values]
  tokens[key]=n;durations[key]=(time.perf_counter_ns()-start)/1e6
 return vectors,tokens,digests,{'load_ms':load_ms,'encode_ms_by_case':durations,
     'local_model_api_requests':len(cases),'physical_transformer_forward_count_attested':False}
def fit_heads(panel,model,vectors,*,seed=20261014,steps=40,lr=.15):
 import torch
 import torch.nn.functional as F
 width=MODELS[model][2];cases=panel['cases']
 if set(vectors)!={c['case_id'] for c in cases} or any(
    len(vectors[c['case_id']])!=width or not all(math.isfinite(float(x)) for x in vectors[c['case_id']])
    for c in cases):raise Invalid('incomplete or wrong-width feature bank')
 if type(seed) is not int or type(steps) is not int or not 1<=steps<=128 or not 0<lr<=1:raise Invalid('optimizer budget')
 train=[c for c in cases if c['split']=='train'];cal=[c for c in cases if c['split']=='calibration']
 def x(rows):return torch.tensor([vectors[c['case_id']] for c in rows],dtype=torch.float32)
 torch.manual_seed(seed);head=torch.nn.Linear(width,2);param=sum(p.numel() for p in head.parameters())
 if not 0<param<=2048:raise Invalid('Head exceeds parameter ceiling')
 frozen=copy.deepcopy(head).eval();start=time.perf_counter_ns()
 train_x=x(train);labels=torch.tensor([c['label'] for c in train],dtype=torch.long)
 optimizer=torch.optim.SGD(head.parameters(),lr=lr)
 for _ in range(steps):
  optimizer.zero_grad(set_to_none=True);loss=F.cross_entropy(head(train_x),labels)
  if not bool(torch.isfinite(loss)):raise Invalid('nonfinite loss')
  loss.backward();optimizer.step()
 elapsed=(time.perf_counter_ns()-start)/1e6
 controls={}
 for name,module in (('frozen_head',frozen),('learned_head',head.eval())):
  digest=hashlib.sha256(b'hepta.e1-english-head-v1')
  for key,value in sorted(module.state_dict().items()):
   digest.update(key.encode()+b'\0'+value.detach().cpu().contiguous().numpy().tobytes())
  with torch.inference_mode():
   cal_logits=module(x(cal));y=torch.tensor([c['label'] for c in cal],dtype=torch.long)
   temp=min(TEMPERATURES,key=lambda t:float(F.cross_entropy(cal_logits/t,y)))
   scored=[c for c in cases if c['split']!='train']
   probs=F.softmax(module(x(scored))/temp,dim=-1).tolist()
  controls[name]={'head_sha256':digest.hexdigest(),'calibration_temperature':temp,
    'predictions':[{'case_id':c['case_id'],'joint_input_digest':c['joint_input_digest'],
      'split':c['split'],'positive_probability':float(p[1])} for c,p in zip(scored,probs)]}
 return {'head_parameter_count':param,'steps':steps,'seed':seed,'learning_rate':lr,
   'train_case_ids_sha256':sha(canonical([c['case_id'] for c in train])),
   'train_time_ms':elapsed,'controls':controls,
   'training_test_labels_accessed':False,'retrospective_public_labels_available_in_process':True}
def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--panel',type=Path,required=True);p.add_argument('--model',choices=sorted(MODELS),required=True)
 p.add_argument('--compact-checkout',type=Path);p.add_argument('--gemma-checkout',type=Path)
 p.add_argument('--gemma-manifest',type=Path);p.add_argument('--output',type=Path,required=True)
 p.add_argument('--e2-output',type=Path,default=None)
 a=p.parse_args()
 if a.output.exists() or (a.e2_output is not None and (a.e2_output.exists() or a.e2_output==a.output)):
  raise FileExistsError('create-only evidence; E1 and E2 must have distinct unused paths')
 if a.model=='embeddinggemma_2_text' and (a.gemma_checkout is None or a.gemma_manifest is None):
  raise Invalid('reviewed Gemma source and complete verified snapshot required')
 if a.model!='embeddinggemma_2_text' and a.compact_checkout is None:raise Invalid('reviewed compact source required')
 panel,panel_sha=load_panel(a.panel)
 if panel_sha!='2f7a013648e16b60c74614b0fcf1496aa06475f7285f215adddaa51fe29e01a4':
  raise Invalid('source selection differs from exact archived physical study')
 start=time.perf_counter_ns();cpu=time.process_time_ns()
 vectors,tokens,digests,physical=encode_pretrained(panel['cases'],a.model,a.compact_checkout,a.gemma_checkout,a.gemma_manifest)
 from e1e2_q24_identity import feature_inventory
 bank=feature_inventory([case['case_id'] for case in panel['cases']],vectors)
 fit=fit_heads(panel,a.model,vectors)
 out={'schema':'hepta.e1-english-public-pretrained-head.v1','model':a.model,
      'model_name':MODELS[a.model][0],'model_revision':MODELS[a.model][1],
      'feature_width':MODELS[a.model][2],'public_panel_sha256':panel_sha,
      'public_dataset_is_chronological_future':False,'english_only':True,
      'actual_pretrained_local_weight_execution_claimed':True,'model_origin_independently_authenticated':False,
      'physical_transformer_forward_count_attested':False,'tokens_per_case':tokens,
      'features_q24_identity':digests,'frozen_feature_bank_identity':bank,'physical_observations':physical,'fitting':fit,
      'wall_ms':(time.perf_counter_ns()-start)/1e6,'cpu_process_ms':(time.process_time_ns()-cpu)/1e6,
      'process_lifetime_peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
      'future_ndu_verified':False,'production_promotion_permitted':False,'authority':'DENY_ALL'}
 with a.output.open('x',encoding='utf8') as h:json.dump(out,h,sort_keys=True,allow_nan=False);h.write('\n')
 if a.e2_output is not None:
  from e2_feature_residual_study import study
  e2=study(panel,a.model,vectors,seed=20261014,steps=40,learning_rate=.15)
  for original,variant in (('frozen_head','frozen_head'),('learned_head','from_zero')):
   e1_rows=fit['controls'][original]['predictions']
   e2_rows=e2['arms'][variant]['predictions']
   if len(e1_rows)!=len(e2_rows) or any(
     x['case_id']!=y['case_id'] or
     abs(x['positive_probability']-y['positive_probability'])>1e-6
     for x,y in zip(e1_rows,e2_rows)
   ):
    raise Invalid('E2 repeated Head control disagrees with E1 original training')
  e2['source_e1_report_sha256']=sha(a.output.read_bytes())
  e2['public_panel_sha256']=panel_sha
  e2['source_model_revision']=MODELS[a.model][1]
  e2['existing_frozen_encoder_features_reused']=True
  e2['additional_encoder_model_loads']=0
  e2['additional_encoder_feature_forwards']=0
  with a.e2_output.open('x',encoding='utf8') as h:
   json.dump(e2,h,sort_keys=True,allow_nan=False);h.write('\n')
if __name__=='__main__':main()
