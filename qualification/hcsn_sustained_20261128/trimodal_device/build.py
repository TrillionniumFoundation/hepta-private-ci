"""Build a self-contained private offline HeptaRuntime script with pinned project inputs."""
import base64
import hashlib
import io
from pathlib import Path
import sys
import tarfile
root=Path(sys.argv[1]).resolve()
here=Path(__file__).resolve().parent
paths=["hcsn_recurrent_boundary_20261128/trimodal_decoder/"+name for name in ["data.py","train.py","network.py"]]
paths+=["hcsn_recurrent_boundary_20261128/direct_hidden/model.py","hcsn_sustained_20261128/resolvent/closed_form.py","hcsn_recurrent_boundary_20261128/returning_encoder/evidence/all.xz"]
buf=io.BytesIO()
with tarfile.open(fileobj=buf,mode="w:xz") as archive:
    for name in paths:
        b=(root/name).read_bytes()
        info=tarfile.TarInfo(name);info.size=len(b);archive.addfile(info,io.BytesIO(b))
blob=buf.getvalue()
header="""import base64, hashlib, io, os, tarfile, tempfile
from pathlib import Path
embedded=base64.b64decode(%r)
assert hashlib.sha256(embedded).hexdigest()==%r
work=Path(tempfile.mkdtemp(prefix="hcsn_trimodal_"))
with tarfile.open(fileobj=io.BytesIO(embedded),mode="r:xz") as archive:
    for item in archive:
        if not item.isfile() or '..' in Path(item.name).parts or Path(item.name).is_absolute(): raise ValueError(item.name)
        dest=work/item.name
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_bytes(archive.extractfile(item).read())
"""%(base64.b64encode(blob).decode(),hashlib.sha256(blob).hexdigest())
source=header+(here/"worker.py").read_text()+'\nrun(work,Path.cwd())\n'
dest=Path(sys.argv[2])
dest.write_text(source)
print(len(dest.read_bytes()),hashlib.sha256(dest.read_bytes()).hexdigest())
