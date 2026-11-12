import base64,hashlib,json
from pathlib import Path
R=Path('/tmp')
inv=json.loads((R/'hepta-e8b-source-gate-transfer-36fa/source-inventory-e8b-original.json').read_text())
files={r['path']:{'path':r['path'],'mode':r['index_mode'],'sha':r['working_blob'],'type':'blob'} for r in inv['files']}
assert len(files)==14741 and all(r['matches_index'] and r['stable'] for r in inv['files'])
dirs={}
for path,v in files.items():
 parent,name=path.rsplit('/',1) if '/' in path else ('',path)
 dirs.setdefault(parent,{})[name]={'path':name,'mode':v['mode'],'sha':v['sha'],'type':'blob'}
 parentparts=parent.split('/') if parent else []
 for i in range(len(parentparts)):dirs.setdefault('/'.join(parentparts[:i]),{})
trees={}
for path in sorted(dirs,key=lambda s:s.count('/')+(1 if s else 0),reverse=True):
 entries=sorted(dirs[path].values(),key=lambda x:(x['path']+('/' if x['type']=='tree' else '')).encode())
 raw=b''.join((('40000' if e['type']=='tree' else e['mode'])+' '+e['path']).encode()+b'\0'+bytes.fromhex(e['sha']) for e in entries)
 sha=hashlib.sha1(b'tree '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
 trees[sha]={'sha':sha,'tree':entries,'provenance':'independently reconstructed exact e8 source inventory'}
 if path:
  parent,name=path.rsplit('/',1) if '/' in path else ('',path)
  dirs[parent][name]={'path':name,'mode':'040000','sha':sha,'type':'tree'}
 else:e8root=sha
assert e8root=='b607ff5f50812c5e0f932d7dae18d4c74f1269cb',e8root
meta=json.loads((R/'hepta-36fa-b298-canonical/metadata.json').read_text())
for t in meta['trees']:trees[t['sha']]=t
extra=R/'hepta-36fa-b298-extra-trees.json'
if extra.exists():
 for t in json.loads(extra.read_text()):trees[t['sha']]=t
unknown={};result={}
def walk(tree,path=''):
 if tree not in trees:
  unknown.setdefault(tree,[]).append(path);return
 t=trees[tree];entries=t['tree']
 raw=b''.join((('40000' if e['type']=='tree' else e['mode'])+' '+e['path']).encode()+b'\0'+bytes.fromhex(e['sha']) for e in sorted(entries,key=lambda e:(e['path']+('/' if e['type']=='tree' else '')).encode()))
 assert hashlib.sha1(b'tree '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==tree
 for e in entries:
  p=path+'/'+e['path'] if path else e['path']
  if e['type']=='tree':walk(e['sha'],p)
  else:result[p]={'path':p,'mode':e['mode'],'sha':e['sha'],'type':e['type']}
walk('906546af39b07474f0b9d046a6e780b6d3342743')
(R/'hepta-36fa-b298-unknown-trees.json').write_text(json.dumps(unknown))
if not unknown:
 (R/'hepta-36fa-b298-exact-file-map.json').write_text(json.dumps({'source':'b29869e856d08db1bfb066116a9c443376ccc57d','tree':'906546af39b07474f0b9d046a6e780b6d3342743','entries':sorted(result.values(),key=lambda x:x['path'].encode())},sort_keys=True,separators=(',',':'))+'\n')
print(json.dumps({'e8root_verified':e8root,'e8_files':len(files),'b298_resolved_files':len(result),'unknown_trees':unknown}))

