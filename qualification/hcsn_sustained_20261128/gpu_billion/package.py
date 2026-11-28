"""Build a single private Colab source under the adapter's 256 KiB limit."""
import base64
import hashlib
import io
import json
import lzma
import tarfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent
assets={n:ROOT/n for n in ("subset.xz","subset.json","run_native.py")}
assets.update({n:ROOT.parent/"billion_recovery/original/scripts"/n for n in ("encoder.py","hcsn_temporal.py")})
report={n:hashlib.sha256(path.read_bytes()).hexdigest() for n,path in assets.items()}
buffer=io.BytesIO()
with tarfile.open(fileobj=buffer,mode="w:") as t:
    for n,path in assets.items():
        data=path.read_bytes()
        info=tarfile.TarInfo(n)
        info.size=len(data);info.mtime=0
        t.addfile(info,io.BytesIO(data))
payload=base64.b85encode(lzma.compress(buffer.getvalue())).decode("ascii")
source="""import base64, hashlib, io, json, lzma, os, pathlib, sys, tarfile, tempfile
folder=pathlib.Path(tempfile.mkdtemp(prefix='physical_hcsn_'))
expected=%r
packed=%r
arch=tarfile.open(fileobj=io.BytesIO(lzma.decompress(base64.b85decode(packed))))
for member in arch:
    assert member.isfile() and member.name in expected
    data=arch.extractfile(member).read()
    assert hashlib.sha256(data).hexdigest()==expected[member.name]
    (folder/member.name).write_bytes(data)
assert set(expected)=={p.name for p in folder.iterdir()}
sys.path.insert(0,str(folder))
from run_native import run
run(folder,pathlib.Path('result.json').resolve())
"""%(report,payload)
p=ROOT/"sealed_workload.py";p.write_text(source)
if p.stat().st_size>262144:
    raise ValueError("provider source limit")
receipt=dict(component_sha256=report,source_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),size=p.stat().st_size)
(ROOT/"source_identity.json").write_text(json.dumps(receipt,indent=2)+"\n")
print(receipt["size"],receipt["source_sha256"])
