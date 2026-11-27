#!/usr/bin/env python3
"""Verify preserved source snapshots as data; never extract or execute them."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tarfile
import zlib

SCHEMA = "hepta.source-custody-container.v1"
SOURCE_COMMIT = "aa37c2723e4856f5c251cc52721286ff8c48851c"
FOLLOWUP = "library-recovery/followup-source-20261103"
UNRESOLVED = "library-recovery/20261107"
MIXED = "library-recovery/mixed-patch-new-files-20261103"
MAX_CONTROL = 1024 * 1024
MAX_ARCHIVE = 8 * 1024 * 1024
MAX_TAR = 16 * 1024 * 1024
SNAPSHOTS = {
    MIXED: {
        "manifest": "SOURCE_MANIFEST.json",
        "notice_count": 3,
        "controls": {
            "PARSER_QUALIFICATION.json": "a7335c5c2cad306ce797a822a876c7bfc15b59f8",
            "README.md": "932f1a1f714dd44c6c8e6c879ded0abfa61e5b77",
            "SOURCE_MANIFEST.json": "c07d6710208bb68d93f3cd60de553d3b9bed8fe2",
            "notices/7f77de13d6a3a5b2a7b35bfb249b7902317c2045.txt": "7f77de13d6a3a5b2a7b35bfb249b7902317c2045",
            "notices/d952d62c065f3f35fb83a173496e90b21525aef3.txt": "d952d62c065f3f35fb83a173496e90b21525aef3",
            "notices/f9afe0989588d7f672fa35a4ebec946189bf4eee.txt": "f9afe0989588d7f672fa35a4ebec946189bf4eee",
            "patch_parser.py": "6c097ab0254a9736eb65283b9441f954889a5dd4",
            "verify_sources.py": "0c9c615dd5a6feeb37e3d9f8c262b7d91ae128a6",
        },
    },
    FOLLOWUP: {
        "manifest": "SOURCE_MANIFEST.json",
        "controls": {
            "README.md": "978f05bb3a6880227a72547d6436d2d45ef577f8",
            "SOURCE_MANIFEST.json": "0bbbc4eafd211a2cff87a373d7c5340b48541bd1",
            "verify_projection.py": "7ce4e3ae73922fe7ff1d38c1471ec2d5ece1a298",
        },
    },
    UNRESOLVED: {
        "manifest": "SOURCE_CUSTODY.json",
        "controls": {
            "REPRODUCIBILITY.md": "dfa17b8c778c94440e45572b1a9d70e92735e39d",
            "SOURCE_CUSTODY.json": "57855c8c7555baed176fbe38fc19e7ca4403d271",
        },
    },
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def canonical(value):
    require(
        isinstance(value, str)
        and re.fullmatch(r"[A-Za-z0-9._/-]+", value)
        and str(PurePosixPath(value)) == value
        and not value.startswith("/")
        and all(part not in {".", "..", ""} for part in value.split("/")),
        "unsafe or noncanonical path",
    )
    return value


def identity(raw):
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "oid": hashlib.sha1(
            b"blob " + str(len(raw)).encode() + b"\0" + raw
        ).hexdigest(),
    }


def file_identity(value):
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def read_regular(root, relative, limit):
    canonical(relative)
    require(type(limit) is int and 0 <= limit <= MAX_TAR, "invalid read limit")
    for parent in PurePosixPath(relative).parents:
        require(not (root / parent).is_symlink(), "symbolic link in input path")
    path = root / relative
    before = path.lstat()
    require(
        stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
        "input must be a regular single-link file",
    )
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_BINARY", 0)
    with os.fdopen(os.open(path, flags), "rb") as handle:
        opened = os.fstat(handle.fileno())
        require(
            file_identity(before) == file_identity(opened), "input changed before read"
        )
        raw = handle.read(limit + 1)
        after = os.fstat(handle.fileno())
    require(len(raw) <= limit, "input exceeds byte limit")
    require(file_identity(opened) == file_identity(after), "input changed during read")
    require(file_identity(after) == file_identity(path.lstat()), "input path changed")
    return raw


def source_rows(document, directory):
    if directory == FOLLOWUP:
        require(
            document["schema"] == "historical-followup-source-archive-v1",
            "source schema",
        )
        require(
            document["archived_source_executed"] is False
            and document["scientific_or_runtime_acceptance"] is False
            and document["deployment_or_production_activation"] is False,
            "source-only boundary changed",
        )
        require(
            isinstance(document["sources"], list) and document["notices"] == [],
            "source rows",
        )
        items = document["sources"]
        count, size = document["source_count"], document["source_bytes"]
        fields = ("relative_path", "git_blob_sha")
    elif directory == MIXED:
        require(
            document["schema"] == "isolated-frozen-patch-new-file-projection-v1",
            "source schema",
        )
        require(
            document["preserved_source_executed"] is False
            and document["patch_applied"] is False
            and document["new_frozen_candidates_counted"] == 0
            and document["source_candidate_sets_unchanged"] is True
            and document["boundaries"]
            == ["DRAFT", "SHADOW_ONLY", "DENY_ALL", "HOLD_NO_GO"]
            and document["frozen_candidate_count"] == 6116
            and document["formal_verified_count_unchanged"] == 5887,
            "source-only boundary changed",
        )
        require(
            isinstance(document["objects"], list)
            and document["additional_source_object_count"] == 30
            and isinstance(document["notices"], list)
            and len(document["notices"]) == document["auxiliary_notice_count"] == 3,
            "source or notice count",
        )
        for notice in document["notices"]:
            name = canonical(notice["relative_path"])
            require(
                name.startswith("notices/")
                and notice["role"] == "auxiliary original third-party notice"
                and notice["git_blob_sha"] == SNAPSHOTS[MIXED]["controls"].get(name),
                "original notice binding",
            )
        items = document["objects"]
        count, size = (
            document["additional_source_object_count"],
            document["additional_source_bytes"],
        )
        fields = ("relative_path", "git_blob_sha")
    elif directory == UNRESOLVED:
        require(
            document["schema"] == "trillionnium.library-source-custody.v1",
            "source schema",
        )
        require(
            document["disposition"] == "ARCHIVE_ONLY_DRAFT_HOLD"
            and document["safeguards"]["authority"] == "DENY_ALL"
            and document["safeguards"]["product_acceptance"] is False,
            "source-only boundary changed",
        )
        items = document["source_files"]
        count, size = (
            document["counts"]["unique_source_identities"],
            document["counts"]["unique_bytes"],
        )
        fields = ("canonical_repository_path", "git_blob_sha1")
    else:
        raise ValueError("unregistered source collection")
    require(
        isinstance(items, list) and type(count) is int and len(items) == count,
        "source count",
    )
    sources, seen = {}, set()
    for index, row in enumerate(items):
        path = canonical(row[fields[0]])
        if directory in (FOLLOWUP, MIXED):
            path = directory + "/" + path
        require(path.startswith(directory + "/"), "source path escapes collection")
        fingerprint = {
            "oid": row[fields[1]],
            "bytes": row["bytes"],
            "sha256": row["sha256"],
        }
        require(
            path not in sources and fingerprint["oid"] not in seen,
            "duplicate source identity",
        )
        sources[path] = {
            **fingerprint,
            "pointer": {
                FOLLOWUP: "/sources/",
                UNRESOLVED: "/source_files/",
                MIXED: "/objects/",
            }[directory]
            + str(index),
        }
        seen.add(fingerprint["oid"])
    require(
        type(size) is int and sum(x["bytes"] for x in sources.values()) == size,
        "source byte count",
    )
    return sources


def verify_container(repository, directory):
    require(not sys.flags.optimize, "optimized verification refused")
    require(directory in SNAPSHOTS, "unregistered source collection")
    repository = Path(repository)
    registration = SNAPSHOTS[directory]
    manifest_name = registration["manifest"]
    original = read_regular(repository, directory + "/" + manifest_name, MAX_CONTROL)
    require(
        identity(original)["oid"] == registration["controls"][manifest_name],
        "original manifest drift",
    )
    sources = source_rows(
        json.loads(original, object_pairs_hook=unique_object), directory
    )
    raw_index = read_regular(
        repository, directory + "/ARCHIVE_MANIFEST.json", MAX_CONTROL
    )
    index = json.loads(raw_index, object_pairs_hook=unique_object)
    keys = {
        "schema",
        "source_commit",
        "original_directory",
        "archive",
        "archive_bytes",
        "archive_sha256",
        "tar_bytes",
        "tar_sha256",
        "source_count",
        "source_bytes",
        "member_count",
        "member_bytes",
        "members",
        "source_executed",
        "scientific_or_runtime_qualification",
    }
    require(
        isinstance(index, dict) and set(index) == keys, "invalid transport manifest"
    )
    require(
        index["schema"] == SCHEMA and index["source_commit"] == SOURCE_COMMIT,
        "transport source identity",
    )
    require(
        index["original_directory"] == directory
        and index["archive"] == "source-custody.tar.gz",
        "container location",
    )
    require(
        index["source_executed"] is False
        and index["scientific_or_runtime_qualification"] is False,
        "transport qualification boundary",
    )
    for name in ("source_count", "source_bytes", "member_count", "member_bytes"):
        require(
            type(index[name]) is int and 0 <= index[name] <= MAX_TAR,
            "invalid transport count",
        )
    require(
        type(index["archive_bytes"]) is int
        and 0 < index["archive_bytes"] <= MAX_ARCHIVE,
        "container byte limit",
    )
    require(
        type(index["tar_bytes"]) is int and 0 < index["tar_bytes"] <= MAX_TAR,
        "tar byte limit",
    )
    rows = index["members"]
    require(
        isinstance(rows, list)
        and 0 < len(rows) <= 512
        and len(rows) == index["member_count"],
        "member count",
    )
    expected = {}
    for row in rows:
        require(
            isinstance(row, dict)
            and set(row)
            == {
                "path",
                "member",
                "mode",
                "oid",
                "bytes",
                "sha256",
                "role",
                "provenance_pointer",
            },
            "invalid member record",
        )
        name = canonical(row["member"])
        require(
            row["path"] == directory + "/" + name and name not in expected,
            "duplicate or inconsistent member path",
        )
        require(
            row["mode"] == "100644"
            and type(row["bytes"]) is int
            and 0 <= row["bytes"] <= MAX_TAR,
            "member mode or size",
        )
        require(
            isinstance(row["oid"], str) and re.fullmatch(r"[0-9a-f]{40}", row["oid"]),
            "invalid Git identity",
        )
        require(
            isinstance(row["sha256"], str)
            and re.fullmatch(r"[0-9a-f]{64}", row["sha256"]),
            "invalid SHA256",
        )
        if row["role"] == "source":
            require(row["path"] in sources, "unexpected source member")
            source = sources[row["path"]]
            require(
                all(row[k] == source[k] for k in ("oid", "bytes", "sha256"))
                and row["provenance_pointer"] == source["pointer"],
                "source manifest binding",
            )
        else:
            require(
                row["role"] == "prior_control"
                and name in registration["controls"]
                and row["oid"] == registration["controls"][name]
                and row["provenance_pointer"] is None,
                "unexpected or changed original control",
            )
        expected[name] = row
    source_names = {path[len(directory) + 1 :] for path in sources}
    require(
        set(expected) == source_names | set(registration["controls"]),
        "missing or unexpected manifest member",
    )
    require(
        index["source_count"] == len(sources)
        and index["source_bytes"] == sum(x["bytes"] for x in sources.values()),
        "transport source totals",
    )
    require(
        index["member_bytes"] == sum(x["bytes"] for x in expected.values()),
        "transport member totals",
    )
    compressed = read_regular(
        repository, directory + "/" + index["archive"], index["archive_bytes"]
    )
    require(
        len(compressed) == index["archive_bytes"]
        and hashlib.sha256(compressed).hexdigest() == index["archive_sha256"],
        "container size or hash mismatch",
    )
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    raw = decoder.decompress(compressed, index["tar_bytes"] + 1)
    require(
        decoder.eof
        and not decoder.unused_data
        and not decoder.unconsumed_tail
        and len(raw) == index["tar_bytes"],
        "truncated, oversized or concatenated gzip",
    )
    require(hashlib.sha256(raw).hexdigest() == index["tar_sha256"], "tar hash mismatch")
    verified, seen, cursor = {}, set(), 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        require(not archive.pax_headers, "unsupported archive metadata")
        for member in archive:
            name = canonical(member.name)
            require(
                name not in seen and name in expected,
                "duplicate or unexpected tar member",
            )
            row = expected[name]
            require(
                member.type == tarfile.REGTYPE
                and not member.linkname
                and not member.pax_headers,
                "member must be a plain regular file",
            )
            require(
                member.mode == 0o644 and member.size == row["bytes"],
                "tar member mode or size mismatch",
            )
            require(
                member.uid == member.gid == member.mtime == 0
                and not member.uname
                and not member.gname,
                "unsupported tar metadata",
            )
            require(
                member.offset == cursor and member.offset_data == cursor + 512,
                "unexpected tar header",
            )
            handle = archive.extractfile(member)
            require(handle is not None, "missing tar member bytes")
            with handle:
                payload = handle.read(member.size + 1)
            require(
                identity(payload) == {k: row[k] for k in ("bytes", "sha256", "oid")},
                "member identity mismatch",
            )
            if name == manifest_name:
                require(payload == original, "archived source manifest differs")
            if row["role"] == "source":
                verified[row["path"]] = payload
            seen.add(name)
            cursor += 512 + ((member.size + 511) // 512) * 512
    require(seen == set(expected), "missing tar members")
    require(
        len(raw) == ((cursor + 1024 + 10239) // 10240) * 10240
        and not any(raw[cursor:]),
        "noncanonical tar trailer",
    )
    require(set(verified) == set(sources), "missing verified source")
    return verified


def resolve_original_paths(repository, original_paths):
    requested = [canonical(path) for path in original_paths]
    require(len(requested) == len(set(requested)), "duplicate source path request")
    cache, resolved = {}, {}
    for original_path in requested:
        groups = [group for group in SNAPSHOTS if original_path.startswith(group + "/")]
        require(len(groups) == 1, "missing or ambiguous source collection")
        group = groups[0]
        if group not in cache:
            cache[group] = verify_container(repository, group)
        require(original_path in cache[group], "missing original source path")
        resolved[original_path] = cache[group][original_path]
    return resolved


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection", choices=sorted(SNAPSHOTS))
    args = parser.parse_args(argv)
    try:
        sources = verify_container(Path(__file__).resolve().parents[1], args.collection)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        zlib.error,
        tarfile.TarError,
    ) as error:
        print(f"Source custody verification failed: {error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "source_count": len(sources),
                "source_bytes": sum(map(len, sources.values())),
                "notice_count": SNAPSHOTS[args.collection].get("notice_count", 0),
                "all_bytes_match_manifest": True,
                "archived_source_executed": False,
                "research_or_runtime_qualification": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
