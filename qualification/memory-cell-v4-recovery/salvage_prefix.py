"""Salvage complete Git objects from a truncated bundle; never claim full recovery."""

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import time
import zlib


CONTROL = Path(__file__).resolve().parent
FINAL = "3c509f9bb9a9724cddbe6a917c728e022582fefe"
SOURCE = "6206dfba0a3219534dd1a0274431bf48fd23673c"
FULL_BYTES = 217549454
FULL_SHA256 = "9e5f6702eea7a0e9679885323278e61f8f08f8237c655220ecaf81e88d2fda93"
HEX40 = re.compile(r"[0-9a-f]{40}\Z")


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=True, indent=2, sort_keys=True)
        stream.write("\n")


def clean_environment():
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_OPTIONAL_LOCKS="0",
        GIT_TERMINAL_PROMPT="0",
        LC_ALL="C",
    )
    return env


def file_identity(path):
    size = path.stat().st_size
    sha256 = hashlib.sha256()
    blob = hashlib.sha1(b"blob " + str(size).encode() + b"\0")
    with path.open("rb") as stream:
        while block := stream.read(1048576):
            sha256.update(block)
            blob.update(block)
    return {"bytes": size, "sha256": sha256.hexdigest(), "git_blob_sha1": blob.hexdigest()}


def assemble(parts, output, expected_sha256, expected_blobs):
    if expected_sha256 and len(expected_sha256) != len(parts):
        raise ValueError("expected part SHA-256 count differs from input count")
    if expected_blobs and len(expected_blobs) != len(parts):
        raise ValueError("expected part Git blob count differs from input count")
    records = []
    destination = output / "input-prefix.bundle.truncated"
    with destination.open("xb") as combined:
        for index, path in enumerate(parts):
            expected_size = path.stat().st_size
            sha256 = hashlib.sha256()
            blob = hashlib.sha1(b"blob " + str(expected_size).encode() + b"\0")
            copied = 0
            with path.open("rb") as source:
                while block := source.read(1048576):
                    copied += len(block)
                    sha256.update(block)
                    blob.update(block)
                    combined.write(block)
            if copied != expected_size:
                raise ValueError(f"input changed size while copied: {path}")
            identity = {"bytes": copied, "sha256": sha256.hexdigest(), "git_blob_sha1": blob.hexdigest()}
            if expected_sha256 and identity["sha256"] != expected_sha256[index]:
                raise ValueError(f"input part SHA-256 mismatch: {path}")
            if expected_blobs and identity["git_blob_sha1"] != expected_blobs[index]:
                raise ValueError(f"input part Git blob mismatch: {path}")
            records.append({"index": index + 1, "path": str(path), **identity})
    return destination, records


def extract_pack(prefix, output, expected_advertised):
    with prefix.open("rb") as stream:
        signature = stream.readline(1024)
        if signature not in (b"# v2 git bundle\n", b"# v3 git bundle\n"):
            raise ValueError("input does not start with a supported Git bundle signature")
        lines = [signature]
        references, prerequisites, capabilities = [], [], []
        for _ in range(10000):
            line = stream.readline(65536)
            if not line or not line.endswith(b"\n"):
                raise ValueError("bundle header is incomplete")
            lines.append(line)
            if line == b"\n":
                break
            value = line[:-1].decode("utf-8")
            if value.startswith("@"):
                capabilities.append(value[1:])
                if value != "@object-format=sha1":
                    raise ValueError(f"unsupported bundle capability: {value}")
            elif value.startswith("-"):
                oid, _, description = value[1:].partition(" ")
                if not HEX40.fullmatch(oid):
                    raise ValueError("invalid prerequisite object ID")
                prerequisites.append({"oid": oid, "description": description})
            else:
                oid, separator, ref = value.partition(" ")
                if not separator or not HEX40.fullmatch(oid):
                    raise ValueError("invalid advertised reference")
                references.append({"oid": oid, "ref": ref})
        else:
            raise ValueError("bundle header exceeds bounded line count")
        offset = stream.tell()
        if expected_advertised not in {item["oid"] for item in references}:
            raise ValueError("expected original commit is not advertised by this header")
        header = stream.read(12)
        if len(header) != 12 or header[:4] != b"PACK":
            raise ValueError("complete PACK header unavailable")
        version, object_count = struct.unpack(">II", header[4:])
        if version not in (2, 3):
            raise ValueError("unsupported PACK version")
        with (output / "pack-prefix.pack").open("xb") as destination:
            destination.write(header)
            shutil.copyfileobj(stream, destination, length=1048576)
    (output / "bundle-header.txt").write_bytes(b"".join(lines))
    return {
        "signature": signature.decode().strip(),
        "capabilities": capabilities,
        "prerequisites": prerequisites,
        "advertised_references": references,
        "pack_offset_in_bundle": offset,
        "pack_version": version,
        "declared_pack_objects": object_count,
    }


def loose_inventory(git_dir):
    valid, invalid = [], []
    for path in sorted((git_dir / "objects").glob("[0-9a-f][0-9a-f]/*")):
        oid = path.parent.name + path.name
        if not path.is_file() or not HEX40.fullmatch(oid):
            continue
        try:
            decoder = zlib.decompressobj()
            content_hash, object_hash = hashlib.sha256(), hashlib.sha1()
            prefix, total, kind, size = b"", 0, None, None
            with path.open("rb") as source:
                while block := source.read(65536):
                    data = decoder.decompress(block)
                    object_hash.update(data)
                    if kind is None:
                        prefix += data
                        if b"\0" not in prefix:
                            if len(prefix) > 100:
                                raise ValueError("oversized loose header")
                            continue
                        header, data = prefix.split(b"\0", 1)
                        kind_raw, size_raw = header.split(b" ")
                        kind, size = kind_raw.decode(), int(size_raw)
                        prefix = b""
                    total += len(data)
                    content_hash.update(data)
            if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                raise ValueError("incomplete or trailing loose compressed stream")
            if kind not in {"commit", "tree", "blob", "tag"} or total != size:
                raise ValueError("invalid loose type or size")
            if object_hash.hexdigest() != oid:
                raise ValueError("loose object SHA-1 mismatch")
            valid.append({"oid": oid, "type": kind, "bytes": size, "content_sha256": content_hash.hexdigest()})
        except (ValueError, zlib.error) as error:
            invalid.append({"oid": oid, "error": str(error)})
    return valid, invalid


class ObjectReader:
    def __init__(self, git_dir, env, limit):
        self.limit = limit
        self.process = subprocess.Popen(
            ["git", "--git-dir", str(git_dir), "cat-file", "--batch"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
        )

    def read(self, oid):
        if not HEX40.fullmatch(oid):
            raise ValueError("invalid requested object ID")
        self.process.stdin.write(oid.encode() + b"\n")
        self.process.stdin.flush()
        header = self.process.stdout.readline().decode().strip().split()
        if header == [oid, "missing"]:
            return None, None, "missing"
        if len(header) != 3 or header[0] != oid:
            raise ValueError(f"invalid cat-file response for {oid}")
        size, kind = int(header[2]), header[1]
        remaining, blocks = size, []
        while remaining:
            block = self.process.stdout.read(min(remaining, 1048576))
            if not block:
                raise ValueError("truncated cat-file output")
            remaining -= len(block)
            if size <= self.limit:
                blocks.append(block)
        if self.process.stdout.read(1) != b"\n":
            raise ValueError("missing cat-file object terminator")
        if size > self.limit:
            return kind, None, f"object_above_read_limit:{size}"
        data = b"".join(blocks)
        if hashlib.sha1(f"{kind} {size}\0".encode() + data).hexdigest() != oid:
            raise ValueError(f"cat-file SHA-1 mismatch: {oid}")
        return kind, data, None

    def close(self):
        self.process.stdin.close()
        self.process.stdout.close()
        if self.process.wait(timeout=30) != 0:
            raise ValueError("cat-file subprocess failed")


def tree_entries(data):
    offset, names = 0, set()
    while offset < len(data):
        end = data.index(b"\0", offset)
        raw_mode, raw_name = data[offset:end].split(b" ", 1)
        name = raw_name.decode("utf-8")
        if name in {"", ".", ".."} or "/" in name or name in names:
            raise ValueError("unsafe or duplicate tree entry")
        names.add(name)
        if end + 21 > len(data):
            raise ValueError("truncated tree entry")
        yield raw_mode.decode(), name, data[end + 1:end + 21].hex()
        offset = end + 21


def export_commit(reader, commit, includes, destination, local_oids):
    result = {"commit": commit, "files": [], "missing": [], "skipped": [], "full_tree_recovered": False, "requested_prefixes": includes}
    kind, data, failure = reader.read(commit)
    if failure or kind != "commit":
        result["missing"].append({"path": "", "oid": commit, "reason": failure or "not_commit"})
        return result
    first = data.split(b"\n", 1)[0]
    if not first.startswith(b"tree "):
        raise ValueError("commit has no leading tree")
    root_tree = first[5:].decode()
    result["commit_content_sha256"] = hashlib.sha256(data).hexdigest()
    result["tree_oid"] = root_tree
    destination.mkdir()
    (destination / "COMMIT.object").write_bytes(data)
    stack, reached = [("", root_tree, "40000")], set()
    while stack:
        relative, oid, mode = stack.pop()
        relevant = any(not relative or relative == inc or relative.startswith(inc + "/") or inc.startswith(relative + "/") for inc in includes)
        if not relevant:
            continue
        if relative in includes:
            reached.add(relative)
        expected_kind = "tree" if mode in {"40000", "040000"} else "blob"
        if mode not in {"40000", "040000", "100644", "100755", "120000"}:
            result["skipped"].append({"path": relative, "oid": oid, "mode": mode})
            continue
        kind, content, failure = reader.read(oid)
        if failure or kind != expected_kind:
            result["missing"].append({"path": relative, "oid": oid, "mode": mode, "reason": failure or "type_mismatch"})
            continue
        if kind == "tree":
            for child_mode, name, child_oid in reversed(list(tree_entries(content))):
                stack.append((f"{relative}/{name}".lstrip("/"), child_oid, child_mode))
        else:
            path = destination / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(content)
            result["files"].append({
                "path": relative, "oid": oid, "mode": mode, "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "object_origin": "recovered_loose" if oid in local_oids else "read_only_base_alternate",
                "symlink_materialized_as_regular_bytes": mode == "120000",
            })
    result["unmatched_prefixes"] = sorted(set(includes) - reached)
    result["requested_subtrees_complete"] = not result["missing"] and not result["skipped"] and not result["unmatched_prefixes"]
    result["exported_files"] = len(result["files"])
    result["exported_bytes"] = sum(item["bytes"] for item in result["files"])
    return result


def recover(args, output, receipt):
    env = clean_environment()
    receipt["git_version"] = subprocess.check_output(["git", "--version"], env=env, text=True).strip()
    prefix, parts = assemble(args.part, output, args.expected_part_sha256, args.expected_part_blob)
    identity = file_identity(prefix)
    receipt.update(input_parts=parts, input_prefix=identity)
    receipt["full_bundle_identity_verified"] = identity["bytes"] == args.expected_full_bytes and identity["sha256"] == args.expected_full_sha256
    if identity["bytes"] > args.expected_full_bytes:
        raise ValueError("provided prefix exceeds expected full bundle size")
    receipt["bundle_header"] = extract_pack(prefix, output, args.expected_advertised_commit)
    git_dir = output / "salvaged-objects.git"
    subprocess.run(["git", "init", "--bare", "--quiet", "--template=", "--object-format=sha1", str(git_dir)], env=env, check=True)
    bases = []
    for base in args.base_repo:
        objdir = subprocess.check_output(["git", "-C", str(base), "rev-parse", "--path-format=absolute", "--git-path", "objects"], env=env, text=True).strip()
        if "\n" in objdir or not Path(objdir).is_dir():
            raise ValueError("invalid base repository object directory")
        bases.append({"repository": str(base), "objects": objdir})
    if bases:
        (git_dir / "objects/info/alternates").write_text("".join(item["objects"] + "\n" for item in bases))
    receipt["read_only_base_repositories"] = bases
    with (output / "pack-prefix.pack").open("rb") as source, (output / "unpack.stdout").open("xb") as stdout, (output / "unpack.stderr").open("xb") as stderr:
        completed = subprocess.run(["git", "--git-dir", str(git_dir), "unpack-objects", "-r", "-q"], stdin=source, stdout=stdout, stderr=stderr, env=env, timeout=args.unpack_timeout)
    receipt["unpack_returncode"] = completed.returncode
    receipt["unpack_nonzero_does_not_invalidate_individually_verified_objects"] = True
    valid, invalid = loose_inventory(git_dir)
    write_json(output / "object-inventory.json", {"valid": valid, "invalid": invalid})
    receipt["new_valid_loose_objects"] = len(valid)
    receipt["new_objects_by_type"] = dict(Counter(item["type"] for item in valid))
    receipt["invalid_loose_objects"] = invalid
    if invalid:
        raise ValueError("invalid loose objects found; no file export attempted")
    reader = ObjectReader(git_dir, env, args.max_object_bytes)
    try:
        exports = []
        for commit in args.commit or [FINAL, SOURCE]:
            report = export_commit(reader, commit, args.include or ["qualification/memory-cell-v4"], output / ("commit-" + commit), {item["oid"] for item in valid})
            write_json(output / ("export-" + commit + ".json"), report)
            exports.append({key: value for key, value in report.items() if key not in {"files", "missing", "skipped"}} | {"missing_count": len(report["missing"]), "skipped_count": len(report["skipped"])})
        receipt["exports"] = exports
    finally:
        reader.close()
    receipt["control_completed"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-part-sha256", action="append", default=[])
    parser.add_argument("--expected-part-blob", action="append", default=[])
    parser.add_argument("--expected-full-bytes", type=int, default=FULL_BYTES)
    parser.add_argument("--expected-full-sha256", default=FULL_SHA256)
    parser.add_argument("--expected-advertised-commit", default=FINAL)
    parser.add_argument("--commit", action="append")
    parser.add_argument("--include", action="append")
    parser.add_argument("--base-repo", action="append", type=Path, default=[])
    parser.add_argument("--max-object-bytes", type=int, default=536870912)
    parser.add_argument("--unpack-timeout", type=int, default=300)
    args = parser.parse_args()
    output = args.output.absolute()
    if output.exists() or output.is_symlink() or not output.resolve().is_relative_to(CONTROL):
        parser.error("output must be a new path inside this recovery control directory")
    for prefix in args.include or []:
        if not prefix or any(part in {"", ".", ".."} for part in prefix.split("/")):
            parser.error("include prefixes must be clean relative Git paths")
    output.mkdir(parents=True)
    started = time.monotonic()
    receipt = {
        "schema": "hepta.partial-bundle-recovery.v1", "partial_recovery_only": True,
        "control_completed": False, "original_results_recreated": False,
        "full_bundle_identity_verified": False, "full_pack_checksum_verified": False,
        "formal_evidence_verified": False, "published_research_refs_created": False,
        "control_script": {"path": str(Path(__file__).resolve()), **file_identity(Path(__file__))},
        "python_version": sys.version,
        "expected_part_sha256": args.expected_part_sha256,
        "expected_part_git_blobs": args.expected_part_blob,
        "expected_full_bundle": {"bytes": args.expected_full_bytes, "sha256": args.expected_full_sha256},
        "limits": ["Absent pack suffix is not reconstructed.", "Missing delta bases may prevent otherwise complete entries from resolving.", "A commit object alone does not establish availability of its entire tree or parents.", "Only complete objects independently hashed and located through the requested original commit tree are exported.", "No original training, result generation, or qualification gate is rerun."],
    }
    try:
        recover(args, output, receipt)
    except Exception as error:
        receipt["failure"] = {"type": type(error).__name__, "message": str(error)}
    receipt["elapsed_seconds"] = time.monotonic() - started
    write_json(output / "RECOVERY.json", receipt)
    print(json.dumps({"output": str(output), **receipt}, indent=2, sort_keys=True))
    return 0 if receipt["control_completed"] else 2


if __name__ == "__main__":
    sys.exit(main())
