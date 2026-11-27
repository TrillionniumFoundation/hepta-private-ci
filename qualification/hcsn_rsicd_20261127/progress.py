"""Capture a recoverable optimizer/sampler state and immutable dev selections, without touching test data."""
import argparse, hashlib, io, json, lzma, os, zipfile
from pathlib import Path
import torch

def publish(run,dest):
    dest.mkdir(exist_ok=True,parents=True)
    source=run/'training.resume.pt'
    raw=source.read_bytes()
    checkpoint=torch.load(io.BytesIO(raw),weights_only=False,map_location='cpu')
    rows=checkpoint['rows'];elapsed=checkpoint['elapsed']
    thresholds=[b for b in [120,600,1800,3600,7200] if elapsed>=b]
    files={'training.resume.pt':raw,'history.json':json.dumps(rows,separators=(',',':')).encode()}
    picks={}
    for b in [*thresholds,elapsed]:
        eligible=[v for v in rows if v['state'] and v['time']<=b]
        best=max(eligible,key=lambda r:(r['dev_r1'],r['dev_r5'],-r['time']))
        data=(run/best['state']).read_bytes()
        assert hashlib.sha256(data).hexdigest()==best['hash']
        files[best['state']]=data;picks[str(b)]=best
    receipt={'seed':checkpoint['seed'],'elapsed':elapsed,'optimizer_steps':checkpoint['steps'],'locked_dev_choices':picks,'development_checks':len(rows),'training_state_sha256':hashlib.sha256(raw).hexdigest(),'dataset_hash':checkpoint['dataset'],'incomplete':elapsed<7200,'wider_panel_requires_three_seeds':True,'test_data_access_in_this_audit':False}
    (dest/'progress.json').write_text(json.dumps(receipt,indent=1));files['progress.json']=(dest/'progress.json').read_bytes()
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_STORED) as z:
        for n,v in files.items():z.writestr(zipfile.ZipInfo(n,(2026,11,27,0,0,0)),v)
    data=stream.getvalue();delivery=lzma.compress(data,preset=4)
    chunks=[]
    for j in range(0,len(delivery),360000):
        part=delivery[j:j+360000];name=f'part{j//360000:03d}.bin';(dest/name).write_bytes(part);chunks.append({'file':name,'size':len(part),'sha256':hashlib.sha256(part).hexdigest()})
    manifest={'delivery_encoding':'xz','delivery_sha256':hashlib.sha256(delivery).hexdigest(),'zip_sha256':hashlib.sha256(data).hexdigest(),'delivery_bytes':len(delivery),'zip_bytes':len(data),'chunks':chunks,'members':{n:hashlib.sha256(v).hexdigest() for n,v in files.items()}}
    (dest/'manifest.json').write_text(json.dumps(manifest,indent=1));return receipt
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('dest',type=Path);a=p.parse_args();print(json.dumps(publish(a.run,a.dest),indent=1))
