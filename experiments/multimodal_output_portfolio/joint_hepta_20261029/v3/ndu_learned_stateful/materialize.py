"""Restore byte-identical frozen evidence from bounded lossless storage objects."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parent / "evidence/registered_v1"
MAX_BLOB_BYTES = 512000


def digest(data):
    return hashlib.sha256(data).hexdigest()


def materialize(output_dir=None):
    output = ROOT if output_dir is None else Path(output_dir)
    manifest = json.loads((ROOT / "storage_manifest.json").read_text())
    if manifest["schema"] != "ndu.lossless-evidence-storage.v1":
        raise ValueError("Unsupported storage contract")
    original = json.loads((ROOT / "manifest.json").read_text())["sha256"]
    output.mkdir(parents=True, exist_ok=True)
    restored = []
    for name, item in manifest["files"].items():
        if Path(name).name != name or name not in original or item["sha256"] != original[name]:
            raise ValueError("Logical file differs from the frozen manifest")
        chunks = []
        for part in item["parts"]:
            path = (ROOT / part["path"]).resolve()
            if not path.is_relative_to(ROOT.resolve()) or path == ROOT.resolve():
                raise ValueError("Storage object outside evidence directory")
            data = path.read_bytes()
            if len(data) != part["bytes"] or len(data) > MAX_BLOB_BYTES or digest(data) != part["sha256"]:
                raise ValueError("Storage object size/hash mismatch")
            if item["encoding"] == "gzip_parts":
                with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
                    data = stream.read(part["decoded_bytes"] + 1)
                if len(data) != part["decoded_bytes"]:
                    raise ValueError("Decoded storage object size mismatch")
            chunks.append(data)
        encoded = b"".join(chunks)
        if item["encoding"] == "gzip":
            with gzip.GzipFile(fileobj=io.BytesIO(encoded)) as stream:
                data = stream.read(item["bytes"] + 1)
        elif item["encoding"] in ("raw", "gzip_parts"):
            data = encoded
        else:
            raise ValueError("Unsupported lossless encoding")
        if len(data) != item["bytes"] or digest(data) != item["sha256"]:
            raise ValueError("Reconstructed evidence differs from frozen bytes")
        target = output / name
        if target.is_symlink():
            raise ValueError("Refusing symlink output")
        if target.exists():
            if target.stat().st_size != len(data) or target.read_bytes() != data:
                raise ValueError("Refusing to overwrite divergent evidence")
        else:
            with tempfile.NamedTemporaryFile(dir=output, prefix="ndu-restore-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
            try:
                # Exclusive creation never replaces a concurrently created file.
                with target.open("xb") as stream:
                    stream.write(temporary.read_bytes())
            finally:
                temporary.unlink()
        restored.append({"name": name, "bytes": len(data), "sha256": digest(data),
                         "storage_objects": len(item["parts"]), "encoding": item["encoding"]})
    return {"schema": "ndu.lossless-evidence-restoration.v1", "status": "matched", "files": restored,
            "scope": "Lossless representation only; no experiment, source freeze, prices or result values changed."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(materialize(args.output_dir), indent=2, sort_keys=True))
