"""Restore the qualified Linux native executables with a path-rebased receipt.

All archive and member identities are checked before creating the new output
directory. The original build receipt remains byte-identical. This restores
existing artifacts; it neither builds nor silently requalifies dependencies.
"""
import argparse
import copy
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile

HERE = Path(__file__).resolve().parent
MAX_PART = 384000
MAX_GZIP = 8 * 1024 * 1024
MAX_TAR = 16 * 1024 * 1024
MAX_MEMBERS = 256


def digest(data):
    return hashlib.sha256(data).hexdigest()


def bounded_integer(value, maximum):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError("invalid bounded byte/count field")
    return value


def sha_string(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("invalid SHA256 field")
    return value


def safe_name(value, *, part=False):
    if not isinstance(value, str) or not value or len(value) > 240 or "\\" in value or "\0" in value:
        raise ValueError("invalid relative member name")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ValueError("unsafe/noncanonical relative member name")
    if part and len(path.parts) != 1:
        raise ValueError("bundle parts must be direct regular files")
    if not part and (len(path.parts) < 2 or path.parts[0] not in ("build", "executables")):
        raise ValueError("member outside the native bundle roots")
    return path


def read_regular(path, limit):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    if path.is_symlink():
        raise ValueError("input symlink refused")
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("regular bounded input required")
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("input exceeds byte limit")
    return data


def verified_parts(bundle, rows, prefix):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 64:
        raise ValueError("invalid part inventory")
    result = []
    for index, row in enumerate(rows):
        name = row["path"]
        safe_name(name, part=True)
        expected_name = f"{prefix}{index:03d}" + (".json" if prefix == "inventory" else "")
        if name != expected_name:
            raise ValueError("noncanonical or unordered bundle parts")
        size = bounded_integer(row["bytes"], MAX_PART)
        data = read_regular(bundle / name, MAX_PART)
        if len(data) != size or digest(data) != sha_string(row["sha256"]):
            raise ValueError(("bundle part identity mismatch", name))
        result.append(data)
    return result


def verified_members(bundle):
    manifest_bytes = read_regular(bundle / "MANIFEST.json", MAX_PART)
    manifest = json.loads(manifest_bytes)
    if manifest.get("schema") != "hepta.native-evidence-bundle.v1":
        raise ValueError("unsupported native bundle schema")
    inventory = []
    for data in verified_parts(bundle, manifest["inventory_parts"], "inventory"):
        rows = json.loads(data)
        if not isinstance(rows, list):
            raise ValueError("member inventory must be a list")
        inventory.extend(rows)
    if len(inventory) != bounded_integer(manifest["member_count"], MAX_MEMBERS):
        raise ValueError("member inventory count mismatch")
    expected = {}
    for row in inventory:
        name = row["path"]
        safe_name(name)
        if name in expected:
            raise ValueError("duplicate member inventory")
        expected[name] = (bounded_integer(row["bytes"], MAX_TAR), sha_string(row["sha256"]))
    total = sum(size for size, _ in expected.values())
    if total > MAX_TAR or total != bounded_integer(manifest["total_input_bytes"], MAX_TAR):
        raise ValueError("member total byte limit/mismatch")
    for name in expected:
        if any(parent.as_posix() in expected for parent in PurePosixPath(name).parents):
            raise ValueError("file/directory name collision")
    archive = b"".join(verified_parts(bundle, manifest["archive_parts"], "native-evidence.tar.gz.part"))
    if len(archive) != bounded_integer(manifest["gzip_bytes"], MAX_GZIP) or digest(archive) != sha_string(manifest["gzip_sha256"]):
        raise ValueError("reassembled gzip identity mismatch")
    with gzip.GzipFile(fileobj=io.BytesIO(archive), mode="rb") as compressed:
        tar_bytes = compressed.read(MAX_TAR + 1)
    if len(tar_bytes) > MAX_TAR:
        raise ValueError("decompressed tar exceeds limit")
    members = {}
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as archive:
        for member in archive:
            safe_name(member.name)
            if not member.isfile() or member.name not in expected or member.name in members:
                raise ValueError("unexpected, linked or duplicate tar member")
            size, sha = expected[member.name]
            if member.size != size:
                raise ValueError("tar member length mismatch")
            data = archive.extractfile(member).read(size + 1)
            if len(data) != size or digest(data) != sha:
                raise ValueError("tar member digest mismatch")
            members[member.name] = data
    if members.keys() != expected.keys():
        raise ValueError("incomplete native bundle")
    return manifest, manifest_bytes, members


def restore(bundle, requested_output):
    bundle = bundle.resolve(strict=True)
    if requested_output.exists() or requested_output.is_symlink():
        raise FileExistsError("restore output must be a new directory")
    output = requested_output.parent.resolve(strict=True) / requested_output.name
    manifest, manifest_bytes, members = verified_members(bundle)
    source_name = manifest["source_build_receipt"]
    safe_name(source_name)
    source_bytes = members[source_name]
    source = json.loads(source_bytes)
    if source.get("schema") != "hepta.r7-native-build.v1" or source.get("success") is not True:
        raise ValueError("successful original build receipt required")
    paths = {"binary": manifest["qualified_binary"], "tests": "executables/r7-native-policy-tests"}
    for field, name in paths.items():
        safe_name(name)
        if name not in members or digest(members[name]) != sha_string(source[field + "_sha256"]):
            raise ValueError("executable differs from the original build receipt")
    for name, expected_sha in source["sources"].items():
        safe_name(name, part=True)
        if digest(read_regular(HERE / name, 1024 * 1024)) != sha_string(expected_sha):
            raise ValueError(("clone Rust source differs from the qualified build", name))
    # No extractall: only verified ordinary files under an exclusively new root.
    output.mkdir(mode=0o700, exist_ok=False)
    for name, data in sorted(members.items()):
        destination = output.joinpath(*PurePosixPath(name).parts)
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(data)
        destination.chmod(0o755 if name in paths.values() else 0o600)
        if digest(read_regular(destination, MAX_TAR)) != digest(data):
            raise ValueError("restored file readback mismatch")
    rebased = copy.deepcopy(source)
    rebased.update(schema="hepta.r7-native-restored-build-reference.v1",
        binary=str(output / paths["binary"]), tests=str(output / paths["tests"]),
        original_executable_paths={field: source[field] for field in paths},
        source_receipt=str(output / source_name), source_receipt_sha256=digest(source_bytes),
        bundle_manifest_sha256=digest(manifest_bytes), restored_gzip_sha256=manifest["gzip_sha256"],
        path_rebase_only=True, restoration_verified=True, fresh_build_this_run=False,
        fresh_cargo_build=False, native_source_files_match_clone=True,
        commands_scope="Unchanged historical build commands; no compiler or historical path was used during restoration.",
        restoration=dict(schema="hepta.native-restore.v1", members_verified=len(members),
            archive_parts_verified=len(manifest["archive_parts"]), restorer_sha256=digest(Path(__file__).read_bytes()),
            executable_platform="Original x86_64-unknown-linux-gnu executable; this is not a cross-platform rebuild."))
    receipt = output / "RESTORED_BUILD_RECEIPT.json"
    with receipt.open("x") as stream:
        json.dump(rebased, stream, indent=2, sort_keys=True)
        stream.write("\n")
    receipt.chmod(0o600)
    return dict(output=str(output), binary=rebased["binary"], tests=rebased["tests"],
        build_report=str(receipt), source_receipt_sha256=digest(source_bytes),
        restored_receipt_sha256=digest(receipt.read_bytes()),
        verified_members=len(members), verified_archive_parts=len(manifest["archive_parts"]),
        executable_sha256=rebased["binary_sha256"], fresh_build_this_run=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(restore(args.bundle, args.output), sort_keys=True))
