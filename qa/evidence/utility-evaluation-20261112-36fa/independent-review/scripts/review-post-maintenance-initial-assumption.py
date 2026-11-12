import ast,base64,difflib,gzip,hashlib,json,re,subprocess,tempfile
from pathlib import Path
R=Path('/tmp')
def load(n):return json.loads((R/n).read_text())
def sha(b):return hashlib.sha256(b).hexdigest()
def gitblob(b):return hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
p=load('hepta-36fa-prepublish-v2-terminal-review-input.json');docs={x['key']:x for x in p['items']}
for x in [p['manifest'],p['summary'],p['patch'],*p['items']]:assert gitblob(x['content'].encode())==x['sha']
manifest=json.loads(p['manifest']['content']);summary=json.loads(p['summary']['content'])
packed=base64.b64decode(docs['native_prepublish_v2_postimages_gzip_b64']['content']);assert len(packed)==10671 and gitblob(packed)=='4bbc13ffd637e45eb54b312f9246f722888a2c46'
raw=gzip.decompress(packed);assert len(raw)==35622;posts=json.loads(raw)
assert [{k:v for k,v in x.items() if k!='content_base64'} for x in posts]==manifest['postimages']
fix_gz=base64.b64decode(docs['native_prepublish_v2_fix_gzip_b64']['content']);assert len(fix_gz)==19125 and gitblob(fix_gz)=='e8b4c376f00ccbe6ec7717794769ebdff42829f5'
fixraw=gzip.decompress(fix_gz);assert fixraw==docs['native_prepublish_v2_fix_raw']['content'].encode()
fixrecord=next(x for x in summary['commands'] if x['name']=='fix');assert len(fixraw)==fixrecord['execution']['log_bytes']==115670 and sha(fixraw)==fixrecord['execution']['log_sha256']
assert fixrecord['execution']['returncode']==0 and not fixrecord['execution']['timed_out'] and not fixrecord['execution']['output_limit_exceeded']
assert not re.search(rb'^error(?:\[|:)',fixraw,re.M)
assert b'Finished \x60dev\x60 profile' in fixraw
fmt=next(x for x in summary['commands'] if x['name']=='fmt');assert fmt['execution']['returncode']==0 and fmt['execution']['log_bytes']==0 and fmt['execution']['log_sha256']==sha(b'')
prep=load('hepta-36fa-integrated-source-prepared-v1/packet.json');pm={x['path']:x for x in prep['expected_source_entries']};cm={x['path']:x for x in prep['changes']}
before=load('hepta-36fa-prepared-physical-inventory-expected.json');assert isinstance(before,list) and len(before)==14851
before_bytes=json.dumps(before,sort_keys=True,separators=(',',':')).encode();assert sha(before_bytes)==summary['source_before']['physical_inventory_sha256']
physical={x['path']:dict(x) for x in before};fmap={k:dict(v) for k,v in pm.items()};preimages={};postimages={}
fixture=load('hepta-36fa-prepublish-v2-fixture-preimage.json')
for x in posts:
 path=x['path'];b=base64.b64decode(x['content_base64']);assert len(b)==x['after']['bytes'] and sha(b)==x['after']['sha256'] and gitblob(b)==x['after']['blob']
 assert pm[path]['sha']==x['before']['sha']
 pre=base64.b64decode(cm[path]['postimage_base64']) if path in cm else fixture['content'].encode();assert gitblob(pre)==x['before']['sha']
 preimages[path]=pre;postimages[path]=b;fmap[path]['sha']=gitblob(b)
 physical[path]={'path':path,'mode':x['after']['mode'],'bytes':len(b),'sha256':sha(b),'blob':gitblob(b)}
 if 'neuron_cell_evaluation_' in path:assert re.sub(rb'\s+',b'',pre)==re.sub(rb'\s+',b'',b)
actual_after=json.dumps(sorted(physical.values(),key=lambda x:x['path'].encode()),sort_keys=True,separators=(',',':')).encode()
assert len(physical)==14851 and sha(actual_after)==summary['source_after_fmt']['physical_inventory_sha256']==summary['source_final_observation']['physical_inventory_sha256']
after_fix={x['path']:dict(x) for x in before};path=posts[0]['path'];after_fix[path]=physical[path]
fix_inventory=json.dumps(sorted(after_fix.values(),key=lambda x:x['path'].encode()),sort_keys=True,separators=(',',':')).encode();assert sha(fix_inventory)==summary['source_after_fix']['physical_inventory_sha256']
patch=p['patch']['content'].encode();assert len(patch)==manifest['diff_bytes'] and sha(patch)==manifest['diff_sha256']
with tempfile.TemporaryDirectory(prefix='hepta-36fa-v2-patchcheck-') as d:
 d=Path(d)
 for path,b in preimages.items():(d/path).parent.mkdir(parents=True,exist_ok=True);(d/path).write_bytes(b)
 pp=d/'actual.patch';pp.write_bytes(patch)
 subprocess.run(['git','apply','--check',str(pp)],cwd=d,check=True,capture_output=True)
 subprocess.run(['git','apply',str(pp)],cwd=d,check=True,capture_output=True)
 assert all((d/path).read_bytes()==b for path,b in postimages.items())
mod=ast.parse((R/'hepta-36fa-compose-final-source.py').read_text());fn=next(x for x in mod.body if isinstance(x,ast.FunctionDef) and x.name=='all_trees');exec(compile(ast.Module(body=[fn],type_ignores=[]),'<existing-reviewed-tree-reconstructor>','exec'))
trees=all_trees(fmap);assert trees['']['sha']==manifest['final_tree']==summary['final_prepublication_tree']=='faf047faf110c20115453766329bd2a66f303df7'
(R/'hepta-36fa-post-maintenance-physical-inventory-expected.json').write_bytes(actual_after)
(R/'hepta-36fa-post-maintenance-exact-file-map.json').write_text(json.dumps({'tree':trees['']['sha'],'entries':list(fmap.values())},sort_keys=True)+'\n')
(R/'hepta-36fa-post-maintenance-new-tree-objects.json').write_text(json.dumps([v for k,v in trees.items() if k in ('','codex-rs','codex-rs/hepta-agentd','codex-rs/hepta-agentd/src')],sort_keys=True)+'\n')
report={'schema':'hepta.utility.post-maintenance-root-review.v1','status':'maintenance-bytes-and-source-reviewed-before-marker-sync','source_parent':summary['source_parent'],'fixed_upstream':summary['fixed_upstream'],'prepared_tree':prep['prepared_tree'],'maintenance_tree':trees['']['sha'],'files':len(physical),'after_fix_inventory_sha256':sha(fix_inventory),'after_fmt_inventory_bytes':len(actual_after),'after_fmt_inventory_sha256':sha(actual_after),'actual_changed_paths':list(postimages),'commands':[{'name':x['name'],'command':x['command'],'execution':x['execution'],'requested_at':x['requested_at'],'finished_at':x['finished_at']} for x in summary['commands']],'raw_fix':{'bytes':len(fixraw),'sha256':sha(fixraw),'blob':gitblob(fixraw),'gzip_bytes':len(fix_gz),'gzip_sha256':sha(fix_gz),'gzip_blob':gitblob(fix_gz)},'postimages_original':{'bytes':len(raw),'sha256':sha(raw),'blob':gitblob(raw),'gzip_bytes':len(packed),'gzip_sha256':sha(packed),'gzip_blob':gitblob(packed)},'checks':['Full original fix gzip exactly decodes to independently fetched full original raw and command-record hash','All three actual postimages match their original manifest and exact prepared preimages','Actual original Git patch applies without fuzz to all three exact preimages and yields all full postimages','Both production guard changes are whitespace-only; manually reviewed exact diff preserves their original conditions and error strings','Fixture nested-if becomes equivalent short-circuit let-chain with unchanged action/error/body','Complete after-fix and after-fmt physical inventories independently reconstructed and matched','Complete final Merkle tree independently reconstructed'],'remaining_before_freeze':['Two retention guard source markers and corresponding mutation literals must follow actual formatting; ordinary prepares a narrow three-non-Rust-file synchronization','Original full source/caller/native gates still have no result on a new source commit'],'not_claimed':['new source commit','full-gate acceptance','positive retention-guard runtime coverage','real authorized ordinary utility']}
out=R/'hepta-36fa-post-maintenance-root-review.json';out.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'tree':trees['']['sha'],'files':len(physical),'inventory':sha(actual_after),'review':str(out),'fix_raw_bytes':len(fixraw),'postimages_raw_bytes':len(raw),'original_patch_checked':True}))

