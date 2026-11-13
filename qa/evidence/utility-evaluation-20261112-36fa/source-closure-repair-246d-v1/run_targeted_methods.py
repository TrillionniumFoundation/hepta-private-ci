#!/usr/bin/env python3
"""One bounded local diagnostic of four original failure methods, not qualification."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib,json,os,subprocess,sys,time

BASE=Path('/tmp/hepta-36fa-source-closure-246d-diagnosis-v1')
SOURCE=BASE/'targeted-proposal-source'
RECORDS=BASE/'targeted-diagnostic-v1'
METHODS=[
 'test_original_circuit_observer_source_closure.OriginalCircuitObserverSourceClosureTests.test_each_source_role_and_clock_constraint_remains_present_in_order',
 'test_original_selection_readback_source_closure.OriginalSelectionReadbackClosureTests.test_wire_purpose_action_sequence_and_original_context_cannot_change',
 'test_original_training_readback_source_closure.OriginalTrainingReadbackClosureTests.test_read_only_adapters_cannot_gain_execution_signing_reconnection_or_bootstrap',
 'test_resident_root_source_closure.ResidentRootSourceClosureTests.test_existing_ci_really_selects_root_cases_neuron_and_full_caller_proof',
]
def identity(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def snapshot():return [{'path':p.relative_to(SOURCE).as_posix(),**identity(p.read_bytes())} for p in sorted(SOURCE.rglob('*')) if p.is_file()]
def save(name,v):(RECORDS/name).write_text(json.dumps(v,sort_keys=True,indent=2)+'\n')
def main():
 RECORDS.mkdir(exist_ok=False)
 before=snapshot();save('INPUTS_BEFORE.json',before)
 command=[sys.executable,'-B','-m','unittest','-v',*METHODS]
 admission={'format':'hepta-local-original-four-method-diagnostic-v1','scope':'Only the four original failure methods and their original class setup. Partial exact source is sufficient for these protected-file methods, never used as a closed-world collector or full source gate.',
  'base_commit':'246d8cb614770252ee42029a5c014f2a4904176a','proposal_manifest':identity((BASE/'REPAIR_MANIFEST.json').read_bytes()),'command':command,'cwd':str(SOURCE/'qa/b4-no-bypass'),'timeout_seconds':600,'complete_source_gate':False,'native_Cargo_or_H':False,'python_version':sys.version}
 save('INPUT.json',admission)
 start=datetime.now(timezone.utc).isoformat();t=time.monotonic();timed_out=False;error=None;returncode=None
 env=dict(os.environ);env['PYTHONDONTWRITEBYTECODE']='1'
 with (RECORDS/'RAW.log').open('wb') as out:
  try:returncode=subprocess.run(command,cwd=admission['cwd'],env=env,stdout=out,stderr=subprocess.STDOUT,timeout=600,check=False).returncode
  except subprocess.TimeoutExpired:timed_out=True;error='local targeted diagnostic exceeded unchanged600-second ceiling'
  except Exception as exc:error=type(exc).__name__+': '+str(exc)
 after=snapshot();save('INPUTS_AFTER.json',after);raw=(RECORDS/'RAW.log').read_bytes()
 result={'format':'hepta-local-original-four-method-diagnostic-result-v1','started_at':start,'finished_at':datetime.now(timezone.utc).isoformat(),'elapsed_seconds':time.monotonic()-t,'returncode':returncode,'timed_out':timed_out,'error':error,'source_inputs_unchanged':before==after,'raw':identity(raw),'methods':METHODS,'status':'passed_scoped_diagnostic' if returncode==0 and not timed_out and error is None and before==after else 'failed_or_unknown_scoped_diagnostic','full_source_qualification':False,'real_task_chains':0}
 save('RESULT.json',result);print(json.dumps(result))
 return 0 if result['status']=='passed_scoped_diagnostic' else 1

if __name__=='__main__':raise SystemExit(main())
