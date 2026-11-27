from pathlib import Path, PurePosixPath
import argparse, gzip, hashlib, io, json, tarfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


parser = argparse.ArgumentParser()
parser.add_argument("output")
args = parser.parse_args()
root = Path(__file__).resolve().parent
manifest = json.loads((root / "originals-manifest.json").read_text())
chunks = []
offset = 0
for row in manifest["carriers"]:
    data = (root / row["file"]).read_bytes()
    assert len(data) == row["bytes"] and digest(data) == row["sha256"]
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
        decoded = stream.read(row["decoded_bytes"] + 1)
    assert len(decoded) == row["decoded_bytes"]
    assert digest(decoded) == row["decoded_sha256"] and offset == row["decoded_offset"]
    chunks.append(decoded)
    offset += len(decoded)
archive = b"".join(chunks)
assert len(archive) == manifest["archive"]["bytes"]
assert digest(archive) == manifest["archive"]["sha256"]
with gzip.GzipFile(fileobj=io.BytesIO(archive)) as stream:
    raw_tar = stream.read(manifest["archive"]["tar_bytes"] + 1)
assert len(raw_tar) == manifest["archive"]["tar_bytes"]
assert digest(raw_tar) == manifest["archive"]["tar_sha256"]
expected = {row["object"]: row["sha256"] for row in manifest["originals"]}
objects = {}
with tarfile.open(fileobj=io.BytesIO(raw_tar), mode="r:") as archive_tar:
    for member in archive_tar.getmembers():
        assert (
            member.isfile() and member.name in expected and member.name not in objects
        )
        value = archive_tar.extractfile(member).read()
        assert digest(value) == expected[member.name]
        objects[member.name] = value
assert set(objects) == set(expected)
output = Path(args.output)
output.mkdir(mode=0o700, parents=True, exist_ok=False)
seen = set()
for row in manifest["originals"]:
    name = PurePosixPath(row["path"])
    assert not name.is_absolute() and ".." not in name.parts and str(name) not in seen
    seen.add(str(name))
    value = objects[row["object"]]
    assert len(value) == row["bytes"] and digest(value) == row["sha256"]
    destination = output.joinpath(*name.parts)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as stream:
        stream.write(value)
    assert destination.read_bytes() == value
assert len(seen) == manifest["original_count"]
print(
    json.dumps(
        {
            "restored_originals": len(seen),
            "all_bytes_verified": True,
            "archive_sha256": manifest["archive"]["sha256"],
        }
    )
)
