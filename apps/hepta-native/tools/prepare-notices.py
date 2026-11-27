"""Stage the original native license notices for packaging, without networking."""

import argparse
import hashlib
import json
from pathlib import Path
import runpy
import tempfile


RESOURCE_DIR = "apps/hepta-native/resources"
RESTORER = "qa/repository-consolidation/20261115/restore_raw_evidence.py"


def prepare_notices(repo, destination):
    helpers = runpy.run_path(str(repo / RESTORER))
    raw_catalog = helpers["read_regular"](repo, f"{RESOURCE_DIR}/NATIVE-ASSETS.json", 256 * 1024)
    provenance = json.loads(
        helpers["read_regular"](repo, f"{RESOURCE_DIR}/NOTICE_SOURCE.json", 256 * 1024)
    )
    if hashlib.sha256(raw_catalog).hexdigest() != provenance["catalogSha256"]:
        raise ValueError("native notice provenance does not match the resource catalog")
    originals = {row["source_path"]: row for row in provenance["files"]}
    records = json.loads(raw_catalog)["noticeFileSha256"]
    if len(originals) != len(provenance["files"]) or len(records) != len(originals):
        raise ValueError("incomplete or duplicated native notice inventory")

    verified = {}
    for entry in records:
        path = helpers["relative_path"](entry["path"])
        if len(path.parts) != 2 or path.parts[0] != "notices" or path.name in verified:
            raise ValueError("invalid or duplicate native notice path")
        original = f"{RESOURCE_DIR}/{path.as_posix()}"
        source = originals[original]
        if (entry["bytes"], entry["sha256"]) != (source["bytes"], source["sha256"]):
            raise ValueError("native notice metadata differs from its original publication")
        data = helpers["read_verified"](repo, original, entry["bytes"], entry["sha256"])
        blob_hash = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
        if blob_hash != source["git_blob"]:
            raise ValueError("native notice does not match the original Git blob")
        verified[path.name] = data

    destination = destination.absolute()
    if any(parent.is_symlink() for parent in destination.parents):
        raise ValueError("native notice destination parent must not be a symbolic link")
    with tempfile.TemporaryDirectory(prefix=".native-notices-", dir=destination.parent) as temporary:
        notices = Path(temporary) / "notices"
        notices.mkdir()
        for name, data in verified.items():
            (notices / name).write_bytes(data)
        destination.mkdir()
        try:
            notices.rename(destination / "notices")
        except OSError:
            destination.rmdir()
            raise
    return len(verified)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="new packaging directory")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[3]
    print(f"Staged {prepare_notices(repo, args.destination)} exact native license notices")
