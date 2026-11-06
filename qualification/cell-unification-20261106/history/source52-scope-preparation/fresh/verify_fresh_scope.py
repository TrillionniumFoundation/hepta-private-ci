#!/usr/bin/env python3
"""Offline source52 package/formatter scope preparation from fresh r29 Cargo metadata."""
import ast,copy,gzip,hashlib,json,re,tomllib
from pathlib import Path
B=Path('/workspace/scratch/08f5efd48967');O=B/'source52-final-scope-preparation';O.mkdir(exist_ok=True)
D=B/'native-validation-results/r29-fixed-metadata';E=B/'native-validation-results/r29-start-closed/evidence'
OLD=B/'source51-final-scope-readonly'
C='1e0910becc37383e6d17ecf861ea844fd07d8862';T='211f15baff19095e8c98bcea2b0ed99ca2270ade';H='bef6fa7645df9df12b69fda499e97eed25de6c75'
def pin(d):return {'bytes':len(d),'sha256':hashlib.sha256(d).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(d)).encode()+b'\0'+d).hexdigest()}
def load(p):return json.loads(p.read_bytes())
def enc(o):return (json.dumps(o,ensure_ascii=False,indent=2)+'\n').encode()
def put(rel,data):
 p=O/rel;p.parent.mkdir(parents=True,exist_ok=True)
 if p.exists():assert p.read_bytes()==data,str(p)
 else:p.write_bytes(data)
 return {'path':rel,**pin(data)}
mb=(D/'native-workspace-r29-metadata.json').read_bytes();sb=(D/'native-workspace-r29-scope.json').read_bytes()
assert pin(mb)['sha256']=='b29d6b0c49c63d6345f50597873e3fa98c79ea0cbfe923ae3dd700b5cc08af8d'
assert pin(sb)['sha256']=='f54377c0848cd407033bfe812cb020130f4c630c05f2fa40eb408bf8d03a6f88'
m=json.loads(mb);scope=json.loads(sb);receipt=load(E/'native-workspace-r29-metadata-receipt.json');raw=load(E/'native-workspace-r29-metadata-raw-process-result.json');post=load(E/'native-workspace-r29-metadata-source-post-verification.json')
assert receipt['exit_code']==raw['exit_code']==0
assert post['pass'] and post['actual_tree']==post['expected_tree']==T and post['native_head']==H and post['changed_file_count']==195
assert post['unstaged_paths']==post['untracked_paths']==post['file_mismatches']==[]
assert scope['metadata_generated_on_current_source'] and scope['old_metadata_reused_as_current'] is False
assert scope['source_commit']==C and scope['source_tree']==T and scope['command']==['just','test','--locked','--retries','0']
assert scope['metadata']=={'path':'native-workspace-r29-metadata.json',**pin(mb)}
assert len(m['workspace_members'])==len(m['workspace_default_members'])==len(m['packages'])==193
assert set(m['workspace_members'])==set(m['workspace_default_members'])
native_root=Path(m['workspace_root']).parent
members={p['id']:p for p in m['packages']};assert set(members)==set(m['workspace_members'])
source_path=B/'native-validation-results/source52-apply-closed/evidence/native-candidate-r28-source.json'
source=load(source_path);rows={x['path']:x for x in source['changed_files']}
assert source['source_commit']==C and source['source_tree']==T and len(rows)==195
rust=sorted(x for x in rows if x.endswith('.rs'));assert len(rust)==181
manifest_dirs=[]
for package in m['packages']:
 rel=Path(package['manifest_path']).relative_to(native_root).as_posix()
 assert rel.startswith('codex-rs/') and rel.endswith('/Cargo.toml')
 manifest_dirs.append((rel.rsplit('/',1)[0],rel,package))
byowner={}
file_commands=[]
for path in rust:
 candidates=[x for x in manifest_dirs if path.startswith(x[0]+'/')]
 assert candidates,path
 directory,manifest,package=max(candidates,key=lambda x:len(x[0]))
 assert package['id'] in m['workspace_default_members'] and package['edition']=='2024'
 rec=byowner.setdefault(package['name'],{'package':package['name'],'package_id':package['id'],'package_directory':directory,'manifest_path':manifest,'edition':package['edition'],'default_workspace_member':True,'rust_paths':[]})
 rec['rust_paths'].append(path)
 file_commands.append({'path':path,'owning_package':package['name'],'manifest_path':manifest,'cwd':str(native_root/directory),'command':['rustfmt','--edition',package['edition'],'--config','imports_granularity=Item,skip_children=true','--',str(native_root/path)]})
assert len(byowner)==26
oldargs=load(OLD/'PROPOSED-FIX-PACKAGES.json');assert sorted(byowner)==oldargs['owners']
owners=[]
for k,v in sorted(byowner.items()):v['rust_path_count']=len(v['rust_paths']);owners.append(v)
workflow=(OLD/'input/hepta-cell-framework-native.yml').read_bytes()
assert pin(workflow)['sha256']==rows['.github/workflows/hepta-cell-framework-native.yml']['sha256']
selectors=re.findall(r'(?<!\S)-p\s+([A-Za-z0-9_-]+)',workflow.decode())
# Matrix package strings are the only -p arguments in this workflow.
assert len(selectors)==len(set(selectors))==27
assert set(selectors)==set(byowner)|{'codex-hepta-control-plane'}
paths=sorted(rows)
python=sorted('./'+p for p in paths if p.startswith(('scripts/','.github/')) and p.endswith(('.py','.pyi')))
assert python==['./scripts/run-nextest.py','./scripts/test_run_nextest_helpers.py']
config=[p for p in paths if Path(p).name in {'rustfmt.toml','.rustfmt.toml','pyproject.toml','ruff.toml','.ruff.toml'}]
assert config==[] and 'justfile' not in paths
assert not any(Path(p).name in {'BUILD','WORKSPACE','MODULE.bazel'} or p.endswith(('.bzl','.sky','.BUILD.bazel','.MODULE.bazel')) for p in paths)
format_bytes=(OLD/'original/scripts/format.py').read_bytes();format_ast=ast.parse(format_bytes)
definitions={n.name:ast.get_source_segment(format_bytes.decode(),n) for n in format_ast.body if isinstance(n,ast.FunctionDef)}
assert 'revision = "HEAD"' in definitions['changed_paths']
assert '"--no-renames"' in definitions['changed_paths'] and '"--diff-filter=ACDMRT"' in definitions['changed_paths']
assert 'imports_granularity=Item,skip_children=true' in definitions['rust_file_command']
assert 'args.all' in definitions['main'] and 'changed_paths(args.base)' in definitions['main']
assert 'python_scripts_formatter_group' in definitions['scoped_formatter_groups']
# Existing immutable owner manifests resolve the same editions as actual metadata.
cargo_pins=[]
for owner in owners:
 p=OLD/'original'/owner['manifest_path'];cargo=tomllib.loads(p.read_text());assert cargo['package']['name']==owner['package']
 edition=cargo['package'].get('edition')
 if isinstance(edition,dict):assert edition=={'workspace':True};edition=tomllib.loads((OLD/'original/codex-rs/Cargo.toml').read_text())['workspace']['package']['edition']
 assert str(edition)==owner['edition']
 cargo_pins.append({'path':owner['manifest_path'],**pin(p.read_bytes())})
inputs={}
inputs['source_manifest']=put('input/native-candidate-r28-source.json',source_path.read_bytes())
meta_gz=gzip.compress(mb,compresslevel=9,mtime=0);assert gzip.decompress(meta_gz)==mb
inputs['fresh_metadata_gzip']=put('input/native-workspace-r29-metadata.json.gz',meta_gz)
inputs['fresh_metadata_gzip']['original_uncompressed']=pin(mb)
inputs['fresh_scope']=put('input/native-workspace-r29-scope.json',sb)
for name in ['native-workspace-r29-metadata-receipt.json','native-workspace-r29-metadata-raw-process-result.json','native-workspace-r29-metadata-source-post-verification.json','native-workspace-r29-metadata-stderr.log']:
 inputs[name]=put('input/'+name,(E/name).read_bytes())
inputs['original_format']=put('input/format.py',format_bytes)
inputs['original_justfile']=put('input/justfile',(OLD/'original/justfile').read_bytes())
inputs['workflow']=put('input/hepta-cell-framework-native.yml',workflow)
inputs['metadata_transfer_readback']=put('input/TRANSFER-READBACK.json',(D/'INDEPENDENT-READBACK.json').read_bytes())
args=[v for name in sorted(byowner) for v in ('-p',name)]
package_args={'schema':'hepta.source52-final-fix-packages.v1','status':'NOT_EXECUTED_PENDING_SAME_SOURCE_R29_PASS',
 'source_commit':C,'source_tree':T,'source_manifest':inputs['source_manifest'],'fresh_metadata':{'bytes':len(mb),'sha256':pin(mb)['sha256'],'git_blob':pin(mb)['git_blob']},
 'owners':sorted(byowner),'package_args':args,'command':['just','fix','--locked',*args],
 'recipe_expansion':['cargo','clippy','--fix','--tests','--allow-dirty','--locked',*args],'cwd':str(native_root/'codex-rs'),
 'fix_executed':False,'same_source_workspace_pass_bound':False}
a=put('PACKAGE-ARGS.json',enc(package_args))
selection={'schema':'hepta.source52-final-formatter-selection.v1','status':'NOT_EXECUTED_PREPARATION_ONLY',
 'source_commit':C,'source_tree':T,'native_HEAD':H,'native_created_commit_checkout_claimed':False,
 'source_manifest':inputs['source_manifest'],'changed_path_count':195,'changed_paths':paths,
 'rust_count':181,'rust_paths':rust,'python_count':2,'python_paths':python,'formatting_configuration_changed_paths':[],
 'owner_count':26,'owners':owners,'ci_selector_count':27,'ci_selectors':selectors,'extra_ci_only_owner':['codex-hepta-control-plane'],
 'workspace_members':193,'workspace_default_members':193,'fresh_source52_r29_metadata_verified':True,
 'default_formatter_command':['just','fmt'],'all_flag_used':False,
 'python_formatter_command':['uv','run','--frozen','--project','scripts','ruff','format',*python],
 'unselected_by_default_formatter':[p for p in paths if p not in rust and './'+p not in python],
 'final_scope_execution_authorized':False,'post_fix_selection_must_be_revalidated_before_fmt':True,
 'unexpected_scope_or_dependency_change_requires_stop_without_reset_or_test_rerun':True}
e=put('EXPECTED-SELECTION.json',enc(selection));fc=put('RUST-FILE-COMMANDS.json',enc(file_commands))
report={'schema':'hepta.source52-fresh-final-scope-readback.v1','result':'READ_ONLY_SCOPE_CLEAR_NOT_EXECUTION_AUTHORIZATION',
 'source_commit':C,'source_tree':T,'source_counts':{'changed':195,'rust':181,'other':14,'owners':26,'ci_selectors':27},
 'fresh_actual_r29_metadata':inputs['fresh_metadata_gzip'],'actual_default_workspace':{'members':193,'defaults':193,'equal':True},
 'inputs':inputs,'original_owner_cargo_pins':cargo_pins,'package_args':a,'expected_selection':e,'rust_file_commands':fc,
 'static_formatter_derivation':'Original default HEAD changed-path algorithm; no formatting config changes,181 Rust files and2 scripts Python files. Edition2024 matches actual package metadata and original manifests; skip_children=true retained.',
 'native_HEAD_not_changed':True,'source_not_modified':True,'cargo_not_run_by_reviewer':True,'fix_executed':False,'fmt_executed':False,
 'workspace_result':None,'required_before_any_execution':'Same-source r29 natural raw/effective/outer0,complete full results and source/dual-lock guards; exact actual tool pins and post-fix scope revalidation.',
 'tools':'No formatter/Cargo/just/Rust commands executed by this audit.'}
put('READ-ONLY-AUDIT.json',enc(report))
files=[{'path':str(p.relative_to(O)),**pin(p.read_bytes())} for p in sorted(O.rglob('*')) if p.is_file() and p.name!='HANDOFF-MANIFEST.json']
put('HANDOFF-MANIFEST.json',enc({'schema':'hepta.source52-final-scope-handoff.v1','status':'FROZEN_NOT_EXECUTED','source_commit':C,'source_tree':T,'files':files,'new_binary_paths':[inputs['fresh_metadata_gzip']],'old_source51_materials_unchanged':True}))
print(json.dumps({'audit':pin((O/'READ-ONLY-AUDIT.json').read_bytes()),'package_args':a,'selection':e,'handoff':pin((O/'HANDOFF-MANIFEST.json').read_bytes()),'files':len(files)}))

