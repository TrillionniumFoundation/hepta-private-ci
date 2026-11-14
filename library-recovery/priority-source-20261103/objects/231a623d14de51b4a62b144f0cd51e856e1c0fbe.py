import hashlib,json,pathlib,re,shutil,sqlite3,subprocess
root=pathlib.Path(__file__).resolve().parent
records=json.loads((root/'sources.json').read_text())+json.loads((root/'doc-sources.json').read_text())
for r in records:
 actual=subprocess.check_output(['git','hash-object',str(root/'base'/r['path'])],text=True).strip()
 assert actual==r['sha'],r
print('PASS: eleven baseline files match exact GitHub blob IDs at dfac7171.')
check=root/'apply-check'
if check.exists():shutil.rmtree(check)
shutil.copytree(root/'base',check)
for name in ['taskflow-timeout-isolation.patch','taskflow-sibling-claim-barrier.patch','taskflow-docs-reconstructed.patch']:
 patch=root/name
 subprocess.run(['git','apply','--check','--whitespace=error',str(patch)],cwd=check,check=True)
 subprocess.run(['git','apply','--whitespace=error',str(patch)],cwd=check,check=True)
 subprocess.run(['git','apply','--reverse','--check','--whitespace=error',str(patch)],cwd=root/'candidate',check=True)
 print('PASS: forward apply, reverse apply and whitespace:',name)
for f in (root/'candidate').rglob('*'):
 if f.is_file():assert (check/f.relative_to(root/'candidate')).read_bytes()==f.read_bytes(),f
print('PASS: applying all three patches reproduces every candidate byte.')
s=(root/'candidate/codex-rs/hepta-automation/src/taskflow_guard.rs').read_text()
q=re.search(r'"(SELECT EXISTS \(.*?)",\n',s,re.S).group(1)
c=sqlite3.connect(':memory:')
c.execute('create table taskflow_step_outbox(owner_agent_id text,run_id text,step_id text,attempt integer,event_seq integer,event_kind text,observation text)')
def add(a,seq,k,obs=None,step='s',run='r',owner='o'):
 c.execute('insert into taskflow_step_outbox values(?,?,?,?,?,?,?)',(owner,run,step,a,seq,k,obs))
def blocked(exclude=None,step='s',run='r',owner='o'):
 return c.execute(q,(owner,run,step,step,exclude,exclude)).fetchone()[0]
add(1,1,'prepared');add(2,1,'prepared');assert not blocked()
add(1,2,'claimed');assert blocked();assert not blocked(1);assert blocked(2)
add(2,2,'claimed');assert blocked(1) and blocked(2)
add(1,3,'recorded','indeterminate');assert blocked(2)
add(1,4,'reconciled');assert not blocked(2)
assert not blocked(None,'other');assert not blocked(run='other');assert not blocked(owner='other')
print('PASS: exact production SQL: prepared/claimed/indeterminate/terminal, self exclusion, distinct step/run/owner.')
step=(root/'candidate/codex-rs/hepta-automation/src/taskflow_step.rs').read_text()
claim=step[step.index('        match operation {'):]
assert 'reject_unresolved_steps(' in claim[:claim.index('            "record" =>')]
ledger=(root/'candidate/codex-rs/hepta-automation/src/effect_dispatch_ledger.rs').read_text()
fn=ledger[ledger.index('    pub(crate) async fn begin_effect_dispatch_attempt('):]
assert fn.index('BEGIN IMMEDIATE')<fn.index('reject_unresolved_steps(')<fn.index('let started_at_ms = admitted_at()?')<fn.index('INSERT INTO taskflow_effect_dispatch_attempts')
print('PASS: guard ordering assertions at actual claim/final admission source.')
for command in [['just','fmt'],['just','test','-p','codex-hepta-automation'],['just','test','-p','codex-hepta-agentd']]:
 try:r=subprocess.run(command,cwd=root/'candidate/codex-rs',capture_output=True,text=True)
 except FileNotFoundError: print('UNRUN:', ' '.join(command),': just not installed; no installation attempted')
 else:print('EXECUTED:',command,'exit',r.returncode,r.stdout,r.stderr)
print('NOTE: SQL/source/apply checks do not establish Rust compilation, native behavioral pass, formatting, or CI acceptance.')
