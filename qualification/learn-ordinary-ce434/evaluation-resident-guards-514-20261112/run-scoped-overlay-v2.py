from pathlib import Path
import hashlib,json,re,shutil,sys,tomllib,unittest,time
root=Path('/workspace/scratch/ce434f960ee9/evaluation-guard-514');evidence=root.parent/'evaluation-guard-514-evidence';overlay=evidence/'validation-overlay-4ae6-v2';overlay.mkdir(exist_ok=False)
source=(root/'CALLERS.toml').read_text();dependencies=[]
for filename in ['remote-4ae6-candidate-evaluation-row.toml','remote-4ae6-candidate-readback-row.toml']:
 donor=(evidence/filename).read_text();target=tomllib.loads(donor)['protected_file'][0]['path'];count=0
 for f in re.finditer(r'^\[\[protected_file\]\].*?(?=^\[\[(?:boundary|protected_file)\]\]|\Z)',source,re.M|re.S):
  if tomllib.loads(f[0])['protected_file'][0]['path']==target:
   source=source[:f.start()]+donor+source[f.end():];count+=1;break
 assert count==1
 dependencies.append({'row':target,'row_sha256':hashlib.sha256(donor.encode()).hexdigest()})
(overlay/'CALLERS.toml').write_text(source)
for name in ['codex-rs','scripts','.github']:(overlay/name).symlink_to(root/name,target_is_directory=True)
shutil.copytree(root/'qa',overlay/'qa')
names=['test_original_evaluation_host_source_closure','test_original_evaluation_panel_source_closure','test_original_evaluation_provider_source_closure','test_original_evaluation_receipt_owner_source_closure','test_original_qualification_owner_source_closure','test_resident_root_source_closure','test_resident_candidate_stage_source_closure','test_learning_evaluation_recovery_source_closure','test_cell_learning_evaluation_source_closure'];sys.path.insert(0,str(overlay/'qa/b4-no-bypass'))
suite=unittest.defaultTestLoader.loadTestsFromNames(names);start=time.time()
with (evidence/'scoped-source-overlay-second.log').open('w') as f:r=unittest.TextTestRunner(stream=f,verbosity=2).run(suite)
raw=(evidence/'scoped-source-overlay-second.log').read_bytes();result={'base_source':'514fe5f53cfdc254477667f8862d652ea756c807','own_manifest_sha256':hashlib.sha256((root/'CALLERS.toml').read_bytes()).hexdigest(),'dependency':{'commit':'4ae6c73ea7731e69c6819c1d188f8ff26ba1fbb7','manifest_blob':'47323db6a89601a6da059b71a01a8cb874a0a05e','rows':dependencies},'overlay_manifest_sha256':hashlib.sha256(source.encode()).hexdigest(),'tests':r.testsRun,'errors':len(r.errors),'failures':len(r.failures),'successful':r.wasSuccessful(),'seconds':time.time()-start,'log_bytes':len(raw),'log_sha256':hashlib.sha256(raw).hexdigest(),'error_names':[str(t) for t,_ in r.errors],'failure_names':[str(t) for t,_ in r.failures]};(evidence/'scoped-source-overlay-second.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
