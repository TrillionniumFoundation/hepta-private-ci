# Original full accounting receipt storage

The historical `full.json` receipt is stored as two ordered byte parts of
499,992 and 330,346 bytes. Each part is within the unchanged 512,000-byte Git
blob limit. Concatenation restores the original 830,338 bytes without changing
JSON formatting, numerical values, failures, resource accounting, or claims.
The parts are byte segments and are not individually valid JSON documents.

[full.json.parts.json](full.json.parts.json) records the complete original
identity and the ordered part identities. The original SHA256 remains
`65e999fa43c100b43a0b92b481c3d39ef5575ab1640c7b4cdd09dc1d72ade9a6`.
Its Git blob is `0164135b1150a09cd0ad5aaf5caef42335d24b41` at source commit
`3a75a9675cf9a078a67d87036627ce9b002bd518`.

The existing [historical manifest](manifest.json) and its `artifacts_sha256`
entry for `full.json` retain their original bytes. Paths in that manifest,
the raw result records, and recorded commands refer to the reconstructed
original. The historical full benchmark and population audit recorded exit
code 2. Storage verification does not change those outcomes and reruns no
training, numerical qualification, or scientific evaluation.

## Restore and verify

Run this from the repository root. The destination below keeps reconstructed
data outside the checkout. To use a historical reader that requires the
original repository path, explicitly pass `.` instead. Existing output files
are never overwritten. Every part, offset, complete SHA256, Git blob identity,
and the independent historical manifest entry is verified before writing.

```sh
python3 - /tmp/hepta-hcsn-restored <<'PY'
import hashlib
import json
from pathlib import Path
import sys

root = Path("qualification/hcsn/evidence/cloud-20261105/attempt-safe")
manifest = json.loads((root / "full.json.parts.json").read_text())
data = bytearray()
for part in manifest["ordered_parts"]:
    chunk = (root / part["path"]).read_bytes()
    if part["offset"] != len(data) or len(chunk) != part["bytes"]:
        raise ValueError("Part offset or length mismatch")
    if hashlib.sha256(chunk).hexdigest() != part["sha256"]:
        raise ValueError("Part SHA256 mismatch")
    data.extend(chunk)
digest = hashlib.sha256(data).hexdigest()
if len(data) != manifest["archive_bytes"] or digest != manifest["archive_sha256"]:
    raise ValueError("Original receipt length or SHA256 mismatch")
historical = json.loads((root / "manifest.json").read_text())
if digest != historical["artifacts_sha256"]["full.json"]:
    raise ValueError("Historical receipt SHA256 mismatch")
git_blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
if git_blob != manifest["original_git_blob"]:
    raise ValueError("Original Git blob mismatch")
json.loads(data)
output = Path(sys.argv[1]) / manifest["original_repository_path"]
output.parent.mkdir(parents=True, exist_ok=True)
with output.open("xb") as stream:
    stream.write(data)
print(f"Verified and restored {output}")
PY
```

This change updates the maintained HCSN README link to the parts manifest.
Historical manifests and producer records retain their original filenames and
hashes so readers can verify the restored bytes against the original evidence.
