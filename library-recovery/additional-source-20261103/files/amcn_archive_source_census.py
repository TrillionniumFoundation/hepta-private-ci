"""Audit-only source-first census of the SHA-fixed original public LoCoMo archive.

No model execution, no Reader answer, no independently accepted human sufficiency.
This script assumes the original ZIP/LoCoMo file have already been verified by
SHA-256 and uses the byte-identical candidate source-first Python blob.
"""
import collections
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,'/mnt/data/amcn-local')
from amcn_core import Evidence,digest
from amcn_source_first import lexical_shortlist,source_first_weak_score

SOURCE_ZIP=Path('/mnt/data/amcn-original-pinned-model-material.zip')
DATA_FILE=Path('/mnt/data/amcn_verified_locomo_public.json')
ZIP_SHA='07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af'
DATA_SHA='79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'
SCOPE='amcn.historical.locomo.shadow'
GEN='locomo-archive-'+DATA_SHA[:12]
MAX_BYTES=1200

def verify_file(path,expected):
 sha=hashlib.sha256()
 with path.open('rb') as file:
  for chunk in iter(lambda: file.read(1048576),b''):sha.update(chunk)
 assert sha.hexdigest()==expected,(path,sha.hexdigest())
 return sha.hexdigest()

verify_file(SOURCE_ZIP,ZIP_SHA)
verify_file(DATA_FILE,DATA_SHA)
data=json.loads(DATA_FILE.read_text())
assert isinstance(data,list) and len(data)==10
family_list=sorted(('locomo:'+x['sample_id'] for x in data),key=digest)
n=len(family_list);train_end=max(4,n*6//10);select_end=min(n-2,max(train_end+1,n*8//10))
partitions={f:('train' if i<train_end else 'select' if i<select_end else 'future_a' if i==select_end else 'future_b') for i,f in enumerate(family_list)}
by_family={}
for s in data:
 fam='locomo:'+s['sample_id']
 convo=s['conversation'];docs=[]
 for sess in sorted((v for v in convo if v.startswith('session_') and v[8:].isdigit()),key=lambda v:int(v[8:])):
  for turn in convo[sess]:
   text=f"{turn['speaker']}: {turn['text']}"
   if turn.get('blip_caption'):
    text+='\n[provided image caption; not observed pixels] '+turn['blip_caption']
   raw=text.encode()
   if not 1<=len(raw)<=MAX_BYTES:continue
   docs.append(Evidence(fam+'/'+turn['dia_id'],fam,SCOPE,1,text,hashlib.sha256(raw).hexdigest(),GEN))
 qs=[]
 for i,q in enumerate(s['qa']):
  id=f'{fam}/q{i}'
  qs.append((id,q['question'],{fam+'/'+x for x in q.get('evidence',[])}))
 by_family[fam]={'questions':sorted(qs,key=lambda x:digest(x[0])),'documents':docs}
rows=[]
for fam in family_list:
 info=by_family[fam];docs=info['documents'];role=partitions[fam]
 qs=[(qid,q,refs) for qid,q,refs in info['questions'] if len(q.encode())<=512 and docs]
 result={'family':fam,'partition':role,'available_questions':len(qs),'eligible_source_documents':len(docs)}
 if not qs:
  result['admitted']=False;result['failure']='no_question_or_docs';rows.append(result);continue
 if role=='train':
  valid=None
  for qid,q,refs in qs:
   p=[d for d in docs if d.evidence_id in refs]
   ng=[d for d in docs if d.evidence_id not in refs]
   if p and ng:valid=(qid,p[0],ng[0]);break
  result['admitted']=valid is not None
  result['train_binary_rows']=2 if valid else 0
  if valid:
   ret=next(((qid,q,refs) for qid,q,refs in qs if qid!=valid[0]),None)
   if ret:
    plan=lexical_shortlist(ret[1],docs,scope=SCOPE,generation=GEN,top_k=16)
    m=source_first_weak_score(plan,sorted(ret[2]))
    result.update(retention_questions=1,retention_support_count=m['publisher_support_count'],retention_lexical_top1=m['lexical_hit_at_1'],retention_lexical_top16=m['lexical_any_hit_at_k'])
   else:result['retention_questions']=0
 else:
  qid,q,refs=qs[0]
  plan=lexical_shortlist(q,docs,scope=SCOPE,generation=GEN,top_k=16)
  m=source_first_weak_score(plan,sorted(refs))
  result.update(admitted=True,eval_questions=1,support_count=m['publisher_support_count'],lexical_top1=m['lexical_hit_at_1'],lexical_top16=m['lexical_any_hit_at_k'],candidate_count=plan['shortlist_size'])
 rows.append(result)
classes=('select','future_a','future_b','retention')
summary={}
for split in classes:
 subset=[x for x in rows if x['partition']==split] if split!='retention' else [x for x in rows if x['partition']=='train' and x.get('retention_questions')]
 key1='lexical_top1' if split!='retention' else 'retention_lexical_top1'
 key16='lexical_top16' if split!='retention' else 'retention_lexical_top16'
 summary[split]={'questions':len(subset),'lexical_hit_at_1':sum(bool(x.get(key1)) for x in subset),'lexical_any_hit_at_16':sum(bool(x.get(key16)) for x in subset)}
report={
 'schema':'hepta.amcn.offline.original-archive-source-first-audit.v1',
 'source_zip_sha256':ZIP_SHA,'lo_co_mo_original_sha256':DATA_SHA,
 'exact_source_first_git_blob_sha':'3483f59ef214ef95a62d431747c1e4ac0cc75c97',
 'original_artifact_id':11586991191,
 'partition_policy':'sha256-family-ordered-historical-60-20-10-10-not-future-time',
 'source_window_profile':'source-bytes-max-1200-question-bytes-max-512-BM25-top16',
 'source_family_total':n,
 'source_family_train_count':sum(x['partition']=='train' for x in rows),
 'train_binary_rows':sum(x.get('train_binary_rows',0) for x in rows),
 'source_family_admitted_train_count':sum(x.get('admitted',False) for x in rows if x['partition']=='train'),
 'source_only_weak_support_by_partition':summary,
 'per_family_census':rows,
 'reader_model_execution':False,
 'encoder_model_execution':False,
 'external_human_sufficient_evidence_review':False,
 'publisher_weak_support_only':True,
 'effective_independent_samples_qualified':False,
 'actual_future_calendar_windows':0,
 'production_accepted':False,
}
output=Path('/mnt/data/amcn_offline_sourcefirst_verified_receipt.json')
output.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
print('output',output,'SHA256',hashlib.sha256(output.read_bytes()).hexdigest())
print('summary',json.dumps({k:v for k,v in report.items() if k in ('source_family_total','train_binary_rows','source_family_admitted_train_count','source_only_weak_support_by_partition','actual_future_calendar_windows')},ensure_ascii=False,sort_keys=True))
