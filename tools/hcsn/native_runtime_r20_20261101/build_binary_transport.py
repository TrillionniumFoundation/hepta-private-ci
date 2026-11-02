"""Delivery-only byte preservation of every actually executed runtime ELF."""
import gzip
import hashlib
import io
import json
from pathlib import Path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    component = Path(__file__).resolve().parent
    candidates = {Path("/tmp/hcsn-r20-runtime-frozen-d0ac"), Path("/tmp/hcsn-r20-runtime-engineering"),
                  Path("/tmp/hcsn-r20-runtime-engineering-financial"), Path("/tmp/hcsn-r20-runtime-identity-engineering")}
    for record in component.glob("*/PROCESS_RECORDS.json"):
        for row in json.loads(record.read_text()):
            candidates.add(Path(row["command"][0]))
    objects = {}
    missing = []
    for path in sorted(candidates):
        if not path.is_file():
            missing.append(str(path)); continue
        data = path.read_bytes()
        if not data.startswith(b"\x7fELF"):
            continue
        sha = digest(data)
        item = objects.setdefault(sha, dict(data=data, origin_paths=[], evidence_aliases=[]))
        item["origin_paths"].append(str(path))
        if path.is_relative_to(component):
            item["evidence_aliases"].append(path.relative_to(component).as_posix())
    rows = []
    for sha, item in sorted(objects.items()):
        buffer = io.BytesIO()
        with gzip.GzipFile(fileobj=buffer, filename="", mode="wb", mtime=0, compresslevel=9) as output:
            output.write(item["data"])
        compressed = buffer.getvalue()
        folder = component / "binary_transport" / sha
        folder.mkdir(parents=True, exist_ok=True)
        parts = []
        for index, start in enumerate(range(0, len(compressed), 450000)):
            data = compressed[start:start+450000]
            path = folder / f"{index:04}.part"
            if path.exists() and path.read_bytes() != data:
                raise ValueError("existing different binary part")
            path.write_bytes(data)
            parts.append(dict(path=path.relative_to(component).as_posix(), bytes=len(data), sha256=digest(data)))
        rows.append(dict(sha256=sha, bytes=len(item["data"]), gzip_bytes=len(compressed), gzip_sha256=digest(compressed),
                         parts=parts, origin_paths=item["origin_paths"], evidence_aliases=item["evidence_aliases"]))
    formal = Path("/tmp/hcsn-r20-runtime-frozen-d0ac")
    formal_sha = digest(formal.read_bytes())
    assert formal_sha == "b30befcb76f00533029c60ce7a430a2b057bc152107625d7a5a4be3cd16f2798"
    manifest = dict(schema="hcsn-fixed-binary-artifacts-v1", formal_binary_sha256=formal_sha,
                    formal_source_freeze="d0acb8d41a9b7682d22f606998c4e04fe4093e6c", binaries=rows,
                    missing_original_paths=missing, scope="Retained exact research artifacts; SHA256 integrity does not grant production authorization or peer authentication.")
    (component / "BINARY_ARTIFACTS.json").write_text(json.dumps(manifest, indent=2)+"\n")
    print(json.dumps(dict(binaries=len(rows), parts=sum(len(row["parts"]) for row in rows),
                          raw_bytes=sum(row["bytes"] for row in rows), gzip_bytes=sum(row["gzip_bytes"] for row in rows), missing=missing), sort_keys=True))


if __name__ == "__main__":
    main()
