# Original Learning evidence storage

Five original Learning evidence files are stored as ordered byte parts of at most 500,000 bytes, within the unchanged 512,000-byte Git blob policy. Concatenation restores the exact original bytes from `f387d7027039e3fc055fe7c201421f5364e1ab9d`. The original JSON audit, four original base64 export pieces, experiment conclusions and export manifests are unchanged after restoration.

The base64 pieces were already part of two historical exports (`initial` and `terminal`). Their original `export-manifest.json` files still refer to the restored `.base64` paths. Restore these four pieces first, then follow the unchanged export manifests to decode the original helper JSONL. The existing third base64 piece in each export remains directly available. No runtime code reads these historical evidence paths.

| Original evidence | Bytes | Ordered manifest |
| --- | ---: | --- |
| `paired-owner-convergence-20261112/validation-c7-native/initial/helpers-codex-hepta-infer-worker-host.jsonl.part-0000.base64` | 524289 | [Parts](../learn-ordinary-ce434/paired-owner-convergence-20261112/validation-c7-native/initial/helpers-codex-hepta-infer-worker-host.jsonl.part-0000.base64.parts.json) |
| `paired-owner-convergence-20261112/validation-c7-native/initial/helpers-codex-hepta-infer-worker-host.jsonl.part-0001.base64` | 524289 | [Parts](../learn-ordinary-ce434/paired-owner-convergence-20261112/validation-c7-native/initial/helpers-codex-hepta-infer-worker-host.jsonl.part-0001.base64.parts.json) |
| `paired-owner-convergence-20261112/validation-c7-native/terminal/helpers-codex-hepta-infer-worker-host.jsonl.part-0000.base64` | 524289 | [Parts](../learn-ordinary-ce434/paired-owner-convergence-20261112/validation-c7-native/terminal/helpers-codex-hepta-infer-worker-host.jsonl.part-0000.base64.parts.json) |
| `paired-owner-convergence-20261112/validation-c7-native/terminal/helpers-codex-hepta-infer-worker-host.jsonl.part-0001.base64` | 524289 | [Parts](../learn-ordinary-ce434/paired-owner-convergence-20261112/validation-c7-native/terminal/helpers-codex-hepta-infer-worker-host.jsonl.part-0001.base64.parts.json) |
| `positive-convergence-20261112/foundation-positive-merge-audit.json` | 796708 | [Parts](../learn-ordinary-ce434/positive-convergence-20261112/foundation-positive-merge-audit.json.parts.json) |

## Restore the original paths

Run from the repository root. The command checks each part's length, offset and SHA256 and the complete original SHA256 before writing. Existing outputs are never overwritten. To preserve a clean checkout, change the first line to `python3 - /tmp/hepta-learning-evidence-restored <<'PY'`; the same repository-relative paths will be restored under that destination.

```sh
python3 - <<'PY'
import hashlib
import json
from pathlib import Path
import sys

destination = Path(sys.argv[1]) if len(sys.argv) == 2 else Path.cwd()
manifests = [
    Path('qualification/learn-ordinary-ce434/paired-owner-convergence-20261112/validation-c7-native/initial/helpers-codex-hepta-infer-worker-host.jsonl.part-0000.base64.parts.json'),
    Path('qualification/learn-ordinary-ce434/paired-owner-convergence-20261112/validation-c7-native/initial/helpers-codex-hepta-infer-worker-host.jsonl.part-0001.base64.parts.json'),
    Path('qualification/learn-ordinary-ce434/paired-owner-convergence-20261112/validation-c7-native/terminal/helpers-codex-hepta-infer-worker-host.jsonl.part-0000.base64.parts.json'),
    Path('qualification/learn-ordinary-ce434/paired-owner-convergence-20261112/validation-c7-native/terminal/helpers-codex-hepta-infer-worker-host.jsonl.part-0001.base64.parts.json'),
    Path('qualification/learn-ordinary-ce434/positive-convergence-20261112/foundation-positive-merge-audit.json.parts.json'),
]
restored = []
for manifest_path in manifests:
    manifest = json.loads(manifest_path.read_text())
    data = bytearray()
    for part in manifest["ordered_parts"]:
        chunk = (manifest_path.parent / part["path"]).read_bytes()
        if part["offset"] != len(data) or len(chunk) != part["bytes"]:
            raise ValueError(f"Part length or offset mismatch: {part['path']}")
        if hashlib.sha256(chunk).hexdigest() != part["sha256"]:
            raise ValueError(f"Part checksum mismatch: {part['path']}")
        data.extend(chunk)
    if len(data) != manifest["archive_bytes"]:
        raise ValueError(f"Original length mismatch: {manifest_path}")
    if hashlib.sha256(data).hexdigest() != manifest["archive_sha256"]:
        raise ValueError(f"Original checksum mismatch: {manifest_path}")
    output = destination / manifest["original_repository_path"]
    if output.exists():
        raise FileExistsError(output)
    restored.append((output, data))
for output, data in restored:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(data)
    print(f"Verified and restored {output}")
PY
```

Each `.parts.json` also records exact no-clobber concatenation and checksum commands for restoring one original file from its recorded working directory.

## Verification

[VERIFICATION.json](VERIFICATION.json) records the original Git blobs, file hashes, part lengths and successful byte-for-byte reconstruction. The documented Python restoration was executed against a temporary destination and its no-overwrite failure was checked. Both reconstructed original base64 exports decode to 1,049,965 bytes with SHA256 `788d1d38d68040f906e396979c87f524179adf5d1274a80baf60bdbaf93ced64`; all JSONL records and the restored foundation audit parse successfully. This verification reran no experiment and creates no new qualification result.
