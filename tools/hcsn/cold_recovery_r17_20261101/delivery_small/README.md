# Complete raw recovery evidence

The 19 part files are ordered byte slices of one gzip-compressed tar archive.
They retain all run01 and run02 process receipts, logs, SQLite files, suspended
snapshots and expected states. Individual parts cannot be extracted separately.
`MANIFEST.json` binds their lengths and SHA256 hashes and the reconstructed
archive. From this directory, reconstruct and verify without overwriting an
existing destination:

```sh
python - <<'PYTHON'
from pathlib import Path
import hashlib, json
manifest = json.loads(Path("MANIFEST.json").read_text())
output = Path(manifest["archive_name"])
hasher = hashlib.sha256()
size = 0
with output.open("xb") as stream:
    for part in manifest["parts"]:
        data = Path(part["path"]).read_bytes()
        assert len(data) == part["bytes"]
        assert hashlib.sha256(data).hexdigest() == part["sha256"]
        stream.write(data)
        hasher.update(data)
        size += len(data)
assert size == manifest["archive_bytes"]
assert hasher.hexdigest() == manifest["archive_sha256"]
print(output, size, hasher.hexdigest())
PYTHON
mkdir recovered-evidence
tar -xzf raw_evidence.tar.gz -C recovered-evidence
```

Then verify the retained raw artifact hashes in
`recovered-evidence/RAW_EVIDENCE_INDEX.json` against paths beneath
`recovered-evidence/`. The preserved source/protocol manifests, source snapshots,
summary JSON and independent audits remain directly readable in the parent
study directory. Restored raw data do not provide production or quality-gain
qualification beyond the scope stated in `../REPORT_ZH.md`.
