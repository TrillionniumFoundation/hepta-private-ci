"""Independent graph traversal, not union-find; no predictions or scores read."""
import csv,hashlib,json,unicodedata
from collections import defaultdict,Counter,deque
from pathlib import Path
P=Path(__file__).resolve().parent;O=P.parent/'cell-head-calibration-research'
H=lambda s:hashlib.sha256(s.encode()).hexdigest()
norm=lambda s:' '.join(unicodedata.normalize('NFKC',s).split()).casefold()
rows=[];index={};bykey=defaultdict(list);title_counts=Counter();title_lengths={}
for split in ['train','test']:
 with (O/f'{split}.csv').open(newline='') as f:
  for rowidx,r in enumerate(csv.reader(f)):
   title=norm(r[1]);full=norm(r[1]+'\n'+r[2]);th,fh=H(title),H(full);i=len(rows)
   rows.append((split,rowidx,int(r[0])-1,th,fh));index[(split,rowidx)]=i
   bykey[('t',th)].append(i);bykey[('f',fh)].append(i);title_counts[th]+=1;title_lengths[th]=len(title)
pilot={}
for split,rs in json.loads((O/'rows.json').read_text()).items():
 for r in rs:pilot[index[(r['source_split'],r['row_index_zero_based'])]]=split
seen=set();key_seen=set();components=[];pilot_cross=[];canonical={}
for start in range(len(rows)):
 if start in seen:continue
 queue=deque([start]);seen.add(start);comp=[]
 while queue:
  i=queue.popleft();comp.append(i)
  for key in [('t',rows[i][3]),('f',rows[i][4])]:
   if key in key_seen:continue
   key_seen.add(key)
   for j in bykey[key]:
    if j not in seen:seen.add(j);queue.append(j)
 ckey=min(rows[i][4] for i in comp)
 for i in comp:canonical[i]=ckey
 p=Counter(pilot[i] for i in comp if i in pilot)
 if 'test' in p and len(p)>1:pilot_cross.append(dict(component_key=ckey,source_component_rows=len(comp),pilot_members=dict(p)))
 components.append(comp)
selected=json.loads((P/'rows.json').read_text());selected_ids=[index[(r['source_split'],r['row_index_zero_based'])] for rs in selected.values() for r in rs]
reported=[r['component_key'] for rs in selected.values() for r in rs]
recomputed=[canonical[i] for i in selected_ids]
pilotkeys={canonical[i] for i in pilot}
ct=Counter();cross_sizes=[]
for comp in components:
 source={rows[i][0] for i in comp}
 if len(source)>1:
  ct['cross_official_components']+=1;ct['cross_official_rows']+=len(comp);cross_sizes.append(len(comp))
 if len({rows[i][2] for i in comp})>1:ct['label_conflict_components']+=1;ct['label_conflict_rows']+=len(comp)
 if any(i in pilot for i in comp):ct['old_exposure_components']+=1;ct['old_exposure_rows']+=len(comp)
blank=H('')
result={'algorithm':'Independent BFS of bipartite row-title/full-hash graph; source normalization recomputed independently. No test predictions read.','components':len(components),'counts':dict(ct),'component_keys_match_selected_manifest':reported==recomputed,'selected_components_unique':len(set(recomputed))==len(recomputed),'selected_old_components_overlap':len(set(recomputed)&pilotkeys),'empty_normalized_title_rows':title_counts.get(blank,0),'repeated_title_groups':sum(c>1 for c in title_counts.values()),'repeated_short_title_groups_le_20_chars':sum(c>1 and title_lengths[k]<=20 for k,c in title_counts.items()),'maximum_title_multiplicity':max(title_counts.values()),'maximum_component_size':max(map(len,components)),'cross_official_maximum_component_size':max(cross_sizes),'pilot_test_vs_other_split_components':pilot_cross,'pilot_test_vs_head_train_components':sum('head_train' in x['pilot_members'] for x in pilot_cross),'pilot_test_vs_temperature_components':sum('temperature' in x['pilot_members'] for x in pilot_cross),'pilot_test_vs_conformal_components':sum('conformal' in x['pilot_members'] for x in pilot_cross),'interpretation':'Equal titles are potential contamination proxies, not verified same-event families. Generic titles can overmerge; this is conservative exclusion, not semantic deduplication. Counts do not demonstrate semantic leakage.'}
(P/'title-component-audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
