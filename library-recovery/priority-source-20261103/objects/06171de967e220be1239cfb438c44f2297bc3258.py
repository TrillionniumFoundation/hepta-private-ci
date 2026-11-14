from pathlib import Path
import hashlib,json,subprocess,tomllib
r=Path(__file__).resolve().parent
subprocess.run(['python',str(r/'package_new_work.py')],cwd=r,check=True)
subprocess.run(['python',str(r/'fairness-design/test_read_only_epoch_cursor.py')],cwd=r,check=True)
m=tomllib.loads((r/'transport-candidate/codex-rs/hepta-agentd/Cargo.toml').read_text())
l=tomllib.loads((r/'transport-candidate/codex-rs/Cargo.lock').read_text())
pkg=next(x for x in l['package'] if x['name']=='codex-hepta-agentd')
for name in ['futures','tokio-tungstenite']:
 assert name in m['dev-dependencies'] and name in pkg['dependencies']
 assert sum(x['name']==name for x in l['package'])==1
print('PASS: test dependency manifests/lock edges parse and refer to existing pinned packages; no resolver/Bazel claim.')
for cmd in [['just','fmt'],['just','test','-p','codex-hepta-automation'],['just','test','-p','codex-hepta-agentd'],['just','bazel-lock-update']]:
 try:p=subprocess.run(cmd,cwd=r/'cursor-candidate/codex-rs',capture_output=True,text=True)
 except FileNotFoundError:print('UNRUN:', ' '.join(cmd),': just missing; no installation attempted')
 else:print('COMMAND RETURNED:',cmd,p.returncode,p.stdout,p.stderr)
print('Source subsets are not a full buildable checkout. No native, CI, deployment or combined-prerequisite qualification is established.')
