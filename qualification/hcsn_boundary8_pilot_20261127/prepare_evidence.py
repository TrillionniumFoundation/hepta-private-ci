"""Select exact predecessor evidence from a pinned one-run CI archive.

This program has no model dependencies and never imports or executes payloads.
It does not fetch a replacement artifact or infer missing source identities.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import zipfile


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, raw):
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def main():
    if len(sys.argv) != 4:
        raise SystemExit("prepare_evidence.py BINDING_JSON EXACT_ARCHIVE NEW_OUTPUT_DIRECTORY")
    binding_path, archive_path, destination = (Path(value).resolve() for value in sys.argv[1:])
    binding = json.loads(binding_path.read_text())
    if binding["status"] != "FROZEN_FOR_EXECUTION_AFTER_ROOT_REVIEW":
        raise ValueError("predecessor archive identity not frozen for execution")
    expected = binding["predecessor_artifact"]
    size = archive_path.stat().st_size
    if size != expected["bytes"] or not 0 < size <= 16777216:
        raise ValueError("exact predecessor archive size or fixed16MiB cap differs")
    raw = archive_path.read_bytes()
    if sha(raw) != expected["sha256"]:
        raise ValueError("exact predecessor archive SHA differs")
    destination.mkdir(parents=True, exist_ok=False)
    receipts = []
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if len(names) != len(set(names)) or len(names) > 128:
            raise ValueError("duplicate or excessive predecessor ZIP member count")
        if sum(item.file_size for item in infos) > 67108864:
            raise ValueError("predecessor archive expanded size exceeds64MiB")
        for item in infos:
            path = Path(item.filename)
            mode = item.external_attr >> 16
            kind = stat.S_IFMT(mode)
            if (path.is_absolute() or ".." in path.parts or "\\" in item.filename or
                    kind not in (0, stat.S_IFREG, stat.S_IFDIR) or
                    item.file_size > 16777216):
                raise ValueError("unsafe or overlarge predecessor ZIP member")
        for name, item in binding["pilot_files"].items():
            if Path(name).name != name or name.startswith(".") or "/" in name or "\\" in name:
                raise ValueError("evidence destination must be one declared plain filename")
            member = item["archive_member"]
            content = archive.read(member)
            if len(content) != item["bytes"] or sha(content) != item["sha256"]:
                raise ValueError("selected predecessor evidence identity differs: " + name)
            save(destination / name, content)
            receipts.append(dict(name=name, archive_member=member, bytes=len(content), sha256=sha(content)))
    receipt = dict(schema="hepta.boundary-public-evidence-prepared.v1", binding_sha256=sha(binding_path.read_bytes()),
                   exact_artifact=expected, selected_files=receipts, model_calls=0, payload_executed=False,
                   arbitrary_archive_members_extracted=False, original_archive_unchanged=sha(archive_path.read_bytes()) == expected["sha256"])
    save(destination / "PREPARED_EVIDENCE.json", (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode())


if __name__ == "__main__":
    main()
