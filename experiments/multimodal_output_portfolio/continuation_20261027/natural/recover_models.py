"""Recover or verify the two precisely pinned external Whisper weight files."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def recover(workspace, metadata, verify_only=False):
    root = workspace.resolve()
    records = json.loads(metadata.read_text())["models"]
    result = []
    for row in records:
        relative = Path(row["relative_path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe recovery path")
        target = root/relative
        if not target.resolve().is_relative_to(root):
            raise ValueError("Recovery path escapes workspace through a symlink")
        parsed = urllib.parse.urlparse(row["url"])
        if parsed.scheme != "https" or parsed.hostname != "huggingface.co" or "/resolve/" not in parsed.path:
            raise ValueError("Only pinned official model repository URLs are accepted")
        if not target.exists():
            if verify_only:
                raise FileNotFoundError(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_name(target.name+".recovery-incomplete")
            observed = 0
            with urllib.request.urlopen(row["url"], timeout=60) as response, partial.open("xb") as stream:
                while block := response.read(1024*1024):
                    observed += len(block)
                    if observed > row["bytes"]:
                        raise ValueError("Model exceeds its pinned byte count; partial retained")
                    stream.write(block)
            if observed != row["bytes"] or sha(partial) != row["sha256"]:
                raise ValueError("Recovered model failed pinned size/hash verification; partial retained")
            os.link(partial, target)
            partial.unlink()
        if target.stat().st_size != row["bytes"] or sha(target) != row["sha256"]:
            raise ValueError("Existing model differs from the pin; no overwrite performed")
        result.append({"path": str(target), "bytes": row["bytes"], "sha256": row["sha256"], "verified": True})
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, default=Path(__file__).parent/"evidence/MODEL_RECOVERY.json")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    print(json.dumps(recover(args.workspace, args.metadata, args.verify_only), indent=2))
