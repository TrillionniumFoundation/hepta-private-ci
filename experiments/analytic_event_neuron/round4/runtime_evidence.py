"""Actual Hepta transport reuse and verified bounded temporary evidence."""

import hashlib
import json
from pathlib import Path
import shutil
import zipfile

from ..transport import ArtifactTransport
from .runtime_owner import file_sha


def write_json(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


class EvidenceZip:
    """Every appended file is reopened and hashed before removing its source."""
    def __init__(self, path):
        self.path = Path(path)
        if self.path.exists():
            raise FileExistsError(self.path)
        self.entries = {}

    def append(self, directory, prefix):
        directory = Path(directory)
        files = sorted(p for p in directory.rglob("*") if p.is_file())
        incoming = {}
        with zipfile.ZipFile(self.path, "a", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in files:
                relative = prefix + "/" + str(path.relative_to(directory))
                if relative in self.entries or relative.startswith("/") or ".." in Path(relative).parts:
                    raise ValueError("Unsafe or duplicate archive member")
                incoming[relative] = {"sha256": file_sha(path), "bytes": path.stat().st_size}
                archive.write(path, relative)
        with zipfile.ZipFile(self.path) as archive:
            for name, expected in incoming.items():
                payload = archive.read(name)
                if expected != {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}:
                    raise ValueError("Actual archive member readback mismatch")
        self.entries.update(incoming)
        shutil.rmtree(directory)

    def finish(self):
        manifest = self.path.with_suffix(".manifest.json")
        write_json(manifest, {"schema": "hepta.case-evidence.zip.v4", "files": self.entries})
        with zipfile.ZipFile(self.path) as archive:
            if len(archive.namelist()) != len(self.entries) or set(archive.namelist()) != set(self.entries):
                raise ValueError("Archive final member inventory mismatch")
        return {"path": self.path.name, "sha256": file_sha(self.path), "bytes": self.path.stat().st_size,
                "verified_files": len(self.entries), "manifest_sha256": file_sha(manifest),
                "all_entries_reopened_before_source_removal": True}


def acquire(data, i, arm, transport):
    case = str(data["ids"][i])
    initial = transport.deliver(case, arm, "initial", float(data["initial_output"][i]), "preview")
    sensor = transport.observer(case, arm, "sensor", float(data["self_evaluation"][i]))
    values = {key: transport.observer(case, arm, key, float(data[key][i])) for key in
              ("sensor_variance", "repair_cost", "wait_cost", "wait_variance")}
    residual = transport.deliver(case, arm, "residual", sensor - initial, "public_feedback")
    return {"initial": initial, "residuals": [residual], "variances": [values.pop("sensor_variance")], **values}


def acquire_wait(data, i, arm, transport, public):
    case = str(data["ids"][i])
    sensor = transport.observer(case, arm, "wait_sensor", float(data["wait_evaluation"][i]))
    residual = transport.deliver(case, arm, "wait_residual", sensor - public["initial"], "paid_feedback")
    return {**public, "residuals": [*public["residuals"], residual], "variances": [*public["variances"], public["wait_variance"]]}


def transport(directory, scope):
    return ArtifactTransport(Path(directory) / "readbacks", scope)
