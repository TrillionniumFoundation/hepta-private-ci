"""Select only; no embeddings, classifier fitting, or test scoring. Raw text local."""
import csv,hashlib,json,unicodedata,time
from collections import defaultdict
from pathlib import Path
P=Path(__file__).resolve().parent; O=P.parent/'cell-head-calibration-research'
H=lambda b:hashlib.sha256(b).hexdigest()
expected='b73cb06a5e441d07e0c38f0bb02350ee798f6e4cd30c70b51abc2163157faf1c'
if H((P/'protocol.json').read_bytes())!=expected:raise ValueError('protocol drift')
plan=json.loads((P/'protocol.json').read_text())
if H((O/'rows.json').read_bytes())!=plan['old_rows_sha256']:raise ValueError('old exclusion rows drift')
for split in ['train','test']:
 if H((O/f'{split}.csv').read_bytes())!=plan['dataset'][split+'_csv_sha256']:raise ValueError('CSV drift')
old={r['group_sha256'] for rs in json.loads((O/'rows.json').read_text()).values() for r in rs}
normalize=lambda t:' '.join(unicodedata.normalize('NFKC',t).split())
records=[];parents=[];seen={}
def root(i):
 while parents[i]!=i:parents[i]=parents[parents[i]];i=parents[i]
 return i
def union(a,b):
 a,b=root(a),root(b)
 if a!=b:parents[max(a,b)]=min(a,b)
for split in ['train','test']:
 with (O/f'{split}.csv').open(newline='') as f:
  for rowidx,r in enumerate(csv.reader(f)):
   text=normalize(r[1]+'\n'+r[2]);title=normalize(r[1]).casefold();full=H(text.casefold().encode());i=len(records);parents.append(i)
   records.append(dict(source_split=split,row_index_zero_based=rowidx,label=int(r[0])-1,text=text,group_sha256=full,normalized_text_sha256=H(text.encode()),title_sha256=H(title.encode())))
   for key in [('full',full),('title',H(title.encode()))]:
    if key in seen:union(i,seen[key])
    else:seen[key]=i
components=defaultdict(list)
for i,r in enumerate(records):components[root(i)].append(r)
eligible={'train':[],'test':[]};counts=defaultdict(int)
for rows in components.values():
 reasons=[]
 if len({r['source_split'] for r in rows})>1:reasons.append('cross_official_split')
 if len({r['label'] for r in rows})>1:reasons.append('label_conflict')
 if any(r['group_sha256'] in old for r in rows):reasons.append('old_exposure')
 for reason in reasons:counts[reason+'_components']+=1;counts[reason+'_rows']+=len(rows)
 if reasons:continue
 r=dict(min(rows,key=lambda r:r['row_index_zero_based']));r['component_key']=min(x['group_sha256'] for x in rows);r['component_rows']=len(rows)
 eligible[r['source_split']].append(r)
selected={}
for split,n in [('train',2560),('test',1600)]:
 eligible[split].sort(key=lambda r:H((plan['selection']['salt']+'|'+split+'|'+r['component_key']).encode()))
 selected[split]=eligible[split][:n]
 if len(selected[split])!=n:raise ValueError('insufficient eligible rows')
for n in plan['training_budgets']:
 if len({r['label'] for r in selected['train'][:n]})!=4:raise ValueError('missing training class; abort without reseed')
keys=[r['component_key'] for rs in selected.values() for r in rs]
if len(set(keys))!=4160:raise ValueError('component overlap')
if any(r['group_sha256'] in old for rs in selected.values() for r in rs):raise ValueError('old exposure')
def save(name,data):
 b=(json.dumps(data,indent=2,sort_keys=True)+'\n').encode()
 with (P/name).open('xb') as f:f.write(b)
 return H(b)
raw=save('selected-local-only.json',selected)
manifest=save('rows.json',{s:[{k:v for k,v in r.items() if k not in ['text','label']} for r in rows] for s,rows in selected.items()})
labels=save('labels-local-only.json',{s:[r['label'] for r in rows] for s,rows in selected.items()})
partition={}
for split,rs in selected.items():
 b=(json.dumps([r['label'] for r in rs])+'\n').encode()
 with (P/(split+'-labels-local-only.json')).open('xb') as f:f.write(b)
 partition[split]={'file':split+'-labels-local-only.json','sha256':H(b),'rows':len(rs)}
with (P/'label-partition-receipt.json').open('x') as f:f.write(json.dumps(partition,indent=2)+'\n')
print(json.dumps({'protocol_sha256':expected,'raw_rows':len(records),'title_fulltext_components':len(components),'exclusions_overlapping_counts':dict(counts),'eligible_components':{s:len(v) for s,v in eligible.items()},'selected':{s:len(v) for s,v in selected.items()},'old_selected_count':len(old),'selected_old_fulltext_overlap':0,'selected_component_overlap':0,'rows_sha256':manifest,'labels_local_sha256':labels,'selected_local_sha256':raw,'new_test_scores_seen':False},indent=2))
