"""Transport exact Unix evidence through Actions' portable filename boundary.

Artifact payload names such as memory-bundle:1-... are valid native identities.
Keep those bytes/names inside a tar archive, rather than renaming evidence or
asking upload-artifact to accept an unsupported filename. Never follow symlinks.
"""

import hashlib
import json
import os
from pathlib import Path
import stat
import tarfile


ROOT = Path(__file__).resolve().parents[2]


def identity(path):
    with path.open("rb") as handle:
        sha = hashlib.file_digest(handle, "sha256").hexdigest()
    return {"bytes": path.stat().st_size, "sha256": sha}


def pack(root, preparation, output):
    output.mkdir(parents=True, exist_ok=False)
    files, special = {}, {}
    inputs = [(p, "memory-v9-ci-output/"+p.relative_to(root).as_posix()) for p in sorted(root.rglob("*"))]
    inputs.extend((p, "preparation/"+p.name) for p in sorted(preparation.glob("*PREPARATION.json")))
    archive = output / "memory-v9-evidence.tar.xz"
    with tarfile.open(archive, "w:xz", format=tarfile.PAX_FORMAT) as tar:
        for path, name in inputs:
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                continue
            if not stat.S_ISREG(mode):
                special[name] = {"mode": mode, "symlink_target": os.readlink(path) if stat.S_ISLNK(mode) else None,
                                 "contents_followed": False}
                continue
            before = identity(path)
            tar.add(path, arcname=name, recursive=False)
            after = identity(path)
            if before != after:
                raise ValueError("evidence changed during transport: "+name)
            files[name] = before
    result = {"schema": "hepta.memory.v9.portable-evidence.v1", "files": files,
              "nonregular_entries": special, "archive": {"path": archive.name, **identity(archive)},
              "original_file_names_preserved": True, "symlinks_followed": False,
              "model_or_measurement_bytes_changed": False}
    (output / "INDEX.json").write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
    receipt = root / "receipt.json"
    if receipt.is_file() and not receipt.is_symlink():
        (output / "receipt.json").write_bytes(receipt.read_bytes())
    return result


if __name__ == "__main__":
    index = pack(ROOT / "memory-v9-ci-output", Path(os.environ["RUNNER_TEMP"]) / "memory-v9-runtime",
                 ROOT / "memory-v9-evidence-transport")
    print(json.dumps({"files": len(index["files"]), "archive": index["archive"],
                      "nonregular_entries": len(index["nonregular_entries"])}))
