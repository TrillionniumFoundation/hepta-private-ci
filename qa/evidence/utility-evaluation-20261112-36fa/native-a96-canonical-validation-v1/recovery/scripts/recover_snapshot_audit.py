from pathlib import Path
import base64,gzip,hashlib,json
ROOT=Path('/tmp/hepta-36fa-a96-recovery')
def jbytes(x):return (json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def oid(t,r):return hashlib.sha1(t.encode()+b' '+str(len(r)).encode()+b'\0'+r).hexdigest()
def sha(r):return hashlib.sha256(r).hexdigest()
def thin(r):return {k:r[k] for k in ('path','mode','type','sha')}
inv=json.loads(Path('/tmp/hepta-36fa-recovered-20261112/c0f-original-source-physical-inventory.json').read_bytes())
assert len(inv['files'])==14851 and all(r['matches_index'] and r['stable'] for r in inv['files'])
cmap={r['path']:{'path':r['path'],'mode':r['index_mode'],'type':'blob','sha':r['index_blob'],'bytes':r['bytes'],'sha256':r['sha256']} for r in inv['files']}
assert len(cmap)==14851
meta={}
def addmeta(r):
    v={k:r[k] for k in ('type','sha','bytes','sha256')}
    if r['sha'] in meta:assert meta[r['sha']]==v
    meta[r['sha']]=v
for r in cmap.values():addmeta(r)
before=json.loads((ROOT/'b298-before-verified-metadata.json').read_bytes())
requests=json.loads((ROOT/'b298-before-blob-requests.json').read_bytes())
bysha={r['sha']:r for r in requests}
assert len(bysha)==32
for r in before:
    r['path']=bysha[r['sha']]['path'];assert r['bytes']==bysha[r['sha']]['bytes'] and r['mode']==bysha[r['sha']]['mode'];addmeta(r)
(ROOT/'b298-before-verified-metadata.json').write_bytes(jbytes(before))
cmp=json.loads((ROOT/'b298-c0f-compare.json').read_bytes())
assert len(cmp['files'])==41
bmap=dict(cmap)
before_by_path={r['path']:r for r in before}
for f in cmp['files']:
    p=f['filename'];assert cmap[p]['sha']==f['sha']
    if f['status']=='added':del bmap[p]
    else:
        assert f['status']=='modified';bmap[p]=dict(before_by_path[p])
assert len(bmap)==14842
trees={}
def merkle(files):
    nested={}
    for path,r in files.items():
        cur=nested
        names=path.split('/')
        for n in names[:-1]:cur=cur.setdefault(n,{})
        assert names[-1] not in cur;cur[names[-1]]=('leaf',r['mode'],r['sha'])
    used=set()
    def build(d):
        rows=[]
        for name,v in d.items():
            mode,s=('40000',build(v)) if isinstance(v,dict) else (v[1],v[2])
            rows.append((name.encode()+ (b'/' if mode=='40000' else b''),mode,name.encode(),s))
        raw=b''.join(mode.encode()+b' '+name+b'\0'+bytes.fromhex(s) for _,mode,name,s in sorted(rows))
        s=oid('tree',raw)
        if s in trees:assert trees[s]==raw
        trees[s]=raw;used.add(s);return s
    return build(nested),used
broot,btrees=merkle(bmap);croot,ctrees=merkle(cmap)
assert broot=='906546af39b07474f0b9d046a6e780b6d3342743'
assert croot=='313ee34febc8ccc54c611ab56286e289518c63cb'
packet=json.loads((ROOT/'canonical-395-packet.json').read_bytes())
provided={}
for item in packet['objects']:
    raw=base64.b64decode(item['raw_base64'],validate=True)
    assert len(raw)==item['bytes'] and sha(raw)==item['sha256'] and oid(item['type'],raw)==item['sha']
    provided[item['sha']]={**{k:item[k] for k in ('type','sha','bytes','sha256')},'raw_base64':item['raw_base64']}
    addmeta(item)
def rows(m):return [dict(m[p]) for p in sorted(m,key=lambda p:p.encode())]
maps={'base_b298':rows(bmap),'reuse_c0f':rows(cmap)}
current=dict(bmap);snapshots=[]
for record in packet['per_commit_changed_paths']:
    for d in record['changes']:
        p=d['path'];actual=thin(current[p]) if p in current else None
        assert actual==d['before'],(record['sha'],p,'before')
        if d['after'] is None:del current[p]
        else:
            m=meta[d['after']['sha']];assert m['type']=='blob'
            current[p]={**d['after'],'bytes':m['bytes'],'sha256':m['sha256']}
    root,used=merkle(current)
    assert root==record['tree'] and len(current)==record['leaf_count'] and len(used)==record['unique_tree_objects']
    maps[record['sha']]=rows(current)
    snapshots.append({'commit':record['sha'],'tree':root,'files':len(current),'unique_trees':len(used)})
assert len(maps)==9 and len(current)==15161
review=json.loads((ROOT/'native-root-review.json').read_bytes())
original=next(r for r in review['artifacts'] if r['name']=='SNAPSHOT_LEAVES.json.gz')
raw=jbytes(maps);assert len(raw)==original['raw_bytes'] and sha(raw)==original['raw_sha256'] and oid('blob',raw)==original['raw_git_blob']
gz=gzip.compress(raw,mtime=0)
gzip_exact=len(gz)==original['bytes'] and sha(gz)==original['sha256'] and oid('blob',gz)==original['git_blob']
if not gzip_exact:
    alternatives=[]
    for osbyte in (3,255):
        candidate=gz[:9]+bytes([osbyte])+gz[10:]
        if len(candidate)==original['bytes'] and sha(candidate)==original['sha256'] and oid('blob',candidate)==original['git_blob']:alternatives.append(candidate)
    if len(alternatives)==1:gz=alternatives[0];gzip_exact=True
assert gzip_exact,'raw matches original, gzip encoding does not'
assert gzip.decompress(gz)==raw
(ROOT/'SNAPSHOT_LEAVES.recovered.json').write_bytes(raw)
(ROOT/'SNAPSHOT_LEAVES.recovered.json.gz').write_bytes(gz)
(ROOT/'derived-tree-bodies.json').write_bytes(jbytes([{'sha':s,'type':'tree','bytes':len(v),'sha256':sha(v),'raw_base64':base64.b64encode(v).decode()} for s,v in sorted(trees.items())]))
(ROOT/'recovered-blob-metadata.json').write_bytes(jbytes([v for s,v in sorted(meta.items()) if v['type']=='blob']))
result={'scope':'Exact recovery of prior native output, not new execution or native read','original_native_result':'d7c135961dfacc04fe8b69697a66450e65566acb','base_tree':broot,'reuse_tree':croot,'base_files':len(bmap),'reuse_files':len(cmap),'snapshots':snapshots,'raw_bytes':len(raw),'raw_sha256':sha(raw),'raw_git_blob':oid('blob',raw),'gzip_bytes':len(gz),'gzip_sha256':sha(gz),'gzip_git_blob':oid('blob',gz),'original_raw_and_gzip_identities_matched':True,'derived_unique_trees':len(trees),'qualification':False}
(ROOT/'SNAPSHOT_RECOVERY_REVIEW.json').write_bytes(jbytes(result));print(json.dumps(result))
