"""Return provider-side device observations even when an allocated worker is CPU-only."""
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import time
import torch

record = {'python':platform.python_version(), 'torch':str(torch.__version__),
          'cuda_build':torch.version.cuda,'hip_build':torch.version.hip,
          'cuda_available':torch.cuda.is_available(),'cuda_count':torch.cuda.device_count()}
for name in ('CUDA_VISIBLE_DEVICES','NVIDIA_VISIBLE_DEVICES'):
    record[name] = os.environ.get(name)
record['gpu_nodes_present'] = bool(list(Path('/dev').glob('nvidia[0-9]*')))
if shutil.which('nvidia-smi'):
    p=subprocess.run(['nvidia-smi','--query-gpu=name,memory.total,driver_version','--format=csv,noheader'],
                     capture_output=True, text=True,timeout=20)
    record['driver']={'exit':p.returncode,'devices':p.stdout.strip().splitlines(),'error':p.stderr[:180]}
if record['cuda_available']:
    torch.manual_seed(211)
    clock=time.monotonic()
    a=torch.randn(128,128,device='cuda')
    gram=(a@a.T).diagonal().mean()
    record['gram']=float(gram)
    torch.cuda.synchronize()
    record['compute_seconds']=time.monotonic()-clock
    record['name']=torch.cuda.get_device_name()
Path('device.json').write_text(json.dumps(record,allow_nan=False)+'\n')
print(json.dumps(record,allow_nan=False))
