"""Restore only the nine hash-pinned original inputs; do not load models or roles."""
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tarfile
import time


def restore(source_root, assets):
    started, cpu=time.perf_counter(),time.process_time()
    source=Path(source_root)/'experiments/multimodal_output_portfolio/field_bridge_v3_20261027/assets.py'
    constants={}
    for node in ast.parse(source.read_bytes()).body:
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
            if node.targets[0].id in ('ORIGINAL_ARCHIVE','PINNED'):
                constants[node.targets[0].id]=ast.literal_eval(node.value)
    assets=Path(assets).resolve()
    archive=assets/'ndu_v6_full002_evidence.tar.gz'
    with archive.open('rb') as stream:
        actual=hashlib.file_digest(stream,'sha256').hexdigest()
    assert actual==constants['ORIGINAL_ARCHIVE']
    assert len(constants['PINNED'])==9
    restored=[]
    with tarfile.open(archive,'r:gz') as tar:
        for name,expected in constants['PINNED'].items():
            member=tar.getmember(name)
            assert member.isfile()
            data=tar.extractfile(member).read()
            assert hashlib.sha256(data).hexdigest()==expected
            target=assets/name
            assert not target.exists()
            target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as stream:
                stream.write(data)
            assert hashlib.sha256(target.read_bytes()).hexdigest()==expected
            restored.append({'path':name,'bytes':len(data),'sha256':expected})
    receipt={'schema':'hepta.fullstudy.original-asset-restoration.1',
        'at_utc':datetime.now(timezone.utc).isoformat(),'archive_sha256':actual,
        'archive_bytes':archive.stat().st_size,'selected_files':restored,
        'all_pinned_bytes_verified':True,'model_tensors_loaded':False,
        'source_roles_decoded':False,'endpoint_scoring_performed':False,
        'wall_seconds':time.perf_counter()-started,'own_cpu_seconds':time.process_time()-cpu}
    path=assets/'RESTORATION.json'
    with path.open('x') as stream:
        json.dump(receipt,stream,indent=2,sort_keys=True)
        stream.write('\n')
    print(json.dumps({'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'restored_files':len(restored),'bytes':sum(r['bytes'] for r in restored)}))


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--source-root',required=True)
    parser.add_argument('--assets',required=True)
    args=parser.parse_args()
    restore(args.source_root,args.assets)
