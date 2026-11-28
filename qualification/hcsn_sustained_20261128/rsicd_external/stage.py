"""Reconstruct the pinned catalog layout without modifying the archived source material."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

root=Path(sys.argv[1]).resolve()
material=Path(sys.argv[2]).resolve()
stage=root/"source-catalog";stage.mkdir(exist_ok=True)
def sha(path):
    with path.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()
for name,expected in (("pixels32.npy","d79c414bb32c3ffb88f1714c20b6bdb531a68a7a95999370c86aea7367b768b1"),
                      ("rows.json","80c9f4256fef2cf37031660858dd90f07d1bb554535a0545a46e744d00f508d2")):
    original=material/"data"/name
    if sha(original)!=expected:raise ValueError(name)
    link=stage/name
    if not link.exists():link.symlink_to(original)
manifest=(root/"catalog_prepared.json").read_bytes()
oid=hashlib.sha1(b"blob "+str(len(manifest)).encode()+b"\0"+manifest).hexdigest()
if oid!="d6922e0678b0f0e55a01eeb5116ececb5cf8fe00":raise ValueError("source catalog manifest")
(stage/"prepared.json").write_bytes(manifest)
subprocess.run([sys.executable,str(root/"prepare.py"),str(stage),str(material/"raw"),str(root)],check=True)
print("recreated",json.loads((root/"data.json").read_text())["input_sha"],flush=True)
