"""Fetch exactly the pinned public encoder assets, or verify an existing copy."""

import argparse
import hashlib
import json
from pathlib import Path

from models import verify_base


MANIFEST_SHA256 = "28b1a3b662298722d12f5be943b21c00920f8584ea5a02eea4fc86bd4d794fa1"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    payload = Path(__file__).with_name("BASE_MODEL_IDENTITY.json").read_bytes()
    if hashlib.sha256(payload).hexdigest() != MANIFEST_SHA256:
        raise ValueError("published model identity manifest changed")
    manifest = json.loads(payload)
    if not args.verify_only:
        from huggingface_hub import snapshot_download
        if args.output.exists() and any(args.output.iterdir()):
            raise ValueError("download destination must be empty; use --verify-only for an existing model")
        args.output.mkdir(parents=True, exist_ok=True)
        snapshot_download(repo_id=manifest["repository"], revision=manifest["revision"],
                          allow_patterns=[entry["path"] for entry in manifest["files"]],
                          local_dir=str(args.output), max_workers=2)
        for entry in manifest["files"]:
            data = (args.output / entry["path"]).read_bytes()
            if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise ValueError("downloaded asset does not match the frozen experiment: " + entry["path"])
        (args.output / "MODEL_IDENTITY.json").write_bytes(payload)
    identity = verify_base(args.output, MANIFEST_SHA256)
    print(json.dumps(dict(identity=identity, bytes=sum(item["bytes"] for item in manifest["files"]),
                          files=len(manifest["files"]), revision=manifest["revision"], verified=True)))


if __name__ == "__main__":
    main()
