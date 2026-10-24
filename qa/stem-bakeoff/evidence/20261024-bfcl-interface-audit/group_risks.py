import json,collections
from pathlib import Path
P=Path(__file__).resolve().parent;g=json.loads((P/'groups.json').read_text());r=json.loads((P/'audit-results.json').read_text());parent=list(range(200))
def find(i):
 while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
 return i
for pairs in r['base_group_hash_collisions'].values():
 for ids in pairs:
  for i in ids[1:]:parent[find(i)]=find(ids[0])
c=collections.defaultdict(list)
for i in range(200):c[find(i)].append(i)
out={'mandatory_variant_groups':200,'conservative_cross_base_components':len(c),'cross_base_components':[v for v in c.values() if len(v)>1],'note':'Optional conservative grouping for identical path OR initial state; template reuse is potential leakage, not proof of identical task. No actual train/cal/test assignment created. All variants of a base must stay together.'}
(P/'grouping-risk-summary.json').write_text(json.dumps(out,indent=2));print(out)
