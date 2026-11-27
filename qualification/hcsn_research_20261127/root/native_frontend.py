"""Prepare the pinned COCO frontend in a task-local venv and extract both modalities."""
from pathlib import Path
from urllib.request import Request,urlopen
import argparse,hashlib,json,os,subprocess,sys,time
def run(args,**kw):
 print('RUN',args,flush=True);subprocess.run(args,check=True,**kw)
def main():
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--ref',required=True);p.add_argument('--threads',type=int,default=4);a=p.parse_args()
 root=a.root.resolve();root.mkdir(mode=0o700,exist_ok=True);os.chdir(root)
 url='https://raw.githubusercontent.com/TrillionniumFoundation/hepta-private-ci/'+a.ref+'/qualification/hcsn_research_20261127/root/'
 for name in ['encode.py','fetch_inputs.py']:
  with urlopen(Request(url+name,headers={'User-Agent':'Hepta research frontend'}),timeout=60) as f: data=f.read()
  print(name,hashlib.sha256(data).hexdigest(),flush=True);(root/name).write_bytes(data)
 v=root/'venv';py=str(v/'bin/python')
 if not (v/'bin/pip').is_file():
  run([sys.executable,'-m','venv',str(v)])
 run([py,'-m','pip','install','--disable-pip-version-check','numpy','onnxruntime','onnx','pillow','tokenizers'])
 env={**os.environ,'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','TOKENIZERS_PARALLELISM':'false'}
 t=time.perf_counter();run([py,'-u','fetch_inputs.py'],env=env)
 print('acquisition_seconds',time.perf_counter()-t,flush=True)
 for mod,batch in [('vision',8),('text',32)]:
  run([py,'-u','encode.py',mod,'--threads',str(a.threads),'--batch',str(batch)],env=env)
 print('FRONTEND_COMPLETE',flush=True)
if __name__=='__main__':main()
