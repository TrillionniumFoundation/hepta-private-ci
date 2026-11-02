"""Load the exact bundled high-precision dependency; no undeclared helper path."""

import hashlib
import json
from pathlib import Path
import sys
import zipfile


root = Path(__file__).resolve().parent
manifest = json.loads((root / "dependencies/MPMATH_MANIFEST.json").read_text())
archive = root / manifest["archive"]
if hashlib.sha256(archive.read_bytes()).hexdigest() != manifest["archive_sha256"]:
    raise RuntimeError("Changed interval dependency archive")
with zipfile.ZipFile(archive) as stream:
    if set(stream.namelist()) != set(manifest["members"]):
        raise RuntimeError("Interval dependency members changed")
    for name, digest in manifest["members"].items():
        if hashlib.sha256(stream.read(name)).hexdigest() != digest:
            raise RuntimeError("Changed interval dependency member: " + name)
if "mpmath" in sys.modules and str(archive) not in str(sys.modules["mpmath"].__file__):
    raise RuntimeError("An unbound mpmath module was imported before the audit")
sys.path.insert(0, str(archive))
import mpmath

if mpmath.__version__ != "1.3.0":
    raise RuntimeError("Unexpected interval dependency version")
