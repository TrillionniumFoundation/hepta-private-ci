# Exact storage of the original architecture logs

The two original plain `.log` files are stored as deterministic gzip members.
No original whitespace or line-ending content was removed. `RAW_LOG_STORAGE.json`
records original byte count, SHA-256 and Git blob ID together with stored pins.
Each gzip was round-trip verified against its original blob. Original branch
history is retained by the ordinary merge.

Historical receipts continue to name the original `.log` paths and hashes.
Reconstruct those names into a new directory before checking a receipt; the
compressed file hash is not the original log hash. From the repository root:

```sh
python3 - <<'PY_RESTORE'
import gzip
import hashlib
import json
from pathlib import Path
root = Path('qualification/act2-continuation-20261110')
rows = json.loads((root / 'RAW_LOG_STORAGE.json').read_text())['files']
output = Path('act2-original-log-reconstruction')
output.mkdir()
for row in rows:
    packed = Path(row['stored_path']).read_bytes()
    assert len(packed) == row['stored']['bytes']
    assert hashlib.sha256(packed).hexdigest() == row['stored']['sha256']
    with gzip.open(row['stored_path'], 'rb') as stream:
        raw = stream.read(row['original']['bytes'] + 1)
    assert len(raw) == row['original']['bytes']
    assert hashlib.sha256(raw).hexdigest() == row['original']['sha256']
    target = output / row['original_path']
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as stream:
        stream.write(raw)
PY_RESTORE
```

This keeps source whitespace checks without rewriting historical evidence or
adding exclusions. All 23 incoming ZIPs remain unchanged. Their 409 members pass
CRC checks without extraction/execution; nine original macOS manifest members
and their source/command-log bindings were checked. These storage checks do not
rerun or qualify the current native behavior.
