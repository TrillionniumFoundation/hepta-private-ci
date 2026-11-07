"""Audit the selected Windows44 packet as inert bytes; never execute payloads."""

import argparse
import hashlib
import io
import json
import lzma
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
import zlib

CANONICAL = Path(
    "/workspace/scratch/3f6a885bb83c/round3_native/access_terminal_checkpoint_inputs/reviewed_restore.py"
)
CANONICAL_SHA = "af61744d776034fb41dac291fbca63d30082c6ec15df821824b49df4678c8d3d"
CANONICAL_API = Path(
    "/dev/shm/ndu_root_continuation_20261107/windows44_packet_canonical_api.json"
)
CANONICAL_API_SHA = "f99f6e85347979bdfb03f161d06908cafe1c75724f9b9ed10d7694105bf1be9a"
HEAD = "883b85f2c0198e9373022e8082d866c080178c0a"
TREE = "6634442bb8fb0bc8b1f86278ff4fffefdaafd23e"
ROSTER_ROOT = "/dev/shm/ndu_windows44_20261107/"
FAILURE_TAILS = (
    "PREPARATION_SPACE_FAILURE.json",
    "source_auto_ci_42352197933/ASSERTION_INITIAL_FAILURE.json",
    "source_auto_ci_42352197933/ASSERTION_SECOND_FAILURE.json",
    "source_auto_ci_42352197933/INITIAL_CAPTURE_TRANSPORT_FAILURE.json",
    "source_auto_ci_42352197933/assertion_values44.py",
    "source_auto_ci_42352197933/assertion_values44_v2.py",
    "review2/manifest.json",
    "review2/from_review1.patch",
)
MAX_FILE = 16 * 1024 * 1024


def require(condition, code):
    if not condition:
        raise ValueError(code)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def size(value, limit):
    require(type(value) is int and 0 <= value <= limit, "INVALID_SIZE")
    return value


def safe_name(name):
    require(type(name) is str and bool(name), "INVALID_PATH")
    require(not any(c in name for c in ("\\", ":", "\0")), "INVALID_PATH")
    path = PurePosixPath(name)
    require(not path.is_absolute() and path.as_posix() == name, "INVALID_PATH")
    require(all(p not in ("", ".", "..") for p in name.split("/")), "INVALID_PATH")
    return name


def read(path, limit=MAX_FILE):
    path = Path(path)
    before = path.lstat()
    require(
        stat.S_ISREG(before.st_mode) and before.st_size <= limit, "INVALID_SOURCE_FILE"
    )
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(fd)
        fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        require(
            all(getattr(before, f) == getattr(opened, f) for f in fields),
            "SOURCE_CHANGED",
        )
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(limit + 1)
        after = os.fstat(fd)
        require(len(data) == before.st_size and len(data) <= limit, "SOURCE_SIZE")
        require(
            all(getattr(before, f) == getattr(after, f) for f in fields),
            "SOURCE_CHANGED",
        )
        require(
            all(getattr(before, f) == getattr(path.lstat(), f) for f in fields),
            "PATH_CHANGED",
        )
    finally:
        os.close(fd)
    return data, before.st_mode


def identity(path, data):
    return {
        "path": str(path),
        "bytes": len(data),
        "sha256": sha(data),
        "git_blob": blob(data),
    }


def pinned(path, expected):
    data, mode = read(path)
    require(sha(data) == expected, "INPUT_PIN_MISMATCH")
    return json.loads(data), data, mode


def decode(index, package):
    chunks, names = [], set()
    require(
        type(index["parts"]) is list and 0 < len(index["parts"]) <= 160, "PART_COUNT"
    )
    for part in index["parts"]:
        name = part["name"]
        require(
            re.fullmatch(r"native-evidence\.tar\.xz\.part[0-9]{3}\.gz", name)
            and name not in names,
            "PART_NAME",
        )
        names.add(name)
        raw, _ = read(package / name, 450000)
        require(
            len(raw) == size(part["bytes"], 450000) and sha(raw) == part["sha256"],
            "PART_IDENTITY",
        )
        count = size(part["segment_bytes"], 440000)
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        segment = decoder.decompress(raw, count + 1)
        require(
            decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail,
            "NOT_SINGLE_GZIP",
        )
        require(
            len(segment) == count and sha(segment) == part["segment_sha256"],
            "SEGMENT_IDENTITY",
        )
        chunks.append(segment)
    compressed = b"".join(chunks)
    require(
        len(compressed) == size(index["compressed_bytes"], 64 * 1024 * 1024)
        and sha(compressed) == index["compressed_sha256"],
        "XZ_IDENTITY",
    )
    count = size(index["archive_bytes"], 256 * 1024 * 1024)
    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_XZ, memlimit=128 * 1024 * 1024)
    raw_tar = decoder.decompress(compressed, max_length=count + 1)
    require(
        decoder.eof and not decoder.unused_data and len(raw_tar) == count,
        "NOT_SINGLE_BOUNDED_XZ",
    )
    require(sha(raw_tar) == index["archive_sha256"], "TAR_IDENTITY")
    return raw_tar, names


def check_reader(package, index_sha):
    canonical, _ = read(CANONICAL)
    require(sha(canonical) == CANONICAL_SHA, "CANONICAL_READER_PIN")
    api, api_raw, _ = pinned(CANONICAL_API, CANONICAL_API_SHA)
    require(
        api["main"] == 5282
        and api["head"] == "46f900f0aefd13b797e56282f536882186c97c93",
        "CANONICAL_API_SOURCE",
    )
    require(len(api["leaves"]) == 1, "CANONICAL_API_LEAF_COUNT")
    leaf = next(iter(api["leaves"].values()))
    require(
        (leaf["sha"], leaf["size"], leaf["type"], leaf["mode"])
        == (blob(canonical), len(canonical), "blob", "100644"),
        "CANONICAL_REMOTE_LEAF",
    )
    current, _ = read(package / "restore.py")
    pattern = rb'EXPECTED_INDEX_SHA256 = \(\n    "([a-f0-9]{64})"\n\)'
    old, new = (
        list(re.finditer(pattern, canonical)),
        list(re.finditer(pattern, current)),
    )
    require(len(old) == len(new) == 1, "READER_SEAL_COUNT")
    require(new[0].group(1) == index_sha.encode(), "READER_SEAL")
    require(current.count(new[0].group(1)) == 1, "READER_SEAL_ALIAS")
    require(
        current.replace(new[0].group(1), old[0].group(1)) == canonical,
        "READER_NOT_SEAL_ONLY",
    )
    return {
        "local": identity(CANONICAL, canonical),
        "root_fresh_api": identity(CANONICAL_API, api_raw),
        "remote_blob": leaf["sha"],
    }


def audit(args):
    publication, publication_raw, _ = pinned(args.manifest, args.manifest_sha)
    roster, roster_raw, _ = pinned(args.roster, args.roster_sha)
    require(
        (
            roster["native_head"],
            roster["native_tree"],
            roster["run"],
            roster["attempt"],
            roster["job"],
        )
        == (HEAD, TREE, 42352197933, 1, 128343024490),
        "NATIVE_BINDING",
    )
    require(
        roster["private_console_exported"] is False
        and publication["remote_mutations_performed"] is False,
        "PUBLICATION_SCOPE",
    )
    files = publication["files"]
    require(
        len(files) == 9 and len({r["path"] for r in files}) == 9, "PUBLICATION_MEMBERS"
    )
    index_row = next(r for r in files if r["path"].endswith("/INDEX.json"))
    package = Path(index_row["local_path"]).parent
    index, index_raw, _ = pinned(index_row["local_path"], publication["index_sha256"])
    require(
        index["format"] == "native-blocker-evidence-v1"
        and index["input_roster_sha256"] == sha(roster_raw),
        "INDEX_ROSTER",
    )
    retained = {str(args.manifest): publication_raw, str(args.roster): roster_raw}
    pub_bytes = {}
    for row in files:
        relative = row["path"].removeprefix(publication["repo_directory"] + "/")
        require(relative != row["path"], "PUBLICATION_PREFIX")
        safe_name(relative)
        raw, mode = read(row["local_path"])
        require(
            (len(raw), sha(raw), blob(raw), format(mode, "o"))
            == (row["bytes"], row["sha256"], row["git_blob_sha"], row["mode"]),
            "PUBLICATION_IDENTITY",
        )
        require(mode == stat.S_IFREG | 0o644, "PUBLICATION_MODE")
        require(
            row["encoding"] == ("base64" if relative.endswith(".gz") else "utf-8"),
            "PUBLICATION_ENCODING",
        )
        if row["encoding"] == "utf-8":
            raw.decode("utf-8")
        retained[row["local_path"]] = raw
        pub_bytes[relative] = raw
    canonical = check_reader(package, sha(index_raw))
    retained[str(CANONICAL)] = read(CANONICAL)[0]
    retained[str(CANONICAL_API)] = read(CANONICAL_API)[0]
    plain = roster["separate_plain_publication"]
    private = roster["excluded_private_identity_only"]
    omitted = roster["omitted_implementation_identity_only"]
    require(
        len(plain) == 6 and len(private) == 2 and len(omitted) == 3, "EXCLUSION_COUNTS"
    )
    require(
        index["plain_source_references"] == plain
        and index["excluded"] == private
        and index["identity_only_audit_implementations"] == omitted,
        "EXCLUSION_METADATA",
    )
    require(
        index["published_plain_algorithm_PRs"]
        == publication["published_plain_algorithms"]
        == [5279, 5280],
        "PLAIN_PR_BINDING",
    )
    plain_bytes = {}
    for row in plain:
        raw, mode = read(row["source_path"])
        require(
            (len(raw), sha(raw), blob(raw), format(mode & 0o7777, "04o"))
            == (row["bytes"], row["sha256"], row["git_blob"], row["mode"]),
            "PLAIN_IDENTITY",
        )
        require(len(raw.splitlines()) == row["lines"], "PLAIN_LINES")
        plain_bytes[row["source_path"]] = raw
        retained[row["source_path"]] = raw
    excluded_paths = {r["source_path"] for r in private + plain + omitted}
    entries, originals = {}, {}
    for row in roster["packet_files"]:
        name, source = safe_name(row["archive_name"]), row["source_path"]
        require(
            name not in originals
            and source not in {r["source_path"] for r in originals.values()},
            "DUPLICATE_ROSTER",
        )
        require(
            source not in excluded_paths
            and Path(source).suffix.lower() not in (".zip", ".log"),
            "EXCLUDED_SOURCE_PATH",
        )
        require(
            not any(
                (row["bytes"], row["sha256"]) == (r["bytes"], r["sha256"])
                for r in private + omitted
            ),
            "EXCLUDED_SOURCE_IDENTITY",
        )
        originals[name] = row
    for row in index["files"]:
        name = safe_name(row["path"])
        require(name in originals and name not in entries, "INDEX_MEMBERSHIP")
        origin = originals[name]
        require(
            (
                row["source_path"],
                row["bytes"],
                row["sha256"],
                row["source_permission_bits"],
                row["source_stat_mode"],
            )
            == (
                origin["source_path"],
                origin["bytes"],
                origin["sha256"],
                "0644",
                "100644",
            ),
            "INDEX_SOURCE_MAPPING",
        )
        require(origin["mode"] == "0644", "ROSTER_MODE")
        entries[name] = row
    require(
        set(entries) == set(originals) and len(entries) == args.expected_files,
        "EXACT_ROSTER",
    )
    for name in entries:
        require(
            not any(str(parent) in entries for parent in PurePosixPath(name).parents),
            "PARENT_FILE_CONFLICT",
        )
    raw_tar, parts = decode(index, package)
    expected_names = {
        "INDEX.json",
        "restore.py",
        "CODESPELL.json",
        "README.md",
        "READER_CHECK.json",
        "ROUNDTRIP.json",
    } | parts
    require(
        {p.name for p in package.iterdir()} == expected_names,
        "PHYSICAL_PACKAGE_MEMBERS",
    )
    require(
        set(pub_bytes)
        == expected_names
        | {"analysis/bind_call_chain45.py", "analysis/CALL_CHAIN_AND_NEXT_UNIT.md"},
        "PUBLICATION_SET",
    )
    recovered, alias_findings = {}, []
    with tarfile.open(fileobj=io.BytesIO(raw_tar), mode="r:") as archive:
        for member in archive:
            name = safe_name(member.name)
            require(
                member.isreg() and not member.linkname and member.mode == 0o644,
                "NONREGULAR_TAR_MEMBER",
            )
            require(name in entries and name not in recovered, "TAR_MEMBER_SET")
            entry, origin = entries[name], originals[name]
            require(member.size == size(entry["bytes"], MAX_FILE), "TAR_MEMBER_SIZE")
            stream = archive.extractfile(member)
            require(stream is not None, "TAR_MEMBER_READ")
            data = stream.read(member.size + 1)
            require(
                len(data) == member.size
                and sha(data) == entry["sha256"]
                and blob(data) == origin["git_blob"],
                "TAR_MEMBER_IDENTITY",
            )
            source_raw, mode = read(entry["source_path"])
            require(
                data == source_raw and mode == stat.S_IFREG | 0o644,
                "ORIGINAL_BYTES_OR_MODE",
            )
            for plain_path, plain_raw in plain_bytes.items():
                if (
                    len(data) == len(plain_raw)
                    and sha(data) == sha(plain_raw)
                    and data == plain_raw
                ):
                    alias_findings.append(
                        {
                            "member": name,
                            "source_path": entry["source_path"],
                            "plain_source_path": plain_path,
                            "bytes": len(data),
                            "sha256": sha(data),
                        }
                    )
            require(
                not any(
                    len(data) == r["bytes"] and sha(data) == r["sha256"]
                    for r in private + omitted
                ),
                "EXCLUDED_BYTE_IDENTITY",
            )
            recovered[name] = data
            retained[entry["source_path"]] = source_raw
    require(set(recovered) == set(entries), "INCOMPLETE_TAR")
    count, total = len(recovered), sum(len(v) for v in recovered.values())
    require(
        (count, total)
        == (args.expected_files, args.expected_bytes)
        == (roster["packet_original_count"], roster["packet_original_bytes"])
        == (publication["original_files"], publication["original_bytes"]),
        "TOTALS",
    )
    paths = {r["source_path"] for r in originals.values()}
    failures = {ROSTER_ROOT + tail for tail in FAILURE_TAILS}
    failures.add(
        "/workspace/scratch/3f6a885bb83c/round3_native/windows_mutation_deny_44/review1/SELF_REVIEW_FINDING.json"
    )
    failures.add(
        "/dev/shm/ndu_root_continuation_20261107/windows44_source_reviewer_initial_ruff.json"
    )
    require(failures <= paths, "FAILURE_HISTORY_OMITTED")
    lines = sum(
        len(pub_bytes[n].splitlines())
        for n in (
            "restore.py",
            "README.md",
            "analysis/bind_call_chain45.py",
            "analysis/CALL_CHAIN_AND_NEXT_UNIT.md",
        )
    )
    require(
        lines == publication["nonmechanical_publication_lines"] <= 800,
        "PUBLICATION_LINES",
    )
    for path, before in retained.items():
        after, _ = read(path)
        require(after == before, "INPUT_CHANGED_DURING_AUDIT")
    return {
        "schema": "windows44-independent-packet-custody-review-v1",
        "decision": "FAIL_PLAIN_SOURCE_BYTE_ALIAS"
        if alias_findings
        else "PASS_SELECTED_SAFE_BYTE_CUSTODY",
        "publication": identity(args.manifest, publication_raw),
        "roster": identity(args.roster, roster_raw),
        "index": identity(package / "INDEX.json", index_raw),
        "canonical_reader": canonical,
        "canonical_reader_only_index_seal_changed": True,
        "files": count,
        "bytes": total,
        "exact_member_original_bytes_and_0644_modes": True,
        "single_bounded_gzip_members": len(parts),
        "single_bounded_xz_and_tar_hashes_verified": True,
        "publication_files": len(files),
        "publication_nonmechanical_lines": lines,
        "private_inputs_identity_only_never_read": private,
        "six_plain_source_paths_excluded": True,
        "six_plain_source_bytes_excluded": not alias_findings,
        "plain_byte_alias_findings": alias_findings,
        "three_historical_implementations_identity_only": omitted,
        "required_failure_history_present": sorted(failures),
        "inputs_byte_identical_when_reread": len(retained),
        "new_native_or_case_qualification": False,
        "payload_import_execution_or_filesystem_restore": False,
        "private_console_or_execution_zip_read": False,
        "P0_or_old_ACL_migration_closed": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "roster", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("manifest-sha", "roster-sha"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--expected-files", type=int, required=True)
    parser.add_argument("--expected-bytes", type=int, required=True)
    args = parser.parse_args()
    require(not args.output.exists() and not args.output.is_symlink(), "OUTPUT_EXISTS")
    result = audit(args)
    with args.output.open("x") as output:
        json.dump(result, output, indent=2)
        output.write("\n")
    print(result["decision"])
    if result["plain_byte_alias_findings"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
