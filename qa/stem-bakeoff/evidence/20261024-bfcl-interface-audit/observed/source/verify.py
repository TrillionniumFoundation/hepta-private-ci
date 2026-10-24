import json,hashlib,ast,collections
from pathlib import Path
P=Path(__file__).resolve().parent.parent/'cell-bfcl-interface-audit';I=P/'input';J=lambda p:json.loads(p.read_text());H=lambda b:hashlib.sha256(b).hexdigest()
m=J(P/'upstream-manifest.json');tr=J(Path(__file__).parent/'upstream-tree.json');assert tr['sha']==m['pin'] and not tr['truncated'];tree={r['path']:r for r in tr['tree']}
files=m['files']+J(P/'extra-source-manifest.json')
for f in files:
 b=(I/Path(f['path']).name).read_bytes();assert len(b)==f['bytes']==tree[f['path']]['size'];assert hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()==f['git_blob_sha']==tree[f['path']]['sha']
rows={c:{int(r['id'].rsplit('_',1)[1]):r for r in map(json.loads,(I/f'BFCL_v4_multi_turn_{c}.json').read_text().splitlines())} for c in ['base','miss_func','miss_param']}
assert all(set(rr)==set(range(200)) for rr in rows.values());g=J(P/'groups.json');assert len(g)==200
for i,e in enumerate(g):
 assert e['base_group']==i
 for c in rows:
  r=rows[c][i];assert e['ids'][c]==r['id']
  for k,eq in e['equality_to_base'][c].items():assert eq==(r.get(k)==rows['base'][i].get(k))
  for k,h in e['sha256'][c].items():assert h==H(json.dumps(r.get(k),sort_keys=True,separators=(',',':'),ensure_ascii=False).encode())
assert [sum(rows[c][i]['initial_config']!=rows['base'][i]['initial_config'] for i in range(200)) for c in ['miss_func','miss_param']]==[7,9]
# All variants, not merely base rows, included in independent collision screen.
adj={i:{i} for i in range(200)}
for field in ['path','initial_config']:
 bins=collections.defaultdict(set)
 for rr in rows.values():
  for i,r in rr.items():bins[json.dumps(r[field],sort_keys=True)].add(i)
 for ids in bins.values():
  for i in ids:adj[i].update(ids)
seen=set();components=[]
for i in range(200):
 if i in seen:continue
 todo=[i];c=set()
 while todo:
  n=todo.pop()
  if n in c:continue
  c.add(n);todo.extend(adj[n]-c)
 seen.update(c);components.append(sorted(c))
assert len(components)==192;assert sorted(c for c in components if len(c)>1)==sorted(J(P/'grouping-risk-summary.json')['cross_base_components'])
clsfiles={'GorillaFileSystem':'gorilla_file_system','VehicleControlAPI':'vehicle_control','TradingBot':'trading_bot','TravelAPI':'travel_booking','MessageAPI':'message_api','TwitterAPI':'posting_api','TicketAPI':'ticket_api','MathAPI':'math_api'}
docs={c:{r['name']:r for r in map(json.loads,(I/(f+'.json')).read_text().splitlines())} for c,f in clsfiles.items()};counts=collections.Counter(f for r in rows['base'].values() for f in set(r['path']));inv=J(P/'function-interface-inventory.json');assert len(inv)==len(counts)==76;missing=[]
for e in inv:
 name=e['original_function'];c,f=name.split('.');d=docs[c].get(f,{});assert e['base_groups_using']==counts[name];assert e['official_schema_found']==bool(d);assert e['parameter_schema']==d.get('parameters') and e['response_schema']==d.get('response');assert not e['exact_mapping_supported']
 if not d:
  methods={n.name for n in ast.walk(ast.parse((I/(clsfiles[c]+'.py')).read_text())) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))};assert f not in methods;missing.append(name)
assert len(missing)==6;assert sum(e['hepta_analogy_only'] is not None for e in inv)==3
b=(P.parent/'cell-feature-snapshot-profile/baseline.py').read_bytes();assert H(b)=='56f88a126c1e0e55cd1b17db81bdce9ab205d0f6ea1196f71144235cd8d38e4d'
out={'status':'PASS_INTERFACE_AUDIT_ONLY','official_pin':m['pin'],'verified_files':len(files),'bytes':sum(f['bytes'] for f in files),'variants':600,'base_groups':200,'all_variant_cross_base_components':192,'distinct_path_names':76,'missing_schema_and_source_names':missing,'exact_hepta_mapping_verified':False,'trained_scored_or_executed_upstream':False}
(Path(__file__).parent/'verification.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
