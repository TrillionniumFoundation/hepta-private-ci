"""Bind the test opening to both parameter seals on the independent native evidence relay."""
import hashlib,json,time
from pathlib import Path
def digest(p):
    with p.open("rb") as stream:return hashlib.file_digest(stream,"sha256").hexdigest()
def await_joint(root):
    ack=root/"joint_receipt.json"
    while not ack.is_file():time.sleep(2)
    stored=json.loads(ack.read_bytes())["sources"]
    expected={n:digest(root/n) for n in ("source/cohort.json","results/seal.json","hard-lif/seal.json")}
    if stored!=expected:raise ValueError("independent joint seal mismatch")
