#!/usr/bin/env python3
"""Read-only pin and exact source-anchor checks. No project imports or calls."""
import hashlib
import json
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-normal-root-custody-feasibility-memo-v1')
PINS = {
 'codex-rs/hepta-agentd/src/config_circuit_task.rs': '2c2869dcfa739364ce50ab22c13cd079cedfc0e1',
 'codex-rs/hepta-agentd/src/neuron_generation_current_store.rs': '3b70b31993dfa18405848e3b99653aba6020821a',
 'codex-rs/hepta-agentd/src/config_root_credentials.rs': 'd220e122d8f0c66bc902a2691d68c5490cdb037c',
 'codex-rs/hepta-contracts/src/authority_host_store.rs': 'd087d646e0162a64caabe83a4120db820346a0a9',
}
inv = json.loads(Path('/tmp/hepta-36fa-provider-0c59-finalfmt-inventory-recovery-v1/final.inventory.exact_recovered.json').read_bytes())
by_path = {row['path']: row for row in inv['files']}
rows = []
for path, expected in PINS.items():
 raw = (ROOT / 'source' / path).read_bytes()
 got = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'git_blob': hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}
 record = by_path[path]
 assert got == {'bytes': record['bytes'], 'sha256': record['sha256'], 'git_blob': record['working_blob']}
 assert got['git_blob'] == expected
 rows.append({'path': path, **got, 'actual_f905_inventory_equal': True, 'actual_full_git_fetch_completed': True})
store = (ROOT / 'source/codex-rs/hepta-contracts/src/authority_host_store.rs').read_text()
credentials = (ROOT / 'source/codex-rs/hepta-agentd/src/config_root_credentials.rs').read_text()
assert 'rustix::process::geteuid().as_raw() != 0' in store
assert 'DirectoryAccess::Private => metadata.mode() & 0o777 == 0o700' in store
assert store.count('let _lock = self.publication_lock()?;') == 2
assert 'self.open_private(name, OFlags::RDWR | OFlags::CREATE)?' in store
assert 'libc::setresuid(expected_uid, expected_uid, expected_uid)' in credentials
assert 'libc::setresgid(expected_gid, expected_gid, expected_gid)' in credentials
assert 'libc::PR_SET_NO_NEW_PRIVS' in credentials and 'libc::PR_CAPBSET_DROP' in credentials
out = {'schema': 'hepta-root-host-feasibility-additional-input-proof-v1', 'files': rows,
       'project_code_executed': False, 'native_calls': 0, 'source_changes': 0,
       'scope': 'Four additional exact source bodies; actual source inventory is reused, not reread from native.'}
b = (json.dumps(out, indent=2, sort_keys=True)+'\n').encode()
p = ROOT / 'ADDITIONAL_INPUT_PROOF.json'
if p.exists(): assert p.read_bytes() == b
else:
 with p.open('xb') as f: f.write(b)
print(json.dumps({'files': len(rows), 'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest(), 'git_blob': hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}))
