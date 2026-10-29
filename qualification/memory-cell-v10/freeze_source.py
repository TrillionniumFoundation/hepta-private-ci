"""Create or verify a bounded source manifest before remote freezing and fits."""

import argparse
import json
from pathlib import Path

from export_native import canonical, sha


def identities():
    root = Path(__file__).resolve().parent
    files = {path.name: sha(path.read_bytes()) for path in sorted(root.iterdir())
             if path.is_file() and path.name != "SOURCE_MANIFEST.json" and path.suffix in (".py", ".json", ".md", ".txt")}
    for name in ("encoder.py", "tensor_cell.py"):
        files["../memory-cell-adapters/" + name] = sha((root.parent / "memory-cell-adapters" / name).read_bytes())
    return files


def verify(path):
    manifest = json.loads(Path(path).read_text())
    if manifest["schema"] != "hepta.memory.v10.source-freeze.v1" or manifest["files"] != identities():
        raise ValueError("source tree differs from the frozen manifest")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    path = Path(__file__).with_name("SOURCE_MANIFEST.json")
    if args.write:
        if path.exists():
            raise ValueError("freeze manifest already exists; explicitly archive invalidated freezes before a new one")
        path.write_bytes(canonical({"schema": "hepta.memory.v10.source-freeze.v1", "files": identities(),
                                   "baseline_commit": "0f41c4968eea63727c69e2b979491e94a99a9dbb",
                                   "formal_fit_started": False, "remote_commit_is_bound_by_run_receipt": True}))
    verify(path)
    print(json.dumps({"manifest_sha256": sha(path.read_bytes()), "files": len(identities())}))


if __name__ == "__main__":
    main()
