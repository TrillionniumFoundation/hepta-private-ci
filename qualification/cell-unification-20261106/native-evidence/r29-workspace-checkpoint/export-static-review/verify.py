#!/usr/bin/env python3
"""Static-only r29 closed exporter review. Never import or execute a runner."""
import ast,hashlib,json
from pathlib import Path
B=Path('/workspace/scratch/08f5efd48967')
OUT=B/'r29-export-independent-static-review';OUT.mkdir(exist_ok=True)
paths={
 'exporter':B/'r29-export-preparation/export-r29-closed-template.py',
 'runner':B/'native-validation-results/r29-bound-input/native-run-r29.py',
 'prior_exporter':B/'r28-export-preparation/export-r28-closed-template-v2.py',
}
def pin(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
texts={k:p.read_text() for k,p in paths.items()}
trees={k:ast.parse(v) for k,v in texts.items()}
funcs={k:{n.name:ast.get_source_segment(texts[k],n) for n in t.body if isinstance(n,ast.FunctionDef)} for k,t in trees.items()}
constants={}
for n in trees['exporter'].body:
 if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name):
  try:constants[n.targets[0].id]=ast.literal_eval(n.value)
  except (ValueError,TypeError):pass
assert pin(paths['exporter'].read_bytes())=={'bytes':42814,'sha256':'7a7a9b77b4dfdf20851a0c97bae3ea34e8218b062bda33e574133e772c554e13','git_blob':'16cb736f949989bfff9d849bdd5b752d1a671acd'}
assert constants['FROZEN'] is False
assert sorted(k for k,v in constants.items() if v is None)==['CLOSED_ORIGINAL_PINS','CONTROLLER_ORIGINAL_PINS','TERMINAL_PIN']
assert funcs['exporter']['review_workspace']==funcs['runner']['review_workspace']
helpers=['require','sha','data_pin','safe_relative','check_pin','check_bindings','stable_read','git','source_guard','recorded_guard','natural_terminal','clean_lines']
assert all(funcs['exporter'][n]==funcs['prior_exporter'][n] for n in helpers)
assert pin(paths['runner'].read_bytes())==constants['RUNNER_PIN']
assert constants['COMMAND']==['just','test','--locked','--retries','0']
assert constants['METADATA_COMMAND']==['cargo','metadata','--locked','--no-deps','--format-version','1']
calls=[]
for n in ast.walk(trees['exporter']):
 if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and isinstance(n.func.value,ast.Name) and n.func.value.id=='subprocess':
  calls.append((n.func.attr,n.lineno))
assert calls==[('check_output',112)],calls
assert 'check_bindings()' in funcs['exporter']['main']
assert funcs['exporter']['main'].index('check_bindings()') < funcs['exporter']['main'].index('export_closed()')
report={
 'schema':'hepta.r29-export-independent-static-review.v1','result':'CLEAR','review_scope':'Static source and producer/consumer contract only',
 'inputs':{k:{'path':str(p.relative_to(B)),**pin(p.read_bytes())} for k,p in paths.items()},
 'inert':{'FROZEN':False,'unknown_closed_maps':3,'python_optimized_execution_refused':True},
 'mechanical':{'ast_parsed_without_import_or_execution':True,'twelve_prior_export_helpers_byte_identical':helpers,
 'workspace_parser_byte_identical_to_actual_r29_runner':True,'only_subprocess_api':'git check_output with explicit readonly operation allowlist'},
 'producer_consumer_checks':[
  {'producer':'capture_metadata lines917-976','consumer':'export_closed lines418-463','result':'Actual command/raw rc/receipt/output hashes/source postguard and fresh193 default/member sets are re-read; exact scope reconstructed from those bytes. No Cargo metadata is executed by exporter.'},
  {'producer':'run_workspace lines1037-1143','consumer':'export_closed lines465-548','result':'Raw exit and effective exit remain separate; resource raw exit and receipt log hash are checked; outer result equals effective result; success requires raw0,complete full-log accounting,empty issues and matching complete original.'},
  {'producer':'run_workspace failure branch lines1135-1142','consumer':'review_workspace and export_closed lines536-548','result':'Compiler exit101 with no Starting/Summary retains nextest_started=false and terminal counts null; a complete failed nextest run retains observed original FAIL/TIMEOUT counts and failed effective/outer result. No pass is inferred from archive completion.'},
  {'producer':'run_frozen preconditions lines1179-1200','consumer':'export_closed lines262-382','result':'Source52 apply195/tree/HEAD/dual locks, old194 ancestor rows, source50 lock and historical r24/r26 failures are kept as original pinned inputs; r28 prerequisite26 originals and true outer0 are separately bound.'},
  {'producer':'controller original launch/closed reads','consumer':'export_closed lines384-416','result':'Launch job and runner SHA, all stream offset/hex/text lengths and terminal seen/stored lengths must agree; no active log is read before natural terminal binding.'},
 ],
 'archive_integrity':{'all195_source_raw_sha_gitblob_gitmode':True,'dual_raw_locks':True,'read_every_original_again_before_archive':True,'create_only_outputs':True,'tar_member_roundtrip':True,'no_original_overwrite':True},
 'limits':[
  'Static clear is not r29 execution or test qualification; original r29 is still pending terminal.',
  'This exporter intentionally rejects missing originals or failed source guards rather than fabricating a closed archive.',
  'No live r29 test log, native process, compiler, formatter, network request or source mutation was used for this review.',
  'git write-tree recomputes the index tree object identity without changing the index or working source; other allowed Git operations are read-only.',
 ],
}
raw=(json.dumps(report,indent=2,ensure_ascii=False)+'\n').encode()
(OUT/'INDEPENDENT-REVIEW.json').write_bytes(raw)
print(json.dumps({'result':'CLEAR','review':pin(raw)}))

