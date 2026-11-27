# Original evidence archive storage

Three existing compressed evidence archives are stored as two ordered byte parts each. Every part is at most 500,000 bytes, within the unchanged 512,000-byte Git blob policy. Concatenation restores the exact original compressed bytes; the archives have not been decompressed and recompressed for storage.

| Original archive | Stored parts manifest | Original bytes |
| --- | --- | ---: |
| MEM12 `continuation-02-recovery.tar.xz` | [Ordered parts](../memory-cell-mem12-native-recovered-20261112/continuation-02-recovery.tar.xz.parts.json) | 596,784 |
| MEM14 `independent-audit-completed.tar.xz` | [Ordered parts](../memory-cell-mem14-preregistered-20261112/independent-audit-completed.tar.xz.parts.json) | 803,660 |
| MEM14 `run-original.tar.xz` | [Ordered parts](../memory-cell-mem14-preregistered-20261112/run-original.tar.xz.parts.json) | 597,704 |

Each manifest retains the original path, byte count, SHA256 and Git blob identity, plus the ordered part paths, offsets, lengths and SHA256 values. It also gives the exact concatenation and checksum commands. The original `EVIDENCE.json`, archive/member manifests and archive SHA256 values retain their historical contents. Their archive filenames refer to the restored originals. The `RESULTS.md` hashes in MEM12 `SHA256SUMS` and MEM14 `PUBLICATION_MANIFEST.json` are refreshed only for the added storage navigation. Experiment results, earlier failures and qualification decisions remain unchanged.

## Restore and verify

From the repository root, run the following command. It verifies every part, each offset and the complete original digest before writing any output. The default restores the three original repository paths. Existing files are never overwritten. Pass a destination directory to the Python invocation to restore the same relative paths outside the checkout, for example `python3 - /tmp/hepta-evidence-restored <<'PY'`.

```sh
python3 - <<'PY'
import hashlib
import json
from pathlib import Path
import sys

destination = Path(sys.argv[1]) if len(sys.argv) == 2 else Path.cwd()
manifests = [
    Path("qualification/memory-cell-mem12-native-recovered-20261112/continuation-02-recovery.tar.xz.parts.json"),
    Path("qualification/memory-cell-mem14-preregistered-20261112/independent-audit-completed.tar.xz.parts.json"),
    Path("qualification/memory-cell-mem14-preregistered-20261112/run-original.tar.xz.parts.json"),
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
        raise ValueError(f"Archive length mismatch: {manifest_path}")
    if hashlib.sha256(data).hexdigest() != manifest["archive_sha256"]:
        raise ValueError(f"Archive checksum mismatch: {manifest_path}")
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

For one archive, run its manifest's `restoration.command` and `restoration.verification_command` from the recorded `working_directory`. These commands also refuse to overwrite an existing original. After restoration, the original archive paths in the evidence reports, member manifests and `SHA256SUMS` work as recorded. Use a destination outside the checkout when preserving a clean worktree is required.

## Verification record

[VERIFICATION.json](VERIFICATION.json) binds every split archive to its original Git blob at `a5ca2bae54d0bca65e72f1920f8157f44b5a4fb8`. Concatenated parts were compared byte for byte with those blobs, the XZ integrity checks passed, and all three tar inventories were read successfully. MEM12's 65 original member hashes matched its unchanged manifest. The two MEM14 archives contain 21 and 5,598 regular files respectively. This storage verification reran no experiment or model evaluation.
