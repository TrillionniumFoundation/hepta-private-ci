"""Verify and reassemble the exact seven retained archive byte ranges. No extraction."""
import hashlib, json
from pathlib import Path
here = Path(__file__).resolve().parent
manifest = json.loads((here / "PARTS.json").read_text())
target = here / manifest["archive"]
whole = hashlib.sha256()
offset = 0
with target.open("xb") as output:
    for index, part in enumerate(manifest["parts"], 1):
        assert part["part"] == index and part["offset"] == offset
        original = here / Path(part["path"]).name
        data = original.read_bytes()
        assert len(data) == part["bytes"]
        assert hashlib.sha256(data).hexdigest() == part["sha256"]
        output.write(data)
        whole.update(data)
        offset += len(data)
assert offset == manifest["bytes"]
assert whole.hexdigest() == manifest["sha256"]
print(json.dumps({"archive": str(target), "bytes": offset, "sha256": whole.hexdigest()}))
