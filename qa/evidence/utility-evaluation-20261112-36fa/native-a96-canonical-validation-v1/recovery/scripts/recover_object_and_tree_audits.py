from pathlib import Path
import base64,gzip,hashlib,json
ROOT=Path('/tmp/hepta-36fa-a96-recovery')
def jbytes(x):return (json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
def oid(t,r):return hashlib.sha1(t.encode()+b' '+str(len(r)).encode()+b'\0'+r).hexdigest()
def sha(r):return hashlib.sha256(r).hexdigest()
def meta(r):return {k:r[k] for k in ('sha','type','bytes','sha256')}
trees={r['sha']:r for r in json.loads((ROOT/'derived-tree-bodies.json').read_bytes())}
blobs={r['sha']:r for r in json.loads((ROOT/'recovered-blob-metadata.json').read_bytes())}
anchors={r['sha']:r for r in json.loads((ROOT/'recovered-anchor-commits.json').read_bytes())}
packet=json.loads((ROOT/'canonical-395-packet.json').read_bytes())
provided={r['sha']:r for r in packet['objects']}
def entries(s):
    b=base64.b64decode(trees[s]['raw_base64'],validate=True);assert oid('tree',b)==s
    off=0;out=[]
    while off<len(b):
        sp=b.index(b' ',off);nul=b.index(b'\0',sp+1);mode=b[off:sp].decode();name=b[sp+1:nul];child=b[nul+1:nul+21].hex();off=nul+21
        out.append((mode,name,child))
    assert off==len(b);return out
def reachable(root):
    ts=set();bs=set()
    def visit(s):
        if s in ts:return
        ts.add(s)
        for mode,name,child in entries(s):
            if mode=='40000':visit(child)
            else:bs.add(child)
    visit(root);return ts,bs
bt,bb=reachable('906546af39b07474f0b9d046a6e780b6d3342743')
ct,cb=reachable('313ee34febc8ccc54c611ab56286e289518c63cb')
existing={}
for s in sorted(bt|ct):existing[s]={**meta(trees[s]),'raw_git_sha_verified':True}
for s in sorted(bb|cb):existing[s]={**meta(blobs[s]),'raw_git_sha_verified':True}
for s,r in anchors.items():
    raw=base64.b64decode(r['raw_base64'],validate=True);assert oid('commit',raw)==s
    existing[s]={**meta(r),'raw_git_sha_verified':True}
assert len(existing)==16136
needed={};used=set()
for c in packet['canonical_commit_order']:
    ts,bs=reachable(c['tree']);used.add(c['sha'])
    for s,t in [(s,'tree') for s in ts]+[(s,'blob') for s in bs]:
        if s in provided:assert provided[s]['type']==t;used.add(s)
        else:assert existing[s]['type']==t;needed[s]=t
needed.update({s:'commit' for s in anchors})
required={r['sha']:r['type'] for r in packet['required_existing_objects']}
assert len(required)==16082 and required==needed and used==set(provided)
obj={'provided':[meta(provided[s]) for s in sorted(provided)],'existing':[existing[s] for s in sorted(existing)],'required_existing':[{'sha':s,'type':required[s]} for s in sorted(required)],'needed_existing':[{'sha':s,'type':needed[s]} for s in sorted(needed)]}
retained={s:trees[s]['raw_base64'] for s in bt|ct};retained.update({s:r['raw_base64'] for s,r in anchors.items()})
treeobj={'existing':[{**existing[s],'raw_base64':retained[s]} for s in sorted(retained)],'provided_tree_and_commit':[{**meta(provided[s]),'raw_base64':provided[s]['raw_base64']} for s in sorted(provided) if provided[s]['type'] in ('tree','commit')]}
original=json.loads((ROOT/'native-root-review.json').read_bytes())
records={r['name']:r for r in original['artifacts']}
results=[]
for name,value in [('OBJECT_AUDIT.json.gz',obj),('TREE_AND_ANCHOR_RAW.json.gz',treeobj)]:
    r=records[name];raw=jbytes(value)
    assert len(raw)==r['raw_bytes'] and sha(raw)==r['raw_sha256'] and oid('blob',raw)==r['raw_git_blob'],(name,'raw identity')
    g=gzip.compress(raw,mtime=0)
    candidates=[g,g[:9]+bytes([3])+g[10:],g[:9]+bytes([255])+g[10:]]
    g=next((x for x in candidates if len(x)==r['bytes'] and sha(x)==r['sha256'] and oid('blob',x)==r['git_blob']),None)
    assert g is not None and gzip.decompress(g)==raw,(name,'gzip identity')
    (ROOT/(name+'.recovered')).write_bytes(g);(ROOT/(name[:-3]+'.recovered')).write_bytes(raw)
    results.append({'name':name,'raw_bytes':len(raw),'raw_sha256':sha(raw),'raw_git_blob':oid('blob',raw),'gzip_bytes':len(g),'gzip_sha256':sha(g),'gzip_git_blob':oid('blob',g),'original_raw_and_gzip_identities_matched':True})
def fields(b):
    h,sep,m=b.partition(b'\n\n');assert sep
    lines=h.split(b'\n')
    return {'tree':[x[5:].decode() for x in lines if x.startswith(b'tree ')][0],'parents':[x[7:].decode() for x in lines if x.startswith(b'parent ')],'message_bytes':len(m),'message_ends_with_lf':m.endswith(b'\n'),'author_lines':[x.decode() for x in lines if x.startswith(b'author ')],'committer_lines':[x.decode() for x in lines if x.startswith(b'committer ')]}
canonical=[]
for c,r in zip(packet['canonical_commit_order'],packet['per_commit_changed_paths']):
    f=fields(base64.b64decode(provided[c['sha']]['raw_base64'],validate=True))
    canonical.append({'sha':c['sha'],'tree':c['tree'],'parents':c['parents'],'leaf_count':r['leaf_count'],'unique_tree_objects':r['unique_tree_objects'],'changed_paths':sorted(r['changes'],key=lambda x:x['path'].encode()),'raw_commit_fields':f})
raw=jbytes(canonical);r=records['CANONICAL_COMMITS_AND_DIFFS.json']
assert len(raw)==r['bytes'] and sha(raw)==r['sha256'] and oid('blob',raw)==r['git_blob']
(ROOT/'CANONICAL_COMMITS_AND_DIFFS.recovered.json').write_bytes(raw)
results.append({'name':'CANONICAL_COMMITS_AND_DIFFS.json','bytes':len(raw),'sha256':sha(raw),'git_blob':oid('blob',raw),'original_identity_matched':True})
report={'scope':'Exact lossless recovery of prior native audits from independently checked inputs and original serializer; no new native execution or read claimed','original_native_result':'d7c135961dfacc04fe8b69697a66450e65566acb','existing_objects':len(existing),'provided_objects':len(provided),'exact_existing_prerequisites':len(needed),'old_tree_count':len(bt|ct),'old_blob_count':len(bb|cb),'anchor_commits':len(anchors),'all_provided_reachable':True,'artifacts':results,'qualification':False}
(ROOT/'OBJECT_TREE_RECOVERY_REVIEW.json').write_bytes(jbytes(report));print(json.dumps(report))
