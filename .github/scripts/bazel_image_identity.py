#!/usr/bin/env python3
"""Bind a smoked immutable Docker image to its original configuration bytes."""

import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory

REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
MAX_JSON = 256 * 1024
MAX_PROOF = 2 * 1024 * 1024
INDEX_TYPES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
}
MANIFEST_TYPES = {
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
}
CONFIG_TYPES = {
    "application/vnd.oci.image.config.v1+json",
    "application/vnd.docker.container.image.v1+json",
}


class IdentityError(Exception):
    pass


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def safe_member(name):
    path = PurePosixPath(name)
    if (
        not name
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in name
        or str(path) != name.rstrip("/")
    ):
        raise IdentityError("Unsafe image archive member path")
    return name


def bounded_read(path, limit=MAX_PROOF):
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise IdentityError("Image identity evidence exceeds its size bound")
    return data


def resolve_identity(read, names, source, inspected):
    image_id = inspected["Id"]
    arch = source["architecture"]
    if (
        not DIGEST.fullmatch(image_id)
        or arch not in ("amd64", "arm64")
        or source["repository"] != REPOSITORY
        or not re.fullmatch(r"[0-9a-f]{40}", source["source_sha"])
        or not re.fullmatch(r"ubuntu@sha256:[0-9a-f]{64}", source["base_image"])
        or not re.fullmatch(r"[0-9a-f]{64}", source["dockerfile_sha256"])
        or (inspected["Os"], inspected["Architecture"]) != ("linux", arch)
    ):
        raise IdentityError("Invalid local image source or platform identity")

    def blob(descriptor, media_types):
        reference = descriptor.get("digest", "")
        if (
            not DIGEST.fullmatch(reference)
            or descriptor.get("mediaType") not in media_types
            or type(descriptor.get("size")) is not int
        ):
            raise IdentityError("Invalid local image descriptor")
        data = read("blobs/sha256/" + reference.split(":")[1])
        if digest(data) != reference or len(data) != descriptor["size"]:
            raise IdentityError("Local image descriptor does not match its bytes")
        return data

    root_path = "blobs/sha256/" + image_id.split(":")[1]
    root_data = read(root_path) if root_path in names else None
    root = json.loads(root_data) if root_data is not None else {}
    if root_data is not None and digest(root_data) != image_id:
        raise IdentityError("Local image root bytes do not match the smoked ID")
    media_type = root.get("mediaType")
    image_manifest_digest = None
    if media_type in INDEX_TYPES | MANIFEST_TYPES:
        outer = json.loads(read("index.json"))
        descriptors = outer.get("manifests", [])
        if (
            outer.get("schemaVersion") != 2
            or outer.get("mediaType") not in INDEX_TYPES
            or len(descriptors) != 1
            or descriptors[0].get("digest") != image_id
            or descriptors[0].get("mediaType") != media_type
            or blob(descriptors[0], INDEX_TYPES | MANIFEST_TYPES) != root_data
            or root.get("schemaVersion") != 2
        ):
            raise IdentityError("Archive index is not bound to the smoked image ID")
        if media_type in INDEX_TYPES:
            matches = [
                entry
                for entry in root.get("manifests", [])
                if entry.get("platform", {}).get("os") == "linux"
                and entry.get("platform", {}).get("architecture") == arch
                and entry.get("platform", {}).get("variant", "") in ("", "v8")
            ]
            if len(matches) != 1:
                raise IdentityError(
                    "Local index must contain one expected native platform"
                )
            manifest_data = blob(matches[0], MANIFEST_TYPES)
            expected_manifest_type = matches[0]["mediaType"]
            kind = "oci-index-id"
        else:
            manifest_data = root_data
            expected_manifest_type = media_type
            kind = "oci-manifest-id"
        manifest = json.loads(manifest_data)
        if (
            manifest.get("schemaVersion") != 2
            or manifest.get("mediaType") != expected_manifest_type
        ):
            raise IdentityError("Invalid local native image manifest")
        image_manifest_digest = digest(manifest_data)
        config_data = blob(manifest["config"], CONFIG_TYPES)
    else:
        # The classic image store uses the config digest itself as the image ID.
        entries = json.loads(read("manifest.json"))
        if not isinstance(entries, list) or len(entries) != 1:
            raise IdentityError("Classic archive must contain exactly one saved image")
        config_data = read(safe_member(entries[0]["Config"]))
        if digest(config_data) != image_id:
            raise IdentityError(
                "Classic configuration bytes do not match the smoked ID"
            )
        kind = "classic-config-id"

    config = json.loads(config_data)
    expected_labels = {
        "org.opencontainers.image.source": "https://github.com/" + REPOSITORY,
        "org.opencontainers.image.revision": source["source_sha"],
        "org.opencontainers.image.base.name": source["base_image"],
        "org.opencontainers.image.base.digest": source["base_image"].split("@", 1)[1],
        "io.hepta.dockerfile.sha256": source["dockerfile_sha256"],
    }
    actual = config.get("config", {})
    labels = actual.get("Labels", {})
    inspected_config = inspected.get("Config", {})
    if (
        (config.get("os"), config.get("architecture")) != ("linux", arch)
        or actual.get("User") != "ubuntu"
        or actual.get("Entrypoint")
        or inspected_config.get("User") != "ubuntu"
        or inspected_config.get("Entrypoint")
        or any(labels.get(key) != value for key, value in expected_labels.items())
        or any(
            inspected_config.get("Labels", {}).get(key) != value
            for key, value in expected_labels.items()
        )
        or config.get("rootfs", {}).get("diff_ids")
        != inspected.get("RootFS", {}).get("Layers")
    ):
        raise IdentityError(
            "Local configuration differs from the source or smoked image"
        )
    return {
        "image_id": image_id,
        "architecture": arch,
        "identity_kind": kind,
        "image_manifest_digest": image_manifest_digest,
        "config_digest": digest(config_data),
    }


def identity_from_archive(path, source, inspected):
    selected = {}
    with tarfile.open(path, mode="r:") as archive:
        members = {}
        for member in archive:
            safe_member(member.name)
            if (
                member.name in members
                or len(members) >= 4096
                or not (member.isfile() or member.isdir())
            ):
                raise IdentityError(
                    "Duplicate, linked or unsupported image archive member"
                )
            members[member.name] = member

        def read(name):
            safe_member(name)
            member = members.get(name)
            if (
                member is None
                or not member.isfile()
                or not 0 <= member.size <= MAX_JSON
            ):
                raise IdentityError("Missing or oversized image metadata member")
            # Read ordinary metadata only; never extract archive paths to disk.
            with archive.extractfile(member) as stream:
                data = stream.read(MAX_JSON + 1)
            if len(data) != member.size:
                raise IdentityError("Truncated image metadata member")
            selected[name] = base64.b64encode(data).decode()
            return data

        result = resolve_identity(read, members, source, inspected)
    return {"schema": "hepta-local-image-identity-v1", **result, "members": selected}


def verified_local_identity(evidence):
    source = json.loads(bounded_read(evidence / "source.json"))
    inspected = json.loads(bounded_read(evidence / "image-inspect.json"))[0]
    proof = json.loads(bounded_read(evidence / "local-image-identity.json"))
    verified_id = bounded_read(evidence / "verified-image-id.txt", 80).decode().strip()
    if (
        proof.get("schema") != "hepta-local-image-identity-v1"
        or verified_id != inspected["Id"]
        or proof.get("image_id") != verified_id
        or not isinstance(proof.get("members"), dict)
        or len(proof["members"]) > 8
    ):
        raise IdentityError("Local identity evidence is not bound to the smoked image")
    members = {}
    for name, encoded in proof["members"].items():
        safe_member(name)
        data = base64.b64decode(encoded, validate=True)
        if len(data) > MAX_JSON:
            raise IdentityError("Oversized retained image metadata")
        members[name] = data
    used = set()

    def read(name):
        if name not in members:
            raise IdentityError("Missing retained image metadata")
        used.add(name)
        return members[name]

    result = resolve_identity(read, members, source, inspected)
    if used != set(members) or any(
        proof.get(key) != value for key, value in result.items()
    ):
        raise IdentityError("Retained image identity differs from its original content")
    return result


def capture_local_identity(evidence, *, run=subprocess.run):
    source = json.loads(bounded_read(evidence / "source.json"))
    inspected = json.loads(bounded_read(evidence / "image-inspect.json"))[0]
    image_id = bounded_read(evidence / "verified-image-id.txt", 80).decode().strip()
    if not DIGEST.fullmatch(image_id) or image_id != inspected["Id"]:
        raise IdentityError("Only the successfully smoked immutable ID can be saved")
    environment = dict(os.environ)
    environment.pop("GHCR_PUBLISH_TOKEN", None)
    with TemporaryDirectory(
        prefix="hepta-image-identity-", dir=environment.get("RUNNER_TEMP")
    ) as directory:
        archive = Path(directory) / "image.tar"
        saved = run(
            ["docker", "image", "save", "--output", str(archive), image_id],
            env=environment,
            capture_output=True,
            check=False,
            timeout=120,
        )
        if saved.returncode:
            raise IdentityError("Unable to save the smoked immutable image")
        proof = identity_from_archive(archive, source, inspected)
        with archive.open("rb") as stream:
            proof["archive_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
        proof["archive_bytes"] = archive.stat().st_size
        (evidence / "local-image-identity.json").write_text(
            json.dumps(proof, indent=2) + "\n"
        )
    verified_local_identity(evidence)


def main():
    try:
        if len(sys.argv) != 2:
            raise IdentityError("Expected the image evidence directory")
        capture_local_identity(Path(sys.argv[1]))
    except (
        IdentityError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        tarfile.TarError,
        subprocess.SubprocessError,
    ) as error:
        print(f"Local image identity verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
