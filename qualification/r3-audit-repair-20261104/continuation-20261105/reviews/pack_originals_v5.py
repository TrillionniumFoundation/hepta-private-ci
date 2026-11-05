"""Lossless original-byte transport for Git blobs below the connector limit."""
from pathlib import Path
import base64
import gzip
import hashlib
import json

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "hepta-audit-fifth/v5-archives"


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def pack(label, inputs):
    directory = OUT / label
    directory.mkdir(parents=True, exist_ok=False)
    originals, rows = [], []
    for logical_name, relative in inputs:
        path = ROOT / relative
        raw = path.read_bytes()
        rows.append({"logical_name": logical_name, "local_source": str(path), **identity(raw)})
        originals.append({"logical_name": logical_name, "bytes_base64": base64.b64encode(raw).decode()})
    encoded = (json.dumps(originals, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    compressed = gzip.compress(encoded, compresslevel=9, mtime=0)
    parts = []
    for n, pos in enumerate(range(0, len(compressed), 180000)):
        raw = compressed[pos:pos + 180000]
        name = f"part-{n:03d}.b64"
        transport = (base64.b64encode(raw).decode() + "\n").encode()
        (directory / name).write_bytes(transport)
        parts.append({"name": name, "compressed_offset": pos, "decoded": identity(raw), "transport": identity(transport)})
    manifest = {"schema": "hepta-lossless-original-archive-v1", "label": label,
                "encoding": "ordered base64 parts of gzip of JSON array with per-original bytes_base64",
                "originals": rows, "original_file_count": len(rows), "original_byte_total": sum(x["bytes"] for x in rows),
                "uncompressed_transport": identity(encoded), "compressed": identity(compressed), "parts": parts,
                "native_commands_run_by_archiver": False, "source_bytes_rewritten": False}
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    verify(manifest_path)
    return {"label": label, "manifest": identity(manifest_path.read_bytes()), "originals": len(rows),
            "original_bytes": manifest["original_byte_total"], "parts": len(parts), "compressed_bytes": len(compressed)}


def verify(manifest_path):
    manifest = json.loads(manifest_path.read_bytes())
    chunks = []
    for row in manifest["parts"]:
        encoded = (manifest_path.parent / row["name"]).read_bytes()
        assert identity(encoded) == row["transport"]
        decoded = base64.b64decode(encoded.strip(), validate=True)
        assert identity(decoded) == row["decoded"]
        assert sum(map(len, chunks)) == row["compressed_offset"]
        chunks.append(decoded)
    compressed = b"".join(chunks)
    assert identity(compressed) == manifest["compressed"]
    raw = gzip.decompress(compressed)
    assert identity(raw) == manifest["uncompressed_transport"]
    originals = json.loads(raw)
    assert len(originals) == len(manifest["originals"]) == manifest["original_file_count"]
    for row, expected in zip(originals, manifest["originals"]):
        assert row["logical_name"] == expected["logical_name"]
        decoded = base64.b64decode(row["bytes_base64"], validate=True)
        assert identity(decoded) == {k: expected[k] for k in ("bytes", "sha256", "blob")}
        assert Path(expected["local_source"]).read_bytes() == decoded


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        for name in sys.argv[1:]:
            verify(Path(name))
            print(json.dumps({"verified": name}))
    else:
        batches = [
            ("foundation-final-metadata", [("B10_R2e3_final-metadata.log",
                "ci-audit/recovered-20261105/b16-ai395-foundation-v7-v2/terminal-originals/B10_R2e3_final-metadata.log")]),
            ("driver-enable-originals", [
                ("launch-request-DISABLED-actual-foundation-v1.json", "ci-audit/recovered-20261105/b16-ai395-driver-v7-bound-candidate-v1/launch-request-DISABLED-actual-foundation-v1.json"),
                ("driver-launch-request-ENABLED.json", "hepta-audit-fifth/driver-launch-request-ENABLED.json")])]
        for label, inputs in batches:
            print(json.dumps(pack(label, inputs)))
