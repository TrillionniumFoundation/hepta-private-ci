"""Immutable original LoCoMo source-only temporal graph diagnostic.

No model/Reader calls, no production HNMF execution, no source publication.
Edges join only consecutive retained turns *within an original session*.
The graph expansion reads no publisher target IDs; those are opened after
candidate sets have been computed.
"""
import collections
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,'/mnt/data/amcn-local')
from amcn_core import Evidence,digest
from amcn_source_first import lexical_shortlist,WORDS

PUBLIC=Path('/mnt/data/amcn_verified_locomo_public.json')
EXPECTED='79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'
with PUBLIC.open('rb') as f:raw=f.read()
assert hashlib.sha256(raw).hexdigest()==EXPECTED
SCOPE='amcn.historical.locomo.shadow';GEN='locomo-archive-'+EXPECTED[:12]
samples=json.loads(raw)
families=sorted(['locomo:'+s['sample_id'] for s in samples],key=digest)
N=len(families);tr=max(4,N*6//10);sel=min(N-2,max(tr+1,N*8//10))
parts={f:('train' if i<tr else 'select' if i<sel else 'future_a' if i==sel else 'future_b') for i,f in enumerate(families)}

def make_history(sample):
 fam='locomo:'+sample['sample_id'];docs=[];adj=collections.defaultdict(set)
 convo=sample['conversation'];sessions=sorted((k for k in convo if k.startswith('session_') and k[8:].isdigit()),key=lambda k:int(k[8:]))
 for sess in sessions:
  prior_admitted_id=None
  for t in convo[sess]:
   text=f"{t['speaker']}: {t['text']}"
   if t.get('blip_caption'):text+='\n[provided image caption; not observed pixels] '+t['blip_caption']
   blob=text.encode()
   if not 1<=len(blob)<=1200:
    # A dropped source must break adjacency, never bridge missing evidence.
    prior_admitted_id=None
    continue
   eid=fam+'/'+t['dia_id']
   docs.append(Evidence(eid,fam,SCOPE,1,text,hashlib.sha256(blob).hexdigest(),GEN))
   if prior_admitted_id is not None:
    adj[prior_admitted_id].add(eid)
    adj[eid].add(prior_admitted_id)
   prior_admitted_id=eid
 qs=sorted([(fam+'/q'+str(i),q['question'],{fam+'/'+r for r in q.get('evidence',[])}) for i,q in enumerate(sample['qa'])],key=lambda x:digest(x[0]))
 return docs,adj,qs

def select_question(fam, docs, qs):
 eligible=[(qid,text,support) for qid,text,support in qs if docs and len(text.encode())<=512]
 if parts[fam]!='train':return eligible[0],parts[fam]
 chosen=next((qid for qid,text,support in eligible if any(d.evidence_id in support for d in docs) and any(d.evidence_id not in support for d in docs)),None)
 assert chosen is not None
 return next((q for q in eligible if q[0]!=chosen)), 'retention'

def full_ranking(query,docs):
 from math import log
 terms=sorted(set(WORDS.findall(query.casefold())))
 ordered=sorted(docs,key=lambda x:x.evidence_id)
 bags=[collections.Counter(WORDS.findall(d.text.casefold())) for d in ordered]
 avg=max(1.,sum(sum(b.values()) for b in bags)/len(bags))
 df={t:sum(t in b for b in bags) for t in terms}
 scored=[]
 for d,b in zip(ordered,bags):
  size=sum(b.values());score=0.
  for t in terms:
   tf=b.get(t,0)
   if tf:score+=log(1+(len(ordered)-df[t]+.5)/(df[t]+.5)) * (2.2*tf/(tf+1.2*(.25+.75*size/avg)))
  scored.append((d.evidence_id,score))
 scored.sort(key=lambda x:(-x[1],x[0]))
 return [sid for sid,_ in scored]

report=[]
for sample in samples:
 fam='locomo:'+sample['sample_id'];docs,edges,qs=make_history(sample)
 (qid,question,support),role=select_question(fam,docs,qs)
 plan=lexical_shortlist(question,docs,scope=SCOPE,generation=GEN,top_k=16)
 full=full_ranking(question,docs)
 assert plan['ranked_source_ids']==full[:16]
 initial=set(plan['ranked_source_ids']);frontier=set(initial);visited=set(initial)
 for _ in range(2):
  neighbors={v for u in frontier for v in edges[u]}
  frontier=neighbors-visited;visited|=neighbors
 # The original source can have >512 rows; graph expansion uses only 2-hop
 # bounded local projection, not a second independent authorizing store.
 assert len(visited)<=512
 by_id={d.evidence_id:d for d in docs}
 source_bytes=lambda collection:sum(len(by_id[i].text.encode()) for i in collection)
 weak_hit=lambda collection:len(set(collection)&support)
 graph=set(visited)
 report.append({
  'family':fam,'split':role,'query_sha256':digest(qid),
  'eligible_document_count':len(docs),'publisher_weak_support_count':len(support),
  'lexical_16_supports':weak_hit(full[:16]),
  'lexical_64_supports':weak_hit(full[:64]),
  'lexical_72_supports':weak_hit(full[:72]),
  'lexical_128_supports':weak_hit(full[:128]),
  'temporal_2hop_supports':weak_hit(graph),
  'temporal_nodes':len(graph),'temporal_extra_nodes':len(graph)-len(initial),
  'lexical_16_source_bytes':source_bytes(full[:16]),
  'lexical_64_source_bytes':source_bytes(full[:64]),
  'lexical_72_source_bytes':source_bytes(full[:72]),
  'temporal_2hop_source_bytes':source_bytes(graph),
  'publisher_annotation_is_semantic_entailment':False,
 })
report.sort(key=lambda x:(x['split'],x['family']))
summary={}
for arm in ('lexical_16','lexical_64','lexical_72','lexical_128','temporal_2hop'):
 summary[arm]={
  'case_any_support':sum(r[arm+'_supports']>0 for r in report),
  'case_all_support':sum(r[arm+'_supports']==r['publisher_weak_support_count'] for r in report),
  'supported_source_occurrences':sum(r[arm+'_supports'] for r in report),
  'total_original_source_bytes':sum(r[arm+'_source_bytes'] for r in report) if all(arm+'_source_bytes' in r for r in report) else None,
 }
answer={'schema':'hepta.amcn.historical-fixed-temporal-graph-data-audit.v1',
 'original_locomo_sha256':EXPECTED,'source_first_candidate_blob':'3483f59ef214ef95a62d431747c1e4ac0cc75c97',
 'case_count':len(report),'max_temporal_hops':2,
 'edge_semantics':'bidirectional adjacency only between original consecutive admitted turns; any omitted source breaks the chain; no causal truth claim',
 'summary':summary,'cases':report,
 'learned_graph_executed':False,'actual_hnmf_native_graph_executed':False,
 'reader_model_calls':0,'encoder_model_calls':0,
 'publisher_source_support_not_human_entailment':True,
 'future_calendar_windows_observed':0,'production_accepted':False}
path=Path('/mnt/data/amcn_historical_temporal_graph_verified_receipt.json')
path.write_text(json.dumps(answer,indent=2,sort_keys=True,ensure_ascii=False)+'\n')
print('OUTPUT',path,'sha256',hashlib.sha256(path.read_bytes()).hexdigest())
for k,v in summary.items():print(k,v)
print('temporal_nodes_min_max',min(r['temporal_nodes'] for r in report),max(r['temporal_nodes'] for r in report))
