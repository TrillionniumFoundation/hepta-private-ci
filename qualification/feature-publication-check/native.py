"""Run the six existing tests by exact name against the unmodified candidate libtest."""
from pathlib import Path
from hashlib import sha256
import json, re, subprocess, sys
binary, roster, evidence = map(Path, sys.argv[1:])
binary=binary.resolve()
tests=json.loads(roster.read_text())
assert len(tests)==len(set(tests))==6
listed=subprocess.check_output([binary,'--list'],text=True)
assert all(listed.splitlines().count(name+': test')==1 for name in tests)
(evidence/'listing.txt').write_text(listed)
with binary.open('rb') as stream:
    h=sha256()
    while block:=stream.read(1024*1024):h.update(block)
run=subprocess.run([binary,'--exact','--test-threads=1',*tests],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
(evidence/'native.log').write_text(run.stdout)
actual={name:status for name,status in re.findall(r'^test (.+) \.\.\. (ok|FAILED)$',run.stdout,re.M)}
(evidence/'native.json').write_text(json.dumps({'sha256':h.hexdigest(),'exit':run.returncode,'results':actual},indent=2)+'\n')
print(run.stdout)
assert run.returncode==0 and actual==dict.fromkeys(tests,'ok') and re.search(r'^test result: ok\. 6 passed; 0 failed; 0 ignored;',run.stdout,re.M)
