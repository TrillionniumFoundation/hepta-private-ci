from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import resource
import sys
import time
from zipfile import ZipFile, ZIP_DEFLATED

started=time.monotonic()
base=Path('/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training')
root=base/'final-retained-trace-labels-v1'
out=base/'final-retained-trace-labels-package-v1'
out.mkdir(exist_ok=False)
source=sys.orig_argv[sys.orig_argv.index('-c')+1]
(out/'collection-source.py').write_text(source)
files={}
for path in sorted(root.iterdir()):
    if path.is_file():
        data=path.read_bytes()
        files['originals/'+path.name]={'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'original_path':str(path)}
manifest={'schema':'original-retained-trace-labels-package-v1','files':files,'scope':'Exact original pure-JSON inspection outputs and source; no probability model or numerical kernel rerun.'}
(out/'MANIFEST.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
archive=base/'final-retained-trace-labels-20261110-v1.zip'
with ZipFile(archive,'x',ZIP_DEFLATED,compresslevel=9) as zipped:
    for name,row in files.items():zipped.write(row['original_path'],name)
    for name in ['MANIFEST.json','collection-source.py']:zipped.write(out/name,name)
with ZipFile(archive) as zipped:
    if zipped.testzip() is not None:raise ValueError('CRC failure')
    for name,row in files.items():
        data=zipped.read(name)
        if len(data)!=row['bytes'] or hashlib.sha256(data).hexdigest()!=row['sha256']:raise ValueError('member hash mismatch')
data=archive.read_bytes()
receipt={'archive':str(archive),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
         'manifest_sha256':hashlib.sha256((out/'MANIFEST.json').read_bytes()).hexdigest(),
         'all_original_members_verified':True,'original_members':len(files),
         'wall_sample_seconds':time.monotonic()-started,'CPU_sample_seconds':time.process_time(),
         'peak_RSS_sample_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
         'timing_scope':'Collection process sample before receipt serialization; separate from original JSON scan and numerical audit.',
         'energy_joules':None,'finished_utc':datetime.now(timezone.utc).isoformat()}
(out/'receipt.json').write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n')
print(json.dumps(receipt),flush=True)
