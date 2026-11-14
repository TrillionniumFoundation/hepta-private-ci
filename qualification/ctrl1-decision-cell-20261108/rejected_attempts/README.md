# Rejected attempt originals

These archives preserve the first `primary` and `cpu_allowance` attempts exactly as retained. Their classification is **integrity-rejected**. They are excluded from accepted numerical results and do not add independent seeds. The underlying cause is unknown. Missing content has not been reconstructed, and retained temporary files are included as ordinary evidence bytes.

`INDEX.json` records every original file path, byte length and SHA-256, together with each complete gzip archive's identity and its ordered parts. No part exceeds 393,216 bytes. Archive members contain only directories and regular files; links and special files are rejected. The archives were verified by concatenating the stored parts and comparing every archived file with the current original.

## Restore into a new directory

Verify the package or `INDEX.json` identity against the separately retained delivery manifest first. Hashes establish content consistency, not independent execution attestation.

The following Python 3 command verifies every part, the concatenated archive, and every member before creating a new destination. It writes files manually instead of calling unrestricted tar extraction. Replace the first argument with this archive directory, choose `primary` or `cpu_allowance`, and use a destination that does not exist. Restored paths include the attempt's own top-level directory.

```bash
python3 - /absolute/path/to/rejected_attempts primary /absolute/path/to/new-destination <<'PY'
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import sys
import tarfile

package = Path(sys.argv[1]).resolve(strict=True)
attempt = sys.argv[2]
destination = Path(sys.argv[3]).resolve()
index = json.loads((package / "INDEX.json").read_bytes())
entry = next(item for item in index["archives"] if item["attempt"] == attempt)

def require(condition, message):
    if not condition:
        raise ValueError(message)

def checked(data, record):
    require(len(data) == record["bytes"], "Byte length mismatch")
    require(hashlib.sha256(data).hexdigest() == record["sha256"], "SHA-256 mismatch")
    return data

chunks = []
for part in entry["archive"]["parts"]:
    name = part["path"]
    require(Path(name).name == name and name not in (".", ".."), "Unsafe part name")
    require(not (package / name).is_symlink(), "Part must not be a symlink")
    chunks.append(checked((package / name).read_bytes(), part))
compressed = checked(b"".join(chunks), entry["archive"])
expected = {item["path"]: item for item in entry["files"]}
directories, contents, seen = set(), {}, set()
with tarfile.open(fileobj=io.BytesIO(compressed), mode="r:gz") as archive:
    for member in archive:
        path = PurePosixPath(member.name)
        require(not path.is_absolute() and ".." not in path.parts
                and str(path) == member.name and path.parts[0] == attempt, "Unsafe member path")
        require(member.name not in seen, "Duplicate member")
        seen.add(member.name)
        if member.isdir():
            directories.add(member.name)
        else:
            require(member.isfile() and member.name in expected, "Unexpected file or link")
            record = expected[member.name]
            require(member.size == record["bytes"], "Member size mismatch")
            with archive.extractfile(member) as stream:
                contents[member.name] = checked(stream.read(record["bytes"] + 1), record)
require(set(contents) == set(expected), "Missing original file")
require(directories == set(entry["directories"]), "Directory inventory mismatch")
destination.mkdir(parents=False, exist_ok=False)
for name in sorted(directories, key=lambda name: (len(PurePosixPath(name).parts), name)):
    (destination / name).mkdir(exist_ok=True)
for name, data in contents.items():
    with (destination / name).open("xb") as stream:
        stream.write(data)
print(json.dumps({"restored_attempt": attempt, "regular_files": len(contents),
                  "destination": str(destination), "classification": "integrity-rejected"}))
PY
```

This procedure restores the directory tree and exact regular-file contents. The tar archives also retain the original mode and modification-time metadata. Restoring a rejected attempt does not change its qualification status.
