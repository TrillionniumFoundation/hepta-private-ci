"""Independent cached-raw setup timing; no fitting or predictive test evaluation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def main(root,core,out):
    here=Path(__file__).resolve().parent
    start=time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        d=Path(tmp)
        for n in ('household.zip','appliances.zip'):(d/n).symlink_to((root/n).resolve())
        subprocess.run([sys.executable,str(here/'prepare.py'),str(d)],check=True,stdout=subprocess.DEVNULL)
        prepared=time.monotonic()-start
        observed=json.loads((d/'split.json').read_text())['sha256']
        expected=json.loads((root/'split.json').read_text())['sha256']
        assert observed==expected
    # Spawn a genuinely new Python interpreter so cold model imports and table setup are included.
    snippet="""import sys
sys.path.insert(0,sys.argv[1])
from pathlib import Path
from models import Data,make_table
import torch
torch.set_num_threads(1)
root=Path(sys.argv[2])
train=Data(root/'train.npz')
dev=Data(root/'dev.npz')
table=make_table(Path(sys.argv[3]))
assert len(train)>0 and len(dev)>0
"""
    start=time.monotonic()
    subprocess.run([sys.executable,'-c',snippet,str(here),str(root),str(core)],check=True)
    startup=time.monotonic()-start
    out.write_text(json.dumps({'cached_raw_to_prepared_wall_s':prepared,'isolated_import_train_dev_table_wall_s':startup,'reproduced_hashes':observed,'affinity':sorted(os.sched_getaffinity(0)),'scope':'One independently timed replay on cached raw archives. Internet acquisition excluded. The two setup measurements are shared-work estimates, not the original run timestamps.'},indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('root','core','out'):p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args();main(a.root,a.core,a.out)
