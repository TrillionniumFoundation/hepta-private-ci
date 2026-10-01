"""Root installer materializes the first actual CPU body from immutable inputs.

The output records installation identity. It neither issues resources nor
qualifies E/S evidence. Only a new, empty body destination is accepted.
"""

import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import sys
import time


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def source(item, maximum):
    if set(item) != {"path", "digest"}:
        raise ValueError("exact Root source fields required")
    path = Path(item["path"])
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError("canonical Root source required")
    for ancestor in path.parents:
        metadata = ancestor.lstat()
        if metadata.st_uid != 0 or metadata.st_mode & 0o022:
            raise ValueError("mutable source ancestor")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0
                or before.st_nlink != 1 or before.st_mode & 0o222
                or not 0 < before.st_size <= maximum):
            raise ValueError("immutable bounded Root file required")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(maximum + 1)
        stable = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_nlink,
                                value.st_uid, value.st_gid, value.st_size,
                                value.st_mtime_ns, value.st_ctime_ns)
        if stable(before) != stable(os.fstat(fd)) or stable(before) != stable(path.stat()) or digest(data) != item["digest"]:
            raise ValueError("Root source changed")
        return data
    finally:
        os.close(fd)


def create(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fchmod(stream.fileno(), 0o444)
        os.fsync(stream.fileno())
    return {"path": str(path), "digest": digest(data)}


def compile_body(config, destination):
    required = {"schema", "agent_id", "body_generation", "organ_id", "base_program",
                "source_provenance", "original_profile", "preprocessor", "current_verified_inputs"}
    if set(config) != required or config["schema"] != "hepta.cpu-neuron.root-first-body-installation.v1":
        raise ValueError("first body installation schema")
    if config["body_generation"] != 1:
        raise ValueError("first installation cannot replace an existing body generation")
    for name in ("agent_id", "organ_id"):
        if not isinstance(config[name], str) or not 1 <= len(config[name].encode()) <= 255:
            raise ValueError("bounded installation identity")
    program = source(config["base_program"], 512 * 1024 * 1024)
    if not program.startswith(b"\x7fELF"):
        raise ValueError("actual native Linux program required")
    provenance_bytes = source(config["source_provenance"], 64 * 1024)
    profile_bytes = source(config["original_profile"], 64 * 1024)
    source(config["preprocessor"], 64 * 1024)
    inputs = json.loads(source(config["current_verified_inputs"], 64 * 1024))
    provenance = json.loads(provenance_bytes)
    if (provenance.get("schema") != "hepta.cpu-neuron.installed-native-build-provenance.v1"
            or provenance.get("program") != config["base_program"]
            or len(bytes.fromhex(provenance["source_revision"])) != 20
            or provenance.get("qualification_features") != []):
        raise ValueError("actual normal native source/program build provenance required")
    profile = json.loads(profile_bytes)
    if (inputs["schema"] != "hepta.cpu-neuron.verified-current-installation-inputs.v1"
            or inputs["generation"] != 1 or inputs["model_manifest"] != profile["model"]
            or inputs["weights"] != profile["weights"]
            or inputs["normalization_digest"] != config["preprocessor"]["digest"]
            or inputs["expires_at_ms"] <= time.time_ns() // 1_000_000):
        raise ValueError("actual current model/normalization differs from installed baseline")
    source(profile["model"], 64 * 1024)
    source(profile["weights"], 16 * 1024 * 1024)
    # Preserve concrete original bytes in each bundle's transitive source list.
    base = {"schema": "hepta.cpu-neuron.installed-base-bundle.v1", "program": config["base_program"],
            "source_provenance": config["source_provenance"]}
    organ = {"schema": "hepta.cpu-neuron.installed-organ-bundle.v1", "organ_id": config["organ_id"],
             "original_profile": config["original_profile"], "model": profile["model"],
             "weights": profile["weights"], "preprocessor": config["preprocessor"],
             "execution_profile_digest": inputs["execution_profile_digest"]}
    base_bytes, organ_bytes = encoded(base), encoded(organ)
    manifest = {"schema": "hepta.cpu-neuron.installed-body-manifest.v1", "agent_id": config["agent_id"],
                "body_generation": 1, "base_bundle_digest": digest(base_bytes),
                "organ_id": config["organ_id"], "organ_bundle_digest": digest(organ_bytes),
                "cell_slot_id": None, "cell_bundle_digest": None,
                "effective_parameter_digest": inputs["execution_profile_digest"],
                "source_revision_digest": digest(provenance_bytes)}
    manifest_bytes = encoded(manifest)
    identity = b"hepta.neuron.body-bundle-identity.v1" + bytes.fromhex(digest(manifest_bytes))
    identity += struct.pack(">Q", 1) + bytes.fromhex(digest(base_bytes))
    organ_id = config["organ_id"].encode()
    identity += struct.pack(">I", len(organ_id)) + organ_id + bytes.fromhex(digest(organ_bytes)) + b"\x00"
    identity += bytes.fromhex(inputs["execution_profile_digest"]) + bytes.fromhex(digest(provenance_bytes))
    if destination.exists() or not destination.is_absolute() or destination.parent.resolve() != destination.parent:
        raise ValueError("exclusive canonical new body destination required")
    parent = destination.parent.stat()
    if parent.st_uid != 0 or parent.st_mode & 0o022:
        raise ValueError("Root body parent required")
    destination.mkdir(mode=0o755)
    sources = [create(destination / name, data) for name, data in (
        ("base-bundle.json", base_bytes), ("organ-bundle.json", organ_bytes),
        ("body-manifest.json", manifest_bytes))]
    compiled = {**manifest, "body_manifest_digest": digest(manifest_bytes),
                "runtime_body_digest": digest(identity), "sources": sources,
                "resource_authority_issued": False, "actual_neuron_tick": False}
    create(destination / "compiled-body.json", encoded(compiled))
    for path in (destination, destination.parent):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        os.fsync(fd)
        os.close(fd)
    return compiled


def main():
    if os.geteuid() != 0 or len(sys.argv) != 4:
        raise ValueError("Root config-path config-pin new-body-directory required")
    config = json.loads(source({"path": sys.argv[1], "digest": sys.argv[2]}, 64 * 1024))
    print(json.dumps(compile_body(config, Path(sys.argv[3])), separators=(",", ":")))


if __name__ == "__main__":
    main()
