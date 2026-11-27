from pathlib import Path
import hashlib,json,shutil,time
r=Path.cwd();d=Path.home()/'.local'/'share'/'hepta-research'/'hcsn-flickr8k-c511-9c415';d.mkdir(parents=True,exist_ok=True)
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def preserve(x,target,h):
 assert sha(x)==h
 target.parent.mkdir(parents=True,exist_ok=True)
 if not target.exists():
  t=target.with_name(target.name+'.supportpart');shutil.copyfile(x,t);assert sha(t)==h;t.replace(target)
 assert sha(target)==h
 return {'sha256':h,'bytes':target.stat().st_size,'file':str(target)}
m=json.loads((r/'data/manifest.json').read_text());p=json.loads((r/'panel_gpu/launch.json').read_text());support={}
for k in ['model.py','panel.py','parent_cell.py','prepare.py','qualify.py','PROTOCOL.md','SOURCE_AMENDMENT.md','quality_time.py','execute_registered.py','CANONICAL_MANIFEST.json','canonical_check.json','panel_gpu/launch.json','panel_gpu/environment.json','panel_gpu/qualification.json','data/manifest.json']:
 expected=p['source'].get(k,sha(r/k))
 support[k]=preserve(r/k,d/'replay'/k,expected)
for q in m['splits'].values():
 for k,h in q['files'].items():support['data/'+k]=preserve(r/'data'/k,d/'replay'/'data'/k,h)
s=json.loads((r/'caption_external20/seal.json').read_text())
for name,rec in s['states'].items():
 for filename,h in [('selected.pt',rec['selected']),('fit.json',rec['fit'])]:support['early20/'+name+'/'+filename]=preserve(r/'caption_external20'/name/filename,d/'early20'/name/filename,h)
support['early20/seal.json']=preserve(r/'caption_external20/seal.json',d/'early20/seal.json',sha(r/'caption_external20/seal.json'))
out={'root':str(d),'files':support,'total_bytes':sum(q['bytes'] for q in support.values()),'canonical_manifest':p['canonical_manifest'],'early_checkpoints':15}
t=d/'replay_manifest.part';t.write_text(json.dumps(out,sort_keys=True,indent=2));t.replace(d/'replay_manifest.json')
print('persisted',len(support),'inputs, sources and exact early files',out['total_bytes'],flush=True)
