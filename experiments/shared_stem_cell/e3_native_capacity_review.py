"""Independent stdlib-only paired accuracy audit of matched Gemma2 Heads.

Consumes source-sealed original five-arm predictions and separately reopened
original historical TEST labels. DOES NOT import trained Head or Encoder code.
"""
from __future__ import annotations
import hashlib
import json
import math
from math import comb,fsum

SCHEMA='hepta.e3.native-same-head-independent-review.v1'
RECEIPT='hepta.e3.native-gemma2-same-head-contrast.v1'
FIVE='hepta.e3.historical-five-arm-source-predictions.v1'
MODEL=('google/embeddinggemma-2','914f7f89142e33e77833254d9c9b90c3cef7303b')
class CapacityReviewError(ValueError):pass

def require(cond, reason):
 if not cond:raise CapacityReviewError(reason)

def sha(x,n=64):
 return type(x) is str and len(x)==n and all(c in '0123456789abcdef' for c in x)

def prob(x):
 require(type(x) is list and len(x)==4 and all(type(v) in (int,float)
         and math.isfinite(v) and 0<=v<=1 for v in x) and
         abs(fsum(x)-1)<1e-4,'invalid four-class probability')
 return x

def exact_p(rescued,harmed):
 n=rescued+harmed
 return min(1.,2*sum(comb(n,k) for k in range(min(rescued,harmed)+1))/2**n) if n else 1.

def score(receipt, combined, held):
 require(type(receipt) is dict and receipt.get('schema')==RECEIPT and
         receipt.get('production_accepted') is False and receipt.get('authority')=='DENY_ALL' and
         receipt.get('cost_matched') is False and
         receipt.get('held_labels_visible_during_fit') is False and
         receipt.get('same_initialization') is True and
         receipt.get('identical_optimizer_schedule') is True,
         'false matched-Head lineage or authority')
 model=receipt.get('model')
 require(type(model) is dict and
         (model.get('repo'),model.get('revision'))==MODEL and
         sha(model.get('pipeline_digest')),'missing original native model identity')
 for key,num in [('heads_complete_trainable_params_each',769),
                 ('train_steps_each',80),('train_examples',96),('test_examples',64)]:
  require(type(receipt.get(key)) is int and receipt[key]==num,
          'mismatched matched-Head train budget '+key)
 for field in ('initial_same_head_digest','text_trained_head_digest','joint_trained_head_digest'):
  require(sha(receipt.get(field)),'missing Head identity '+field)
 require(type(combined) is dict and combined.get('schema')==FIVE and
         combined.get('authority')=='DENY_ALL' and
         combined.get('production_accepted') is False and
         combined.get('stem_winner') is None and
         combined.get('human_visual_necessity_adjudicated') is False and
         combined.get('cohort')=='historical_scienceqa_test_not_future' and
         receipt.get('source_sha256')==combined.get('source_sha256') and
         sha(combined.get('source_sha256')),'unmatched historical source')
 rows=receipt.get('rows');sources=combined.get('cases')
 require(type(rows) is list and len(rows)==64 and
         type(sources) is list and len(sources)==64 and
         type(held) is list and len(held)==64,'missing original heldout cohort')
 by_source={}
 for item in sources:
  require(type(item) is dict and
          set(item)=={'id','group','source_input_sha256','arms'} and
          sha(item.get('id')) and sha(item.get('group')) and
          sha(item.get('source_input_sha256')) and item['id'] not in by_source,
          'invalid registered source')
  by_source[item['id']]=item
 label_map={}
 for item in held:
  require(type(item) is dict and
          set(item)=={'id','group','split','label'} and item.get('split')=='test' and
          sha(item.get('id')) and sha(item.get('group')) and
          type(item.get('label')) is int and 0<=item['label']<4 and
          item['id'] not in label_map,'unsafe historical label')
  label_map[item['id']]=item
 correct={'native_text_same_head':0,'native_joint_same_head':0}
 brier={key:[] for key in correct}
 rescues=harms=0
 seen=set()
 for item in rows:
  require(type(item) is dict and set(item)=={
   'id','group','source_input_sha256','text_only_probabilities',
   'joint_text_image_probabilities'} and item.get('id') in by_source and
   item['id'] in label_map and item['id'] not in seen,'incomplete matched Head cases')
  seen.add(item['id'])
  ref=by_source[item['id']]; lab=label_map[item['id']]
  require(item['group']==ref['group']==lab['group'] and
          item['source_input_sha256']==ref['source_input_sha256'],
          'mixed original source/label/image geometry')
  label=lab['label']
  v0=prob(item['text_only_probabilities']);v1=prob(item['joint_text_image_probabilities'])
  yes=[]
  for key,probs in [('native_text_same_head',v0),('native_joint_same_head',v1)]:
   guess=max(range(4),key=lambda j:(probs[j],-j))
   iscorrect=int(guess==label)
   yes.append(iscorrect)
   correct[key]+=iscorrect
   brier[key].append(fsum((probs[k]-int(k==label))**2 for k in range(4))/4)
  rescues+=int(yes==[0,1]);harms+=int(yes==[1,0])
 require(seen==set(by_source)==set(label_map),'missing original labels/cases')
 return {'schema':SCHEMA,'source_sha256':combined['source_sha256'],
         'model':dict(repo=MODEL[0],revision=MODEL[1]),
         'original_test_cases':64,'complete_trainable_parameters_per_head':769,
         'train_steps_each':80,'text_only_correct':correct['native_text_same_head'],
         'joint_correct':correct['native_joint_same_head'],
         'text_only_accuracy':correct['native_text_same_head']/64,
         'joint_accuracy':correct['native_joint_same_head']/64,
         'text_only_brier':fsum(brier['native_text_same_head'])/64,
         'joint_brier':fsum(brier['native_joint_same_head'])/64,
         'joint_rescued_vs_same_head_text':rescues,
         'joint_harmed_vs_same_head_text':harms,
         'mcnemar_two_sided_unadjusted_p':exact_p(rescues,harms),
         'is_exploratory_posthoc_control':True,'human_necessity_independently_adjudicated':False,
         'cost_matched':False,'production_accepted':False,
         'stem_winner':None,'authority':'DENY_ALL'}
