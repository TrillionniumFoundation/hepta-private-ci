from pathlib import Path
import subprocess, hashlib, json
root=Path('/workspace/shared/operations-authbus-integration')
source=root/'codex-rs/hepta-authbus/src/recovery_tests.rs'
base=source.read_bytes(); snippet=Path('/workspace/shared/authbus-preflight-spec/native-sequence-counterexample.rs').read_bytes()
result=None
try:
 source.write_bytes(base+snippet)
 result=subprocess.run(['just','test','--locked','-p','codex-hepta-authbus','--lib','-E','test(privileged_sequence_rewind_must_not_hide_next_frontier_event)','--failure-output','immediate'],cwd=root/'codex-rs')
finally:
 source.write_bytes(base)
 assert source.read_bytes()==base
 Path('/workspace/shared/authbus-preflight-spec/native-counterexample-manifest.json').write_text(json.dumps({'expected':'native invariant assertion fails after successful committed time update; privileged storage corruption scope','exit_code':None if result is None else result.returncode,'restored_source_sha256':hashlib.sha256(base).hexdigest(),'probe_sha256':hashlib.sha256(snippet).hexdigest()},indent=2)+'\n')
raise SystemExit(result.returncode)
