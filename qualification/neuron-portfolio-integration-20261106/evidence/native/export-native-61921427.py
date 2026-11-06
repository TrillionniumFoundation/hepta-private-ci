import collections,datetime,hashlib,json,os,pathlib,re,shutil,subprocess,tarfile
root=pathlib.Path('/home/qq/work/hepta-portfolio-816d-20261106');source=root/'source';records=root/'records';env=os.environ.copy();env.update(json.loads((root/'env.json').read_text()))
def sh(args,cwd=source):return subprocess.check_output(args,cwd=cwd,env=env,text=True).strip()
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
identity={'head':sh(['git','rev-parse','HEAD']),'tree':sh(['git','rev-parse','HEAD^{tree}']),'status':sh(['git','status','--porcelain=v1','--untracked-files=all'])}
assert identity=={'head':'61921427dc19223fd8c9d0ded1a4723b255c5df5','tree':'31d99be67393619aca47436d82f9dca909cba359','status':''}
helper=json.loads((records/'current-helper-manifest.json').read_text());verified=[]
for name,a in helper['artifacts'].items():
 p=pathlib.Path(a['executable']);actual=digest(p);assert actual==a['sha256'];verified.append({'name':name,'path':str(p),'sha256_after_tests_and_list':actual,'bytes':p.stat().st_size})
skips=json.loads((records/'formal-61921427-test-inventory/skipped-tests.json').read_text())
rust_paths=sh(['rg','--files','hepta-agentd','hepta-neuron','hepta-intelligence','hepta-infer-worker-host','-g','*.rs'],source/'codex-rs').splitlines()
documents=[(p,(source/'codex-rs'/p).read_text()) for p in rust_paths]
source_reasons=[]
for test in skips['skipped_tests']:
 name=test['test_name'].split('::')[-1];matches=[]
 for path,text in documents:
  for m in re.finditer(r'(?m)^\s*(?:(?:pub(?:\([^)]*\))?\s+)?async\s+|pub(?:\([^)]*\))?\s+)?fn\s+'+re.escape(name)+r'\s*\(',text):
   before=text[:m.start()];context=before.splitlines()[-16:];attrs=[x.strip() for x in context if '#[ignore' in x or '#[cfg_attr' in x]
   matches.append({'source_path':'codex-rs/'+path,'line':text[:m.start()].count('\n')+1,'attribute_lines':attrs,'preceding_context':context})
 source_reasons.append({**test,'source_matches':matches})
(records/'formal-61921427-test-inventory/ignored-source-reasons.json').write_text(json.dumps({'source':identity,'ignored_count':66,'tests':source_reasons},indent=2)+'\n')
snapshot={'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source':identity,'toolchain':{},'target_path':str(root/'target'),'disk_usage':dict(zip(['total','used','free'],shutil.disk_usage(root))),'meminfo':pathlib.Path('/proc/meminfo').read_text(),'target_du_bytes':sh(['du','-sx','--block-size=1',str(root/'target')]),'helper_hashes_after_tests':verified,'cpu_time':'unknown; child rusage was not collected, no CPU value inferred from wall/resource limits','run_scope':'four named packages, default features, repository nextest local profile; 66 ignored cases not executed as top-level tests'}
for name,args in {'rustc':['rustc','-vV'],'cargo':['cargo','-V'],'just':['just','--version'],'nextest':['cargo','nextest','--version'],'uname':['uname','-a']}.items():snapshot['toolchain'][name]=sh(args)
config=records/'execution-config';config.mkdir(exist_ok=True)
for rel in ['justfile','codex-rs/.config/nextest.toml','codex-rs/rust-toolchain.toml','codex-rs/.cargo/config.toml']:
 p=source/rel
 if p.is_file():
  dst=config/rel;dst.parent.mkdir(exist_ok=True,parents=True);shutil.copy2(p,dst)
(records/'final-environment.json').write_text(json.dumps(snapshot,indent=2)+'\n')
paths=[p for p in records.rglob('*') if p.is_file()]+[root/n for n in ['env.json','env.sh','native-command.py','native-command-v2.py','pipeline-61921427.py','inventory-61921427.py','export-native-61921427.py'] if (root/n).is_file()]
assert all(not p.is_symlink() for p in paths)
inventory=[{'path':str(p.relative_to(root)),'bytes':p.stat().st_size,'sha256':digest(p)} for p in sorted(paths)]
inventory_path=root/'evidence-inventory.json';inventory_path.write_text(json.dumps({'source':identity,'files':inventory},indent=2)+'\n')
archive=root/'native-evidence-61921427.tar.gz'
with tarfile.open(archive,'w:gz',compresslevel=6) as tar:
 for p in sorted(paths)+[inventory_path]:tar.add(p,arcname=str(p.relative_to(root)),recursive=False)
print(json.dumps({'archive':str(archive),'bytes':archive.stat().st_size,'sha256':digest(archive),'file_count':len(paths)+1,'source':identity,'helper_hashes_after_tests':verified,'disk_free':shutil.disk_usage(root).free},indent=2))
