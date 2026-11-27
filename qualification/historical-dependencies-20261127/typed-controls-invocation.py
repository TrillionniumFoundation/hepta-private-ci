from pathlib import Path
import tarfile,hashlib,json,subprocess,os,sys,time
root=Path('/home/qian-qi/codex-historical-dependencies-20261127-2ac5')
archive=root/'historical-helper-v5.tar.gz';assert hashlib.sha256(archive.read_bytes()).hexdigest()=="56515828655b0717a4f1d6bdd3087bff4adeaf02749ac259f5a03469ae26e74c"
source=root/'historical-helper-v5';source.mkdir()
with tarfile.open(archive) as tar:tar.extractall(source,filter='data')
argv=[sys.executable,'-B',str(source/'test_historical_dependency_admission.py'),'--receipt',str(root/'historical-a201-probe-v2-receipt.json'),'--output-dir',str(root/'historical-a201-admission-controls-v3'),'--report',str(root/'historical-a201-admission-controls-v3.json')]
start=time.time()
with (root/'historical-a201-admission-controls-v3.log').open('xb') as log:
 p=subprocess.run(argv,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),stdout=log,stderr=subprocess.STDOUT)
print((root/'historical-a201-admission-controls-v3.log').read_text(),flush=True)
print(json.dumps({'argv':argv,'returncode':p.returncode,'started':start,'finished':time.time(),'helper_sha256':"56515828655b0717a4f1d6bdd3087bff4adeaf02749ac259f5a03469ae26e74c"}),flush=True)
raise SystemExit(p.returncode)

