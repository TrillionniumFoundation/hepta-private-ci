#!/usr/bin/env python3
"""Read registered historical source volumes as bounded data, without extraction."""

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile
import zlib

from verify_source_custody_container import (
    MAX_ARCHIVE,
    MAX_CONTROL,
    MAX_TAR,
    identity,
    read_regular,
    require,
    unique_object,
)

SCHEMA = "hepta.source-custody-volumes.v1"
SOURCE_COMMIT = "c2130629037b342e6e48154867b65acc8fc82434"
MAX_MEMBER_BYTES = 4 * 1024 * 1024
MAX_VOLUME_MEMBERS = 256
MAX_VOLUMES = 16
MAX_COLLECTION_MEMBERS = 2048
MAX_COLLECTION_BYTES = 32 * 1024 * 1024
# These hashes bind the complete original Git path/mode/object roster, including
# original manifests, notices and reader versions. They are not supplied by callers.
REGISTRATIONS = {
    "library-recovery/additional-source-20261103": "29e8568501443967992db86de26dc514742b96fc00feee5c5db066ac1c826499",
    "library-recovery/control-runtime-named-host-qualification-20261113": "43f432536bb897c86980dfe9f043ad8447f497c0d70ec68387bf2897b3e773f9",
    "library-recovery/embedded-generated-source-20261103": "526a5d5081ac6a137b50ebcb3277657a86452d3187f8800f5247e61b60fbfa64",
    "library-recovery/git-object-repro-20261104": "309f8860ba60ad6006f797f719b485b3f053da4d42e4b125f6da39dbb1d8c209",
    "library-recovery/handoff-command-fragment-20261104": "e281a46fb9a08225ce5cf7fdf8a2a843124ba502c6f876e11782a8fc93621b98",
    "library-recovery/lane-e-unwired-objective-03ec": "55efba52bc6bb09194be0762068c657b4f0e2a01b736e303e3e0a34e63878256",
    "library-recovery/memorycell-int8-20261104": "bd495700df7861f1ff79514d27e55fba93f0007cf32c6eb38f25a09e7f3cd5d1",
    "library-recovery/model-forward-and-diverse60-20261103": "28c658c3af9956045ede1a68a4a5c987bf54a3b651e84fa73dee6b4d0f9e7ceb",
    "library-recovery/notebook-code-cells-20261103": "86485422907ef3e030dfae7526e4871aa32f882584d2f41cae90ece5d713013f",
    "library-recovery/priority-source-20261103": "afa8589e32755792073e6deef5732502785543ec5a1a0fc8755996ef539a843c",
    "library-recovery/retained-source-20261103": "6ab9766f7ef201792a59c2fbdf5c87808e9b7a2abe80d0814a6b193d3e7c136a",
    "library-recovery/rrsnn-v2-source-20261103": "29ce4939cb2ad1480d676d2f1da79dee1e631fe32a3fc35ddb712f62f8aaba8b",
    "library-recovery/small-source-20261103": "895ab3a7d4d25db68f55dd9d8c65bdbf640314663067754a714aced3d8006db2",
    "library-recovery/standalone-python-regressions-20261103": "1a468f634b40e477267879ed4321ede4cfb1b4ecbf1adf383b5b6acd06c3da30",
    "library-recovery/standalone-source-20261103": "6c6d2be016f9824c4b359562838d7618c891cd1b66e7f0df5a17df2471b7e452",
    "library-recovery/taskflow-source-inputs-20261104": "c97e4c7446c4e23ea5371189574bbc82080814b6e5fd46709541a34c013d4f94",
}


def original_path(value):
    """Validate a data member name; parentheses occur in original duplicate names."""
    require(
        isinstance(value, str)
        and re.fullmatch(r"[A-Za-z0-9._/()-]+", value)
        and str(PurePosixPath(value)) == value
        and not value.startswith("/")
        and all(part not in {"", ".", ".."} for part in value.split("/")),
        "unsafe or noncanonical original data path",
    )
    return value


def integer(value, lower, upper, message):
    require(type(value) is int and lower <= value <= upper, message)


def digest(value, length):
    require(
        isinstance(value, str) and re.fullmatch("[0-9a-f]{" + str(length) + "}", value),
        "invalid content identity",
    )


def load_manifest(repository, directory):
    require(not sys.flags.optimize, "optimized verification refused")
    require(directory in REGISTRATIONS, "unregistered source collection")
    raw = read_regular(repository, directory + "/SOURCE_VOLUMES.json", MAX_CONTROL)
    require(
        hashlib.sha256(raw).hexdigest() == REGISTRATIONS[directory],
        "registered original roster changed",
    )
    manifest = json.loads(raw, object_pairs_hook=unique_object)
    require(
        isinstance(manifest, dict)
        and set(manifest)
        == {
            "schema",
            "source_commit",
            "original_directory",
            "member_count",
            "member_bytes",
            "source_executed",
            "scientific_or_runtime_qualification",
            "members",
            "volumes",
        },
        "invalid volume manifest",
    )
    require(
        manifest["schema"] == SCHEMA
        and manifest["source_commit"] == SOURCE_COMMIT
        and manifest["original_directory"] == directory,
        "original source identity changed",
    )
    require(
        manifest["source_executed"] is False
        and manifest["scientific_or_runtime_qualification"] is False,
        "historical source qualification boundary changed",
    )
    integer(
        manifest["member_count"], 1, MAX_COLLECTION_MEMBERS, "collection member bound"
    )
    integer(manifest["member_bytes"], 0, MAX_COLLECTION_BYTES, "collection byte bound")
    require(isinstance(manifest["members"], list), "invalid members")
    require(
        len(manifest["members"]) == manifest["member_count"],
        "original member count mismatch",
    )
    volumes = manifest["volumes"]
    require(
        isinstance(volumes, list) and 0 < len(volumes) <= MAX_VOLUMES,
        "volume count bound",
    )
    expected_volumes = {}
    for number, volume in enumerate(volumes, 1):
        require(
            isinstance(volume, dict)
            and set(volume)
            == {
                "path",
                "bytes",
                "sha256",
                "tar_bytes",
                "tar_sha256",
                "member_count",
                "member_bytes",
            },
            "invalid volume record",
        )
        name = "source-custody-%03d.tar.gz" % number
        require(volume["path"] == name, "noncanonical volume sequence")
        integer(volume["bytes"], 1, MAX_ARCHIVE, "compressed volume byte bound")
        integer(volume["tar_bytes"], 1, MAX_TAR, "expanded volume byte bound")
        integer(volume["member_count"], 1, MAX_VOLUME_MEMBERS, "volume member bound")
        integer(volume["member_bytes"], 0, MAX_MEMBER_BYTES, "volume payload bound")
        digest(volume["sha256"], 64)
        digest(volume["tar_sha256"], 64)
        expected_volumes[name] = volume
    rows = {}
    by_volume = {name: {} for name in expected_volumes}
    for row in manifest["members"]:
        require(
            isinstance(row, dict)
            and set(row)
            == {
                "path",
                "member",
                "mode",
                "bytes",
                "sha256",
                "oid",
                "surface",
                "volume",
            },
            "invalid original member record",
        )
        name = original_path(row["member"])
        require(
            row["path"] == directory + "/" + name and name not in rows,
            "duplicate or inconsistent original path",
        )
        require(row["mode"] == "100644", "original Git mode changed")
        integer(row["bytes"], 0, MAX_MEMBER_BYTES, "original member byte bound")
        digest(row["sha256"], 64)
        digest(row["oid"], 40)
        require(
            row["surface"]
            in {"maintained_reader", "retained_original", "container_only"},
            "unknown surface disposition",
        )
        require(row["volume"] in expected_volumes, "missing registered volume")
        rows[name] = row
        by_volume[row["volume"]][name] = row
    require(
        sum(row["bytes"] for row in rows.values()) == manifest["member_bytes"],
        "original collection byte count mismatch",
    )
    for name, volume in expected_volumes.items():
        members = by_volume[name]
        require(
            len(members) == volume["member_count"]
            and sum(row["bytes"] for row in members.values()) == volume["member_bytes"],
            "volume roster totals mismatch",
        )
    return manifest, by_volume


def verify_volume(repository, directory, volume, expected):
    compressed = read_regular(
        repository, directory + "/" + volume["path"], volume["bytes"]
    )
    require(
        len(compressed) == volume["bytes"]
        and hashlib.sha256(compressed).hexdigest() == volume["sha256"],
        "compressed volume identity mismatch",
    )
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    raw = decoder.decompress(compressed, volume["tar_bytes"] + 1)
    require(
        decoder.eof
        and not decoder.unused_data
        and not decoder.unconsumed_tail
        and len(raw) == volume["tar_bytes"],
        "truncated, oversized or concatenated gzip",
    )
    require(
        hashlib.sha256(raw).hexdigest() == volume["tar_sha256"],
        "expanded volume identity mismatch",
    )
    verified = {}
    cursor = 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        require(not archive.pax_headers, "unsupported archive metadata")
        for member in archive:
            name = original_path(member.name)
            require(
                name in expected and name not in verified,
                "unexpected or duplicate tar member",
            )
            row = expected[name]
            require(
                raw[cursor + 257 : cursor + 265] == b"ustar\x0000",
                "member header must use USTAR magic and version",
            )
            require(
                member.type == tarfile.REGTYPE
                and not member.linkname
                and not member.pax_headers,
                "member must be a plain regular file",
            )
            require(
                member.size == row["bytes"] and member.mode == 0o644,
                "tar member mode or size differs from original Git record",
            )
            require(
                member.uid == member.gid == member.mtime == 0
                and not member.uname
                and not member.gname,
                "unsupported tar owner or timestamp metadata",
            )
            require(
                member.offset == cursor and member.offset_data == cursor + 512,
                "unexpected tar header",
            )
            stream = archive.extractfile(member)
            require(stream is not None, "missing tar bytes")
            with stream:
                data = stream.read(member.size + 1)
            require(
                identity(data) == {key: row[key] for key in ("bytes", "sha256", "oid")},
                "original member fingerprint mismatch",
            )
            verified[name] = data
            cursor += 512 + ((member.size + 511) // 512) * 512
    require(set(verified) == set(expected), "missing tar members")
    require(
        len(raw) == ((cursor + 1024 + 10239) // 10240) * 10240
        and not any(raw[cursor:]),
        "noncanonical tar trailer",
    )
    return verified


def verify_collection(repository, directory):
    repository = Path(repository)
    manifest, by_volume = load_manifest(repository, directory)
    verified = {}
    for volume in manifest["volumes"]:
        members = verify_volume(
            repository, directory, volume, by_volume[volume["path"]]
        )
        for name, data in members.items():
            require(name not in verified, "duplicate member across volumes")
            verified[name] = data
    require(
        len(verified) == manifest["member_count"], "missing original collection member"
    )
    for row in manifest["members"]:
        if row["surface"] == "retained_original":
            current = read_regular(repository, row["path"], row["bytes"])
            require(
                current == verified[row["member"]],
                "visible original control or notice differs from archived original",
            )
    return {directory + "/" + name: data for name, data in verified.items()}


def resolve_original_paths(repository, paths):
    requested = [original_path(path) for path in paths]
    require(
        len(requested) <= MAX_COLLECTION_MEMBERS * len(REGISTRATIONS)
        and len(requested) == len(set(requested)),
        "duplicate or excessive original path request",
    )
    cache = {}
    result = {}
    for path in requested:
        groups = [group for group in REGISTRATIONS if path.startswith(group + "/")]
        require(len(groups) == 1, "missing or ambiguous registered source collection")
        group = groups[0]
        if group not in cache:
            cache[group] = verify_collection(repository, group)
        require(path in cache[group], "missing original source path")
        result[path] = cache[group][path]
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection", nargs="?", choices=sorted(REGISTRATIONS))
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)
    if args.all == (args.collection is not None):
        parser.error("provide exactly one collection or --all")
    repository = Path(__file__).resolve().parents[1]
    groups = sorted(REGISTRATIONS) if args.all else [args.collection]
    records = []
    try:
        for group in groups:
            verified = verify_collection(repository, group)
            records.append(
                {
                    "collection": group,
                    "original_files_verified": len(verified),
                    "original_bytes_verified": sum(map(len, verified.values())),
                    "all_bytes_match_original_git_roster": True,
                    "archived_source_executed": False,
                    "scientific_or_runtime_qualification": False,
                }
            )
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        zlib.error,
        tarfile.TarError,
    ) as error:
        print(f"Source volume verification failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(records))
    return 0


if __name__ == "__main__":
    sys.exit(main())
