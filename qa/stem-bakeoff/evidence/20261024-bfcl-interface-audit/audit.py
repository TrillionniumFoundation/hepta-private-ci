"""Read-only metadata/schema/group audit; no external code imported or task execution."""
import json,hashlib,collections
from pathlib import Path
P=Path(__file__).resolve().parent;I=P/'input'
J=lambda p:json.loads(p.read_text())
H=lambda b:hashlib.sha256(b).hexdigest()
def digest(x):return H(json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode())
def save(n,x):(P/n).write_text(json.dumps(x,indent=2,ensure_ascii=False))
manifest=J(P/'upstream-manifest.json');verified=[]
for f in manifest['files']:
 p=I/Path(f['path']).name;b=p.read_bytes();gh=hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
 assert gh==f['git_blob_sha'] and len(b)==f['bytes'],p
 verified.append(f|{'sha256':H(b)})
sets={c:[json.loads(l) for l in (I/f'BFCL_v4_multi_turn_{c}.json').read_text().splitlines()] for c in ['base','miss_func','miss_param']}
maps={c:{int(r['id'].removeprefix('multi_turn_'+c+'_')):r for r in rr} for c,rr in sets.items()}
assert all(len(rr)==200 for rr in sets.values());assert all(set(m)==set(range(200)) for m in maps.values())
groups=[];diffs=collections.Counter()
for i in range(200):
 rows={c:m[i] for c,m in maps.items()};base=rows['base'];g={'base_group':i,'ids':{c:r['id'] for c,r in rows.items()},'equality_to_base':{},'sha256':{},'base_path':base['path'],'involved_classes':base['involved_classes'],'turn_counts':{c:len(r['question']) for c,r in rows.items()}}
 for c,r in rows.items():
  eq={k:r.get(k)==base.get(k) for k in ['path','initial_config','involved_classes','excluded_function','question']};g['equality_to_base'][c]=eq
  for k,v in eq.items():
   if not v:diffs[c+':'+k]+=1
  g['sha256'][c]={k:digest(r.get(k)) for k in ['path','initial_config','question']}
 groups.append(g)
# Record collisions rather than presume suffix alone proves independence.
components={}
for key in ['path','initial_config']:
 d=collections.defaultdict(list)
 for i,r in maps['base'].items():d[digest(r[key])].append(i)
 components[key]=[v for v in d.values() if len(v)>1]
classfiles={'GorillaFileSystem':'gorilla_file_system','VehicleControlAPI':'vehicle_control','TradingBot':'trading_bot','TravelAPI':'travel_booking','MessageAPI':'message_api','TwitterAPI':'posting_api','TicketAPI':'ticket_api','MathAPI':'math_api'}
docs={c:{r['name']:r for r in [json.loads(l) for l in (I/(f+'.json')).read_text().splitlines()]} for c,f in classfiles.items()}
used=collections.Counter(fn for r in maps['base'].values() for fn in set(r['path']));inventory=[]
for full,n in sorted(used.items()):
 cls,fn=full.split('.');d=docs[cls].get(fn,{});required=d.get('parameters',{}).get('required',[])
 analog={'GorillaFileSystem.cd':'navigate','GorillaFileSystem.cat':'open_path','MessageAPI.send_message':'notify'}.get(full)
 inventory.append({'original_function':full,'official_schema_found':bool(d),'base_groups_using':n,'required_parameters':required,'parameter_schema':d.get('parameters'),'response_schema':d.get('response'),'hepta_analogy_only':analog,'exact_mapping_supported':False,'reason':'Argument semantics, state/executor and postconditions require an explicit validated adapter; name similarity is not equivalence.' if analog else 'No identical operation in inspected six-action profile; never substitute request_evidence for executing it.'})
turn_stats={c:{'records':len(rr),'total_turn_blocks':sum(len(r['question']) for r in rr),'schema_field_sets':sorted({','.join(sorted(r)) for r in rr})} for c,rr in sets.items()}
report={'pin':manifest['pin'],'verified_files':verified,'total_bytes':sum(x['bytes'] for x in verified),'counts':turn_stats,'groups':200,'variants':600,'differences_to_base':dict(diffs),'base_group_hash_collisions':components,'distinct_path_functions':len(inventory),'base_domain_count':dict(collections.Counter(c for r in sets['base'] for c in r['involved_classes'])),'all_groups_path_config_classes_identical':all(all(g['equality_to_base'][c][k] for k in ['path','initial_config','involved_classes']) for g in groups for c in ['miss_func','miss_param']),'no_training_scoring_or_task_execution':True}
save('groups.json',groups);save('function-interface-inventory.json',inventory);save('audit-results.json',report)
print(json.dumps({k:v for k,v in report.items() if k!='verified_files'},indent=2))
