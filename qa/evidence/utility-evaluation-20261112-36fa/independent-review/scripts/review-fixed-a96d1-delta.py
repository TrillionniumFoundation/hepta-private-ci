import json,hashlib,pathlib
p=pathlib.Path('/tmp/hepta-36fa-integrated-source-prepared-v1/packet.json')
packet=json.loads(p.read_text());delta=json.loads(pathlib.Path('/tmp/hepta-36fa-fixed-a96d1-tree-delta.json').read_text())
c0f=json.loads(pathlib.Path('/tmp/hepta-36fa-final-formatted-source/expected-leaf-map.json').read_text())
base={e['path']:dict(e) for e in packet['expected_source_entries']}
for c in packet['changes']:
 if c['base_blob'] is None: del base[c['path']]
 else: base[c['path']]={'path':c['path'],'mode':c['mode'],'type':'blob','sha':c['base_blob']}
def git(kind,b):return hashlib.sha1(kind.encode()+b' '+str(len(b)).encode()+b'\0'+b).hexdigest()
def build(entries):
 root={}
 for path,e in entries.items():
  d=root
  parts=path.split('/')
  for part in parts[:-1]: d=d.setdefault(part,{})
  assert parts[-1] not in d
  d[parts[-1]]=e
 def node(d):
  items=[]
  for name,e in d.items():
   if 'sha' in e and 'mode' in e:mode=e['mode'];sha=e['sha'];isdir=False
   else:mode='40000';sha=node(e);isdir=True
   items.append((name.encode()+ (b'/' if isdir else b''),mode,name,sha))
  raw=b''.join(mode.encode()+b' '+name.encode()+b'\0'+bytes.fromhex(sha) for _,mode,name,sha in sorted(items))
  return git('tree',raw)
 return node(root)
assert build(base)==delta['base_tree'],build(base)
n={p:dict(e) for p,e in base.items()}
for d in delta['source_changes']+delta['evidence_changes']:
 path=d['path'];o=d['old'];e=d['new']
 if o is None: assert path not in n,path
 else:
  assert all(n[path][k]==o[k] for k in ['sha','mode','type']),path
 if e is None:del n[path]
 else:n[path]={k:(path if k=='path' else e[k]) for k in ['path','mode','type','sha']}
assert build(n)==delta['tip_tree'],build(n)
ours={e['path']:e for e in c0f['entries']}
assert build(ours)==c0f['tree']
conflicts=[];same=[];clean=[]
for d in delta['source_changes']:
 path=d['path'];old=base.get(path);a=ours.get(path);b=n.get(path)
 if a==b:same.append(path)
 elif a==old:clean.append(path)
 else:conflicts.append({'path':path,'base':old,'c0f':a,'a96d1':b})
report={'schema':'hepta.fixed-upstream-complete-merkle-proof.v1','base':delta['base'],'base_tree':build(base),'base_files':len(base),'tip':delta['tip'],'tip_tree':build(n),'tip_files':len(n),'source_delta':len(delta['source_changes']),'qualification_delta':len(delta['evidence_changes']),'total_delta':len(delta['source_changes'])+len(delta['evidence_changes']),'c0f_tree':build(ours),'c0f_files':len(ours),'already_identical':same,'clean_source_changes':clean,'divergent_source_changes':conflicts,'qualification_result':False,'status':'complete_fixed_tree_identity_verified_no_runtime_claim'}
pathlib.Path('/tmp/hepta-36fa-fixed-a96d1-merkle-review.json').write_text(json.dumps(report,indent=2)+'\n')
pathlib.Path('/tmp/hepta-36fa-fixed-a96d1-complete-leaf-map.json').write_text(json.dumps({'tree':build(n),'entries':[n[p] for p in sorted(n)]},separators=(',',':'))+'\n')
print(json.dumps(report))

