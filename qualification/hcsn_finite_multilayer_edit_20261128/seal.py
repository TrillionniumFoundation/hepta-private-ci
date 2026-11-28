"""Freeze exact old-trained parents, all 108 selected active/ridge fits and inputs before opening outcomes."""
import argparse
import hashlib
import json
from pathlib import Path
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main(root,source,raw,law,fresh,out):
    if out.exists():raise FileExistsError(out)
    files={}
    for arch in ('literal','smooth'):
        for seed in (271,577,911):
            d=root/f'{arch}_{seed}'
            names=['parent.json','parent.npz','sensitivity_check.json']
            if arch=='smooth':names+=['smooth.npz']
            for arm in ('joint','receiver','bp','lora','ridge','wrong','lm_joint','lm_receiver','lbfgs'):
                names.append(arm+'.json')
                meta=json.loads((d/(arm+'.json')).read_text())['picks']
                for b in (3,15,60):
                    f=f'{arm}_{b}.npz';assert sha(d/f)==meta[str(b)]['sha256'];names.append(f)
            for n in names:files[str((d/n).relative_to(root))]=sha(d/n)
    manifest=dict(candidates=files,source={p.name:sha(p) for p in source.glob('*.py')},protocol=sha(source/'PROTOCOL.md'),extension=sha(source/'FORWARD_SENSITIVITY.md'),
                  data={p.name:sha(p) for p in raw.glob('*.npz')},old_preparation=sha(raw/'data.json'),physical_table=sha(law),
                  fresh={p.name:sha(p) for p in fresh.iterdir() if p.is_file()})
    out.write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('root','source','raw','law','fresh','out'):p.add_argument(name,type=Path)
    a=p.parse_args();main(a.root,a.source,a.raw,a.law,a.fresh,a.out)
