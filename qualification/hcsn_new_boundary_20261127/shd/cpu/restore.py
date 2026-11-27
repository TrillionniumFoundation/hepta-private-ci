"""Verify evidence archives and restore the original relative paths with hash checks."""
import hashlib
import json
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parent
index = json.loads((root / "archives.json").read_text())
restored = set()
for archive in index["bundles"]:
    path = root / archive["file"]
    assert path.stat().st_size == archive["size"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == archive["sha256"]
    with zipfile.ZipFile(path) as handle:
        for name in handle.namelist():
            item = index["files"][name]
            assert item["archive"] == path.name and name not in restored
            target = (root / name).resolve()
            assert root in target.parents and name.split("/")[0] in {"fits", "test"}
            data = handle.read(name)
            assert len(data) == item["size"] and hashlib.sha256(data).hexdigest() == item["sha256"]
            if target.exists():
                assert target.read_bytes() == data
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            restored.add(name)
assert restored == index["files"].keys()
print(f"Verified and restored {len(restored)} files from {len(index['bundles'])} archives")
