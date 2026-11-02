"""Restore exact compressed evidence bytes from checked, ordered Git parts."""

import hashlib
import json
from pathlib import Path
import tempfile


def checked_path(root, relative):
    path = (root / relative).resolve()
    path.relative_to(root.resolve())
    return path


def verify(data, record):
    blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    if (len(data) != record["bytes"] or hashlib.sha256(data).hexdigest() != record["sha256"]
            or blob != record["git_blob"]):
        raise ValueError("Evidence content differs: " + record["path"])


def restore(root):
    manifest = json.loads((root / "publication/TRANSPORT.json").read_text())
    original = manifest["original"]
    destination = checked_path(root, original["path"])
    data = bytearray()
    for part in manifest["parts"]:
        piece = checked_path(root, part["path"]).read_bytes()
        verify(piece, part)
        data.extend(piece)
    verify(data, original)
    if destination.exists():
        verify(destination.read_bytes(), original)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        temporary.replace(destination)
    return {"restored": original["path"], "bytes": len(data), "sha256": original["sha256"]}


if __name__ == "__main__":
    print(json.dumps(restore(Path(__file__).resolve().parents[1])))
