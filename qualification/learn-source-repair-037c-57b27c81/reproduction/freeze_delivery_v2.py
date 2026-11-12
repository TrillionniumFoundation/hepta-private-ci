"""Freeze the exact QA/registry repair, its negative originals and scoped result."""
from pathlib import Path
import ast,base64,datetime,difflib,gzip,hashlib,json,shutil,subprocess

R=Path(__file__).resolve().parent;C=R.parent/'candidate-source-57b-qa-repair-v1';D=R/'delivery-v2';D.mkdir(exist_ok=False)
SOURCE='57b27c81d0d5321b873ee751fd0e58e1d905b988'
PREFIX='qualification/learn-source-repair-037c-57b27c81'
Q=D/PREFIX;Q.mkdir(parents=True)
def meta(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def put(path,data):
 p=Q/path;p.parent.mkdir(parents=True,exist_ok=True);assert not p.exists();p.write_bytes(data)
def take(path,source):put(path,Path(source).read_bytes())
def js(path,x):put(path,(json.dumps(x,indent=2)+'\n').encode())
after_files={str(p.relative_to(R/'work')):p.read_bytes() for p in sorted((R/'work').rglob('*.py'))}
assert len(after_files)==17
after_files['CALLERS.toml']=(R/'registry/CALLERS.toml').read_bytes()
before_files={'CALLERS.toml':(R/'base/CALLERS.toml').read_bytes()}
for path in after_files:
 if path!='CALLERS.toml':before_files[path]=(R/'all-exact-qa'/path).read_bytes()
patch=''.join(''.join(difflib.unified_diff(before_files[p].decode().splitlines(keepends=True),after_files[p].decode().splitlines(keepends=True),fromfile='a/'+p,tofile='b/'+p)) for p in sorted(after_files))
put('REPAIR.patch',patch.encode());(D/'REPAIR.patch').write_text(patch)
replay=D/'strict-replay';replay.mkdir()
for path,b in before_files.items():p=replay/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
steps=[]
for mode in ('--check','--apply'):
 argv=['git','apply','--whitespace=error-all',mode,str(D/'REPAIR.patch')]
 p=subprocess.run(argv,cwd=replay,capture_output=True);steps.append({'argv':argv,'returncode':p.returncode,'stdout':p.stdout.decode(),'stderr':p.stderr.decode()});assert p.returncode==0 and not p.stdout and not p.stderr,steps
for path,b in after_files.items():assert (replay/path).read_bytes()==b
files=[{'path':p,'before':meta(before_files[p]),'after':meta(after_files[p])} for p in sorted(after_files)]
manifest={'source':SOURCE,'source_tree':'3db894ee96d358c583bbf4ea15163a0d2bd96258','scope':'17 exact QA migrations and three actual caller registrations; no product, verifier, authority or forbidden/duplicate-row changes.','files':files,'count':18,'registry_counts':{'boundaries':607,'protected_files':425},'registry_new_blob':meta(after_files['CALLERS.toml']),'allowlist_action_for_root':'Append only the exact new CALLERS blob/size if publishing; do not widen thresholds or patterns.','patch':meta(patch.encode()),'strict_replay':steps,'all_18_replayed_postimages_equal':True,'source_full_gate':'57b failed 38 failures + 2 errors over 482 cases; no post-repair full source run in this package.','local_affected_result':json.loads((R/'evidence/after-affected-01/result.json').read_text()),'fullcaller':'NOT_RUN_FOR_REPAIR','native':'NOT_RUN_FOR_REPAIR','ordinary_qualification':{'adopt':0,'no_update':0,'daemon_root_cold_recovery':0,'multi_generation':0}}
js('MANIFEST.json',manifest);(D/'MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
for path,b in after_files.items():
 if path=='CALLERS.toml':put('registry/CALLERS.after.toml.gz',gzip.compress(b,mtime=0))
 else:put('postimages/'+path,b)
put('registry/CALLERS.before.toml.gz',gzip.compress(before_files['CALLERS.toml'],mtime=0))
for name in ('REGISTRY_REPAIR_PROOF.json','CALLERS.patch'):take('registry/'+name,R/'registry'/name)
for name in ('TYPED_EDGE_EVIDENCE.json','OWNED_QA_MIGRATIONS.json','EXACT_QA_TREE.json','EXACT_QA_BASES.json','DEPENDENCY_PREFLIGHT.json'):
 p=R/name
 if not p.exists():p=R/'evidence'/name
 if p.exists():take('profile/'+name,p)
for name in ('MANIFEST.json','TYPED_EDGE_EVIDENCE.json','DISCOVERED_CALLER_OMISSION.json','REMOTE_BLOBS.json'):
 take('candidate/'+name,C/name)
for p in sorted((R/'evidence').rglob('*')):
 if p.is_file():take('profile/evidence/'+str(p.relative_to(R/'evidence')),p)
for attempt in ('before-01','after-01','after-02'):
 for p in sorted((C/attempt).rglob('*')):
  if p.is_file():
   path='candidate/'+attempt+'/'+str(p.relative_to(C/attempt))
   if p.name=='CALLERS.input.toml':
    b=p.read_bytes();which='before' if b==before_files['CALLERS.toml'] else 'after';assert b==(before_files if which=='before' else after_files)['CALLERS.toml']
    js(path+'.reference.json',{'original_path':str(p),'logical_original':meta(b),'same_bytes_in':'registry/CALLERS.'+which+'.toml.gz','reason':'Avoid duplicating the same large exact registry input.'})
   else:take(path,p)
for name in ('prove_added_edges.py','repair_registry.py','migrate_owned_qa.py','run_owned_suites.py','run_affected_suites.py','freeze_delivery.py','freeze_delivery_v2.py'):
 take('reproduction/'+name,R/name)
put('README.md',('''# Exact 57b source repair evidence

The published source is `'''+SOURCE+'''`. Its complete source gate naturally failed: 482 cases, 38 failures and 2 errors (442 observed passes), without timeout or inventory changes. The complete original failure log and result are preserved here.

This repair changes 17 source QA files and three exact `product_callers` lists. The two extra QA files were already passing but depend on the corrected owner-channel caller list. All 147 existing affected case names remain. The two moved attack markers now target the actual delegated read-only helper and both original Root signature-reading paths. The old unregistered-caller and mutation attacks remain.

The three registry omissions are actual calls in unchanged 57b Rust: the Trainer readback service constructs the original bounded owner channel; the Evaluator Trainer-readback factory reads its original receipt profile and consumes it through the existing host constructor. Each old row fails on that source, the exact added registration passes, and deletion or an unregistered copy is still rejected. All 607 boundaries, 425 protected rows including duplicates, forbidden lists, other fields and both original scanners remain unchanged.

The combined 17-suite run passed 147/147 in 75.2168 seconds, with all 293 physical inputs unchanged. This is a scoped local source check, not a complete repository source gate, native test, complete caller proof, ordinary launcher qualification, or deployment. The four ordinary qualification counts remain zero. Later Rust compiler diagnostics and their repair are a separate candidate, not included here.

## Packaging

The full 1.8 MB before/after registry texts are losslessly gzip-compressed with logical identities in MANIFEST and registry proof. The 17 final QA postimages and exact 18-path patch are included; all 18 strict replay outputs match their recorded bytes. Rust source copies are intentionally omitted. Actual typed/free-call evidence includes exact source path, SHA, Git blob and relevant call excerpts; fetch the unchanged source from the pinned published commit to rerun against a full tree.

Local preparation errors caused by missing overlay dependencies are retained as attempts 01/02; attempt 03 reproduced the eight-suite 13 original failures without setup errors. Candidate before/after-01 preserve the remaining original failures and the independently discovered missing registry edge. No failed original has been replaced by a passing result.
''').encode())
take('profile/PACKAGING_ATTEMPT_01.json',R/'PACKAGING_ATTEMPT_01.json')
entries=[]
for p in sorted(Q.rglob('*')):
 if p.is_file():
  b=p.read_bytes();assert len(b)<512000,(p,len(b));entries.append({'path':str(p.relative_to(Q)),**meta(b)})
js('ARTIFACTS.json',{'source':SOURCE,'files':entries,'index_excludes_itself':True,'byte_preservation':'Original physical bytes copied without newline/CRLF normalization; derived reports and gzip containers labeled by path.'})
bundle={'prefix':PREFIX,'source':SOURCE,'files':[{'path':str(p.relative_to(D)),**meta(p.read_bytes()),'content_base64':base64.b64encode(p.read_bytes()).decode()} for p in sorted(Q.rglob('*')) if p.is_file()]}
raw=json.dumps(bundle,separators=(',',':')).encode();gz=gzip.compress(raw,mtime=0);(D/'publish-bundle.json.gz').write_bytes(gz)
bm={'raw':meta(raw),'gzip':meta(gz),'file_count':len(bundle['files']),'largest':max(x['bytes'] for x in bundle['files']),'prefix':PREFIX}
(D/'BUNDLE_META.json').write_text(json.dumps(bm,indent=2)+'\n');print(json.dumps(bm,indent=2))
