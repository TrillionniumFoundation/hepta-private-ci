"""Evaluate the frozen original camera from sealed media after binding the separate acoustic decision file."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
from zipfile import ZipFile
import numpy as np
import torch
from qualification.hcsn_intervention_value.media import vision

HERE=Path(__file__).resolve().parent
def sha(path):
    with path.open('rb') as f:
        h=sha256()
        for block in iter(lambda:f.read(1<<20),b''):h.update(block)
    return h.hexdigest()
def read(path):return json.loads(path.read_text())
def save(path,x):path.write_text(json.dumps(x,indent=2,sort_keys=True)+'\n')
def run(args):
    first=time.perf_counter(); out=args.out
    seal=read(out/'action-seal.json')
    assert sha(out/'action-seal.json')==args.action_seal and sha(HERE/'protocol.json')==seal['protocol_sha256']
    assert all(sha(out/name)==hash_ for name,hash_ in seal['files'].items())
    cohort=read(HERE/'cohort.json');assert sha(HERE/'cohort.json')==seal['cohort_sha256']
    src={str(r['pageid']):r for r in cohort['sources']}
    assert sha(args.weights)==read(HERE/'protocol.json')['frozen_sha256']['camera']
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    model,transform,idx=vision.load_model(args.weights)
    rows=read(out/'roster.json'); folder=out/'camera-rows';folder.mkdir(exist_ok=True)
    all_records=[]; probs=[]
    with TemporaryDirectory(dir=args.scratch) as tmp:
        root=Path(tmp); repo=Path(sys.modules[vision.__name__].__file__).resolve().parents[3]
        with ZipFile(repo/'qualification/hcsn_blocker_followup/media/source_replay.zip') as archive:
            for name in ('rgb_disk.py','vision_disk.py'):
                (root/name).write_bytes(archive.read('pinned/'+name))
        sys.path.insert(0,str(root))
        import rgb_disk,vision_disk
        with torch.inference_mode():
            for row in rows:
                record=src[row['recording']]; name=str(record['pageid'])+Path(record['title']).suffix
                path=next(a/name for a in args.originals if (a/name).is_file())
                row=dict(row,local_media=str(path.resolve()));original_sha=sha(path)
                assert original_sha==record['source_sha256']
                destination=folder/(row['query_id']+'.json')
                if destination.exists():
                    observation=read(destination)
                    assert observation['source_sha256']==original_sha and observation['action_seal']==args.action_seal
                else:
                    started=time.perf_counter()
                    rgb_disk.one(row)
                    z,details=vision_disk.tensors(row,transform)
                    decoded=time.perf_counter()
                    logits=model(z);prob=vision.cumulative_class_probability(logits,idx)
                    observation={'query_id':row['query_id'],'source_sha256':original_sha,'action_seal':args.action_seal,
                       'rgb_sha256':details['rgb_sha256'],'transform_sha256':vision_disk.th(z),'logits_sha256':vision_disk.th(logits),
                       'posterior':prob.numpy().tolist(),'clock':details['details'],
                       'decode_transform_wall_seconds':decoded-started,'inference_wall_seconds':time.perf_counter()-decoded}
                    save(destination,observation)
                    (root/'rgb-cache'/row['split']/(row['query_id']+'.rgb')).unlink()
                probs.append(observation['posterior']);all_records.append(observation)
    assert len(all_records)==48
    np.savez_compressed(out/'camera.npz',query_id=np.asarray([row['query_id'] for row in rows]),probability=np.asarray(probs))
    save(out/'camera-receipt.json',{'action_seal':args.action_seal,'script':sha(Path(__file__)),'original_vision':sha(Path(vision.__file__)),
        'weights':sha(args.weights),'wall_seconds':time.perf_counter()-first,'torch':torch.__version__,'torchvision':vision.torchvision.__version__,
        'output_sha256':sha(out/'camera.npz'),'rows':all_records})
if __name__=='__main__':
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--weights',type=Path,required=True);cli.add_argument('--out',type=Path,required=True)
    cli.add_argument('--scratch',type=Path,required=True);cli.add_argument('--action-seal',required=True)
    cli.add_argument('--originals',type=Path,nargs='+',required=True);run(cli.parse_args())
