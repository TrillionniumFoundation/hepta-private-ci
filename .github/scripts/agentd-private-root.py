"""Run only the repository's original ignored UID0 grant-store test at verified ELF identities."""
import hashlib,json,os
from pathlib import Path
import subprocess
import time

OUT=Path(os.environ['RUNNER_TEMP'])/'private16-evidence'
CASE='authority_host_service::generation_publication::grant_store::tests::root_publication_grant_retains_actual_signature_and_reopen_never_issues'
EXPECTED={'base':'8cb021ab5ad9e6332dbe35e8cf90e9798ca344a034869bf9cbd25d403e7140b8',
          'candidate':'fc5838947364db9051e30736a79a79b1eb7bc4a90c3cc481a3179c0580b8cbd1'}
sudo=['sudo','-n']
def check(args):
    return subprocess.check_output(args,text=True).strip()
def run():
    assert len(set(EXPECTED.values()))==2
    assert check(sudo+['id','-u'])=='0'
    rows={}
    root_dir=Path(check(sudo+['mktemp','-d','/run/hepta-private16-native.XXXXXX']))
    assert root_dir.parent==Path('/run') and root_dir.name.startswith('hepta-private16-native.')
    try:
        for arm,digest in EXPECTED.items():
            binary=Path(os.environ['RUNNER_TEMP'])/('agentd-private-'+arm)
            with binary.open('rb') as stream:
                assert hashlib.file_digest(stream,'sha256').hexdigest()==digest
            trusted=root_dir/arm
            subprocess.run(sudo+['install','-o','root','-g','root','-m','0555',binary,trusted],check=True)
            assert check(sudo+['sha256sum',trusted]).split()[0]==digest
            cmd=sudo+['env','-i','PATH=/usr/bin:/bin',trusted,'--ignored','--exact',CASE,'--test-threads=1']
            start=time.monotonic()
            result=subprocess.run(cmd,cwd=Path(os.environ['RUNNER_TEMP'])/('source-private-'+arm),
                                  stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=90)
            (OUT/('uid0-'+arm+'.log')).write_text(result.stdout)
            passed=('test '+CASE+' ... ok') in result.stdout and '1 passed; 0 failed; 0 ignored;' in result.stdout
            rows[arm]={'case':CASE,'source':os.environ[arm.upper()],'sha256':digest,
                       'exit':result.returncode,'elapsed_seconds':time.monotonic()-start,
                       'actual_uid':0,'case_passed':passed}
            print(result.stdout,flush=True)
    finally:
        for arm in EXPECTED:
            subprocess.run(sudo+['rm','-f','--',root_dir/arm],check=True)
        subprocess.run(sudo+['rmdir','--',root_dir],check=True)
    (OUT/'uid0-pair.json').write_text(json.dumps(rows,indent=2)+'\n')
    print(json.dumps(rows,indent=2),flush=True)
    assert all(r['exit']==0 and r['case_passed'] for r in rows.values()),rows
if __name__=='__main__':
    run()
