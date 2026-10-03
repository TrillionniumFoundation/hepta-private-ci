"""Upload only validated screenshots, textual diagnostics and hash manifests."""

import hashlib
import json
from pathlib import Path


def stage(source, destination):
    from PIL import Image

    destination.mkdir(parents=True, exist_ok=False)
    receipt = {"included": {}, "excluded": {}}
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if path.is_symlink():
            raise ValueError("Evidence symlinks are forbidden: " + str(relative))
        if not path.is_file():
            continue
        data = path.read_bytes()
        record = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        if any(part.startswith(".") for part in relative.parts) or path.suffix not in (
            ".png", ".json", ".log", ".patch", ".rs"
        ):
            receipt["excluded"][str(relative)] = record
            continue
        if path.suffix == ".png":
            with Image.open(path) as image:
                if image.format != "PNG":
                    raise ValueError("Not a PNG screenshot: " + str(relative))
                image.verify()
        else:
            text = data.decode("utf-8")
            if "\0" in text:
                raise ValueError("Binary data in textual evidence: " + str(relative))
            if path.suffix == ".json":
                json.loads(text)
        # Preserve exact patch/helper source bytes as diagnostic logs, never executables.
        if path.suffix in (".patch", ".rs"):
            relative = relative.with_name(relative.name + ".log")
        target = destination / relative
        if target.exists():
            raise ValueError("Evidence destination collision: " + str(relative))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        receipt["included"][str(relative)] = record
    (destination / "upload-scope.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    stage(root / "robrix-evidence", root / "robrix-upload-evidence")
