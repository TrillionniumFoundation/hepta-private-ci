import base64
import hashlib
import json
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUN = "/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-final-nonrust-format-v1/run/"


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def save(name, raw):
    path = ROOT / name
    if path.exists():
        assert path.read_bytes() == raw, name
    else:
        with path.open("xb") as out:
            out.write(raw)


def decode(name, expected):
    files = sorted(ROOT.glob(name + ".READ_*.original.json"))
    assert files, name
    chunks = []
    observed = []
    offset = 0
    version = None
    for path in files:
        outer = json.loads(path.read_bytes())
        assert not outer.get("isError"), path.name
        text = [x["text"] for x in outer["content"] if x.get("type") == "text"]
        assert len(text) == 1, path.name
        response = json.loads(text[0])
        raw = base64.b64decode(response["data_base64"], validate=True)
        assert response["path"] == RUN + name
        assert response["offset"] == offset
        assert response["next_offset"] == offset + len(raw)
        assert response["chunk_sha256"] == hashlib.sha256(raw).hexdigest()
        version = version or response["version"]
        assert response["version"] == version
        assert response["size"] == expected["bytes"]
        offset = response["next_offset"]
        observed.append({"sdk": path.name, "sdk_identity": pin(path.read_bytes()),
                         "offset": response["offset"], "next_offset": offset,
                         "chunk_sha256": response["chunk_sha256"], "version": version,
                         "eof": response["eof"]})
        chunks.append(raw)
    assert response["eof"] and offset == expected["bytes"]
    raw = b"".join(chunks)
    assert pin(raw) == {k: expected[k] for k in ("bytes", "sha256", "git_blob")}, name
    save(name, raw)
    row = {"name": name, **pin(raw), "native_full_file_read": True,
           "version": version, "reads": observed}
    if name.endswith(".gz"):
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        body = decoder.decompress(raw, expected["raw_bytes"] + 1)
        assert decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail
        assert pin(body) == {k: expected["raw_" + k] for k in ("bytes", "sha256", "git_blob")}
        decoded_name = name[:-3]
        save(decoded_name, body)
        row["decoded_companion"] = {"name": decoded_name, **pin(body)}
        parts = []
        for part in expected.get("parts", []):
            start = part["decoded_offset"]
            chunk = raw[start:start + part["decoded_bytes"]]
            assert hashlib.sha256(chunk).hexdigest() == part["decoded_sha256"]
            encoded = base64.b64encode(chunk) + b"\n"
            assert pin(encoded) == {k: part[k] for k in ("bytes", "sha256", "git_blob")}
            save(part["name"], encoded)
            parts.append({"name": part["name"], **pin(encoded),
                          "representation": "lossless encoding of actual full binary read; matches producer part identity"})
        row["lossless_parts"] = parts
    return row


if __name__ == "__main__":
    artifacts = json.loads((ROOT / "ARTIFACTS.json").read_bytes())
    expected = {x["name"]: x for x in artifacts["files"]}
    names = sys.argv[1:]
    assert names and len(names) == len(set(names))
    rows = [decode(name, expected[name]) for name in names]
    for row in rows:
        print(json.dumps(row, separators=(",", ":")))
