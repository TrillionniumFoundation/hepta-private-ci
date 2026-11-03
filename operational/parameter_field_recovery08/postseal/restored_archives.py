"""Fresh copy evidence for immutable archives restored on a different machine."""

from pathlib import Path
import shutil
import zipfile

from operational.parameter_field_recovery08 import common as c
from operational.parameter_field_recovery08.postseal import review

SCHEMA = "hepta.execution08.restored-readback.1"
FIELDS = ("source_device_inode", "staged_device_inode", "readback_device_inode")


def copy_new(stream, destination, item):
    destination = Path(destination)
    c.need(destination.resolve() == destination, "Restoration path contains a symlink")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as output:
        shutil.copyfileobj(stream, output, 1024 * 1024)
    c.checked({**item, "path": str(destination)})


def capture_proof(item, source, staged, readback):
    value = {"path": item["path"], "source": {**item, "path": str(source)}}
    for field, path in zip(FIELDS, (source, staged, readback)):
        c.checked({**item, "path": str(path)})
        info = path.stat()
        value[field] = [info.st_dev, info.st_ino]
    c.need(len({tuple(value[f]) for f in FIELDS}) == 3,
           "Restored readback is not three independent files")
    return value


def restore_archive(row, downloaded, source_directory):
    """Restore new copies; never edit an ACK, manifest, or old wait4 receipt."""
    ack = c.bound(row["ack"])
    artifact = ack["artifact"]
    actual = c.descriptor(downloaded)
    c.need(all(actual[k] == artifact[k] for k in ("bytes", "sha256")),
           "Fresh provider download differs from immutable artifact")
    directory = Path(row["ack"]["path"]).parent
    archive = Path(ack["readback"]["raw_archive"]["path"])
    c.need(archive.parent == directory / "download_raw" and not archive.exists(),
           "Fresh canonical raw archive destination required")
    archive.parent.mkdir(parents=True, exist_ok=True)
    downloaded.rename(archive)
    proofs = []
    with zipfile.ZipFile(archive) as saved:
        for item in ack["logical_files"]:
            relative = review.logical(item["path"])
            key = "payload/" + relative.as_posix()
            c.need(saved.getinfo(key).file_size == item["bytes"], "Payload size differs")
            paths = (source_directory / relative,
                     directory / "upload/payload" / relative,
                     directory / "readback/payload" / relative)
            for path in paths:
                with saved.open(key) as stream:
                    copy_new(stream, path, item)
            proofs.append(capture_proof(item, *paths))
    return {"artifact": artifact, "ack": row["ack"], "manifest": ack["manifest"],
            "files": proofs}


class RestoredMetadata(review.Metadata):
    """Keep historical independence checks, and bind live copies to a new receipt."""

    def __init__(self, receipt, rows):
        super().__init__()
        value = self.read(receipt)
        c.need(value.get("schema") == SCHEMA
               and value.get("historical_receipts_modified") is False,
               "Explicit restored-readback receipt required")
        records = value.get("archives", [])
        c.need(len(records) == len(rows)
               and len({r["artifact"]["id"] for r in records}) == len(records),
               "Restored archive receipt population differs")
        self.archives = {r["artifact"]["id"]: r for r in records}
        for row in rows:
            record = self.archives.get(row["artifact"]["id"], {})
            files = record.get("files", [])
            c.need(record.get("artifact") == row["artifact"]
                   and record.get("ack") == row["ack"]
                   and record.get("manifest") == row["manifest"]
                   and len(files) == len(row["logical_files"])
                   and {p["path"] for p in files} == {p["path"] for p in row["logical_files"]},
                   "Fresh receipt does not bind the original archive population")
            record["by_path"] = {p["path"]: p for p in files}

    def readback_proof(self, artifact, item, historical):
        record = self.archives[artifact["id"]]
        c.need(record["artifact"] == artifact, "Fresh artifact identity differs")
        proof = record["by_path"][item["path"]]
        source = proof["source"]
        c.need(all(source[k] == item[k] for k in ("bytes", "sha256")),
               "Restored source bytes are not the archived payload")
        path = self.check(source)
        info = path.stat()
        c.need(proof["source_device_inode"] == [info.st_dev, info.st_ino],
               "Restored source inode identity differs")
        return proof


def restore_final_raw(rows, source_root, raw_root, manifest_item):
    """Select the last immutable delivery of each raw name, then check final pins."""
    latest = {}
    for row in rows:
        for item in row["logical_files"]:
            if item["path"].startswith("raw/"):
                latest[item["path"][4:]] = (row["artifact"]["id"], item)
    # The manifest is itself delivered in the final closure archive.
    relative = Path(manifest_item["path"]).relative_to(raw_root).as_posix()
    artifact_id, item = latest[relative]
    manifest_source = source_root / str(artifact_id) / item["path"]
    c.need(all(c.descriptor(manifest_source)[k] == manifest_item[k]
               for k in ("bytes", "sha256")), "Final manifest delivery differs")
    manifest = c.read(manifest_source)
    expected = {**manifest["logical_paths"], relative: manifest_item}
    for name, pin in expected.items():
        review.logical(name)
        unused_artifact_id, item = latest[name]
        c.need(all(item[k] == pin[k] for k in ("bytes", "sha256")),
               "Final raw coverage differs: " + name)
    for name, (artifact_id, item) in latest.items():
        review.logical(name)
        destination = raw_root / name
        with (source_root / str(artifact_id) / item["path"]).open("rb") as stream:
            copy_new(stream, destination, item)
    return len(latest)
