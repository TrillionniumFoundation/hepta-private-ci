"""Check exact test-only transformations against the archived two native builds."""
import hashlib, json, shutil, subprocess, sys, tempfile, zipfile
from pathlib import Path
evidence, checkout, observer = map(lambda p:Path(p).resolve(), sys.argv[1:4])
names = ['authority_host_publication_deployment_tests.rs','authority_host_generation_publication_root_fixture_tests.rs','authority_host_successor_deployment_files_tests.rs']
prefix=Path('codex-rs/hepta-agentd/src')
bound=json.loads((evidence/'c12-bound-inputs.json').read_bytes())
expected={}
for n in names:
    data=(checkout/prefix/n).read_bytes()
    blob=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
    assert blob==bound[str(prefix/n)][2]
    expected[n]=blob
with tempfile.TemporaryDirectory() as tmp:
    directory=Path(tmp)/prefix;directory.mkdir(parents=True)
    for n in names:shutil.copy2(checkout/prefix/n,directory/n)
    p=subprocess.run([sys.executable,str(observer/'observe.py'),tmp],capture_output=True,check=True)
    for arm in ['base','candidate']:
        with zipfile.ZipFile(evidence/f'{arm}.zip') as z:
            assert z.read('observer-hashes.txt')==p.stdout
    after={n:hashlib.sha256((directory/n).read_bytes()).hexdigest() for n in names}
print(json.dumps({'input_git_blobs':expected,'observed_bytes_sha256':after,'identical_to_both_actual_native_builds':True},indent=2,sort_keys=True))
