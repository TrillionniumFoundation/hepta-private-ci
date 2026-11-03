from pathlib import Path
import ast,tarfile,io,hashlib,json,tomllib
ROOT=Path('/mnt/data')
ARCHIVES=[ROOT/'NBO_20261028_source_only.tar.gz']+sorted((ROOT/'source-only-recovery-20261103').glob('*.tar.gz'))
report={'schema':'recovery.code-and-manifest.qa.v1','bundles':[],'summary':{'bundles':0,'source_members':0,'sha256_verified':0,'python_parsed':0,'json_parsed':0,'toml_parsed':0,'errors':0},'scope':'archive completeness, member SHA-256, Python AST, JSON/TOML parsing only; not execution, external dependency resolution, independent experimental replay, formal proof or CI build'}
for p in ARCHIVES:
 row={'name':p.name,'bytes':p.stat().st_size,'bundle_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'members':0,'source_files':0,'hash_verified':0,'python_ast_pass':0,'json_parse_pass':0,'toml_parse_pass':0,'issues':[]}
 with tarfile.open(p,'r:gz') as t:
  mem={m.name:m for m in t.getmembers() if m.isfile()}
  row['members']=len(mem)
  if 'SOURCE_MANIFEST.json' not in mem:row['issues'].append('SOURCE_MANIFEST.json missing');continue
  manifest=json.load(t.extractfile(mem['SOURCE_MANIFEST.json']))
  candidates=manifest.get('sources') or manifest.get('members') or manifest.get('code_and_reproduction_files') or manifest.get('items') or []
  row['source_files']=len(candidates)
  for obj in candidates:
   name=obj.get('path')
   if name not in mem:
    row['issues'].append(f'{name}: missing');continue
   raw=t.extractfile(mem[name]).read()
   if len(raw)!=obj['bytes'] or hashlib.sha256(raw).hexdigest()!=obj['sha256']:
    row['issues'].append(f'{name}: size/hash mismatch');continue
   row['hash_verified']+=1
   sfx=Path(name).suffix.lower()
   try:
    if sfx=='.py':ast.parse(raw.decode('utf8'),filename=name);row['python_ast_pass']+=1
    elif sfx=='.json':json.loads(raw);row['json_parse_pass']+=1
    elif sfx=='.toml':tomllib.loads(raw.decode('utf8'));row['toml_parse_pass']+=1
   except Exception as e:row['issues'].append(f'{name}: {type(e).__name__}: {e}')
 report['bundles'].append(row)
 report['summary']['bundles']+=1
 report['summary']['source_members']+=row['source_files']
 report['summary']['sha256_verified']+=row['hash_verified']
 report['summary']['python_parsed']+=row['python_ast_pass']
 report['summary']['json_parsed']+=row['json_parse_pass']
 report['summary']['toml_parsed']+=row['toml_parse_pass']
 report['summary']['errors']+=len(row['issues'])
out=ROOT/'source_only_bundle_validation_20261103.json'
out.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
print(json.dumps({'summary':report['summary'],'bundles':[{'name':x['name'],'sources':x['source_files'],'verified':x['hash_verified'],'py':x['python_ast_pass'],'json':x['json_parse_pass'],'issues':x['issues'][:5]} for x in report['bundles']]},ensure_ascii=False))
