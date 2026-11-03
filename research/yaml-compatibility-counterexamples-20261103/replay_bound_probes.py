#!/usr/bin/env python3
"""Fresh, bounded replay with complete source/command/output binding.
All compiler invocations target only the independent research probes. Expected
compatibility failures remain failures; this script does not accept a migration.
"""
import argparse,hashlib,json,os,shutil,subprocess,time
from pathlib import Path
ap=argparse.ArgumentParser()
ap.add_argument('--replay-root',type=Path,required=True)
ap.add_argument('--dependency-dir',type=Path,required=True)
ap.add_argument('--rustc',type=Path,required=True)
ap.add_argument('--label',default='fresh-local-policy')
ap.add_argument('--patched-source',type=Path)
a=ap.parse_args()
ROOT=Path(__file__).resolve().parent
OUT=a.replay_root/'runs'/a.label;OUT.mkdir(parents=True,exist_ok=False)
DEP=a.dependency_dir
SOURCE=a.patched_source or a.replay_root/'patched/serde-saphyr-2.1.0'
inputs={};records=[]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dependency(name):
 ps=list(DEP.glob('lib'+name+'-*.rlib'));assert len(ps)==1,(name,ps)
 inputs[str(ps[0])]=sha(ps[0]);return str(ps[0])
def run(name,argv,cwd=OUT):
 start=time.monotonic();p=subprocess.run(argv,cwd=cwd,capture_output=True,timeout=60)
 (OUT/(name+'.stdout')).write_bytes(p.stdout);(OUT/(name+'.stderr')).write_bytes(p.stderr)
 rec={'name':name,'argv':argv,'cwd':str(cwd),'exit_code':p.returncode,'elapsed_seconds':time.monotonic()-start,'stdout_sha256':hashlib.sha256(p.stdout).hexdigest(),'stderr_sha256':hashlib.sha256(p.stderr).hexdigest()}
 records.append(rec);(OUT/'commands-partial.json').write_text(json.dumps(records,indent=2)+'\n')
 print(json.dumps({k:rec[k] for k in ['name','exit_code','elapsed_seconds']}),flush=True)
 if name.startswith('compile-') and p.returncode:
  print(p.stderr.decode(),flush=True);raise SystemExit(p.returncode)
 return p
common=[str(a.rustc),'--edition=2024','-C','debuginfo=0','-C','opt-level=0','-L','dependency='+str(DEP),'-L','dependency='+str(OUT)]
source={str(p):sha(p) for p in SOURCE.rglob('*.rs')}
args=common+['--crate-name','serde_saphyr','--crate-type=rlib','-C','metadata=yaml_recovered_'+a.label,'--cfg','feature="deserialize"','--cfg','feature="comments"']
for name in ['annotate_snippets','encoding_rs_io','num_traits','serde_core','smallvec','granit_parser']:args+=['--extern',name+'='+dependency(name)]
args+=[str(SOURCE/'src/lib.rs'),'-o',str(OUT/'libserde_saphyr_patched.rlib')]
run('compile-patched-library',args,SOURCE)
extra_options='''
        duplicate_keys: serde_saphyr::DuplicateKeyPolicy::PassThrough,
        leading_zero_numbers_as_strings: true,
        underscored_numbers_as_strings: true,
        ignore_binary_tag_for_string: true,
'''
summary={}
for variant in ['official','fork-default-off','fork-policy-on']:
 dst=OUT/variant;shutil.copytree(ROOT/'root-checkpoint/src',dst/'src')
 original=(dst/'src/safe_yaml.rs').read_text();needle='        strict_booleans: true,\n';assert original.count(needle)==1
 text=original.replace(needle,needle+extra_options)
 if variant=='fork-policy-on':text=text.replace(needle,needle+'        preserve_local_application_tags: true,\n')
 (dst/'src/safe_yaml.rs').write_text(text)
 for name in ['scalar_matrix.rs','narrow_examples.rs','policy_controls.rs']:
  text=(ROOT/'probe'/name).read_text()
  text=text.replace('../root-checkpoint/src/','')
  (dst/'src'/name).write_text(text)
 for p in (dst/'src').rglob('*.rs'):source[str(p)]=sha(p)
 lib=dependency('serde_saphyr') if variant=='official' else str(OUT/'libserde_saphyr_patched.rlib')
 for name,src,is_test in [('matrix','scalar_matrix.rs',False),('examples','narrow_examples.rs',False),('consumers','lib.rs',True)]+([('policy-controls','policy_controls.rs',True)] if variant=='fork-policy-on' else []):
  args=common+['--crate-name','probe_'+variant.replace('-','_')+'_'+name.replace('-','_'),'--extern','serde_saphyr='+lib]
  for n in ['serde','serde_yaml','serde_json','ryu','thiserror','pretty_assertions']:args+=['--extern',n+'='+dependency(n)]
  if is_test:args+=['--test']
  binary=dst/name;args+=[str(dst/'src'/src),'-o',str(binary)]
  run('compile-'+variant+'-'+name,args)
  p=run('run-'+variant+'-'+name,[str(binary)]+(['--nocapture'] if is_test else []))
  if not is_test:
   rows=[json.loads(x) for x in p.stdout.splitlines()]
   summary[variant+'-'+name]={'observations':len(rows),'differences':sum(not x['equal'] for x in rows),'output_sha256':hashlib.sha256(p.stdout).hexdigest()}
  else:summary[variant+'-'+name]={'exit_code':p.returncode,'output_sha256':hashlib.sha256(p.stdout).hexdigest()}
  inputs[str(binary)]=sha(binary)
o=(OUT/'run-official-matrix.stdout').read_bytes();f=(OUT/'run-fork-default-off-matrix.stdout').read_bytes()
summary['fork_default_off_byte_identical']=o==f
summary['migration_accepted']=False
summary['full_four_consumer_builds_executed']=False
summary['current_observations_are_new_replay_not_restored_old_logs']=True
(OUT/'SUMMARY.json').write_text(json.dumps(summary,indent=2)+'\n')
receipt={'schema':'bound-fresh-yaml-probe-receipt-v1','compiler':subprocess.check_output([str(a.rustc),'--version'],text=True).strip(),'compiler_sha256':sha(a.rustc),'source_sha256':source,'input_rlib_and_binary_sha256':inputs,'commands':records,'source_unchanged':all(sha(p)==h for p,h in source.items()),'shared_inputs_unchanged':all(sha(p)==h for p,h in inputs.items()),'migration_accepted':False,'production_modified':False}
assert receipt['source_unchanged'] and receipt['shared_inputs_unchanged']
(OUT/'RECEIPT.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(summary,indent=2))
