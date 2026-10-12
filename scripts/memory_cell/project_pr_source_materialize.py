"""Acquire the original Git code bytes for the precommitted project cohort.

This is research evidence acquisition, NOT gold labels, a trained model,
independent review, an authenticated historical PR discussion or production use.
All remote object identities are pinned before fetching. A partial download
cannot publish READY. Retrieved source is untrusted data, never instructions.
"""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from project_pr_source_precommit import CUT, PARTITIONS, read_pinned, timestamp

MAX_BLOB = 1024 * 1024
MAX_TOTAL = 24 * 1024 * 1024
MAX_REQUESTS = 512
MAX_TREE_BYTES = 6 * 1024 * 1024
SHA1 = re.compile(r"[a-f0-9]{40}\Z")


def strict_json(data):
    """Reject ambiguous HTTP metadata, duplicate fields and nonfinite numbers."""
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError("duplicate GitHub API JSON property")
            out[key] = value
        return out

    def invalid(value):
        raise ValueError("nonfinite GitHub API JSON number: " + value)

    return json.loads(data, object_pairs_hook=pairs, parse_constant=invalid)


def blob_sha(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def check_sha(sha):
    if type(sha) is not str or SHA1.fullmatch(sha) is None:
        raise ValueError("invalid registered Git object ID")
    return sha


def github_json(repo, category, oid, *, token=None):
    """Only generated allowlisted Git-object endpoints, never arbitrary URLs."""
    if repo not in PARTITIONS or category not in ("commits", "trees", "blobs"):
        raise ValueError("unregistered Git object request")
    oid = check_sha(oid)
    url = f"https://api.github.com/repos/{repo}/git/{category}/{oid}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "hepta-memory-source-cut/1"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = Request(url, headers=headers)
    limit = MAX_TREE_BYTES if category == "trees" else 2 * MAX_BLOB + 32768
    try:
        with urlopen(request, timeout=30) as response:
            if response.status != 200:
                raise ValueError("non-success immutable Git object fetch")
            raw = response.read(limit + 1)
    except (HTTPError, URLError) as exc:
        raise ValueError("original Git object unavailable; snapshot incomplete") from exc
    if not raw or len(raw) > limit:
        raise ValueError("GitHub object response exceeds research acquisition bound")
    obj = strict_json(raw.decode("utf-8"))
    if not isinstance(obj, dict) or obj.get("sha") != oid:
        raise ValueError("unexpected Git object identity")
    return obj


class ObjectReader:
    """Immutable Git object client with count and tree-cache bounds."""

    def __init__(self, fetch, *, request_limit=MAX_REQUESTS):
        if type(request_limit) is not int or not 1 <= request_limit <= MAX_REQUESTS:
            raise ValueError("invalid Git object request limit")
        self.fetch = fetch
        self.limit = request_limit
        self.cache = {}
        self.count = 0

    def get(self, repo, category, oid):
        key = (repo, category, check_sha(oid))
        if key not in self.cache:
            if self.count >= self.limit:
                raise ValueError("remote Git request limit reached; snapshot incomplete")
            self.count += 1
            obj = self.fetch(*key)
            if not isinstance(obj, dict) or obj.get("sha") != oid:
                raise ValueError("remote Git identity differs from precommitted SHA")
            self.cache[key] = obj
        return self.cache[key]


def verify_head(row, reader):
    repo, head = row["repo"], check_sha(row["head_sha"])
    commit = reader.get(repo, "commits", head)
    if (
        commit.get("tree", {}).get("sha") != row["tree_sha"]
        or [p.get("sha") for p in commit.get("parents", [])] != row["parents"]
    ):
        raise ValueError("frozen Git head does not bind recorded tree and parents")
    # A backdated Git author timestamp cannot move a later committed HEAD
    # into a source-only cohort. The *committer* clock is what the sealed
    # head_committed_at field records; author and committer are distinct.
    try:
        authored = timestamp(commit["author"]["date"])
        committed = timestamp(commit["committer"]["date"])
        declared = timestamp(row["head_committed_at"])
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise ValueError("missing or invalid pinned Git commit dates") from exc
    if authored > timestamp(CUT) or committed > timestamp(CUT) or committed != declared:
        raise ValueError("frozen head committer date differs from the precommitted cut")


def bind_path(row, file, reader):
    """Walk an exact pinned tree; do not use moving branches or PR endpoints."""
    path = file["path"]
    if not isinstance(path, str) or not path or any(x in ("", ".", "..") for x in path.split("/")):
        raise ValueError("unsafe original path")
    repo, tree_sha = row["repo"], check_sha(row["tree_sha"])
    components = path.split("/")
    for index, component in enumerate(components):
        tree = reader.get(repo, "trees", tree_sha)
        if tree.get("truncated") is not False or not isinstance(tree.get("tree"), list) or len(tree["tree"]) > 10000:
            raise ValueError("unbounded or truncated original Git tree")
        entries = [e for e in tree["tree"] if e.get("path") == component]
        if len(entries) != 1:
            raise ValueError("path absent or ambiguous in committed original tree")
        entry = entries[0]
        if index < len(components) - 1:
            if entry.get("type") != "tree" or entry.get("mode") != "040000":
                raise ValueError("original path traverses non-directory")
            tree_sha = check_sha(entry.get("sha"))
        elif (
            entry.get("type") != "blob"
            or entry.get("mode") not in ("100644", "100755")
            or entry.get("sha") != file["blob_sha"]
        ):
            raise ValueError("file path, executable mode or SHA differs from frozen tree")
    return entry["mode"]


def decode_blob(obj, expected):
    if obj.get("sha") != expected or obj.get("encoding") != "base64":
        raise ValueError("unregistered Git blob representation")
    length = obj.get("size")
    if type(length) is not int or not 0 <= length <= MAX_BLOB:
        raise ValueError("oversized or missing original Git blob size")
    content = obj.get("content")
    if type(content) is not str or len(content) > 2 * MAX_BLOB + 16:
        raise ValueError("unbounded Git blob envelope")
    try:
        raw = base64.b64decode(content.replace("\n", "").encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise ValueError("corrupted base64 Git object") from exc
    if len(raw) != length or blob_sha(raw) != expected:
        raise ValueError("downloaded bytes fail original Git blob hash")
    return raw


def atomic_json(path, obj):
    with path.open("xb") as file:
        file.write(canonical(obj) + b"\n")
        file.flush()
        os.fsync(file.fileno())


def collect(manifest, out, *, manifest_sha, fetch, max_total=MAX_TOTAL):
    """Only publish READY after ALL eight PR trees and ALL source blobs match."""
    if type(max_total) is not int or not 1 <= max_total <= MAX_TOTAL:
        raise ValueError("unregistered original-source byte limit")
    if out.exists() or manifest.get("model_executions") != 0 or manifest.get("no_answers_or_labels") is not True:
        raise ValueError("output must be new and source cut must contain no answer or model execution")
    reader = ObjectReader(fetch)
    out.mkdir(parents=True, exist_ok=False)
    originals = out / "blobs"
    originals.mkdir()
    total = 0
    files = []
    blobs = {}
    try:
        for row in manifest["cases"]:
            verify_head(row, reader)
            for file in row["files"]:
                mode = bind_path(row, file, reader)
                oid = check_sha(file["blob_sha"])
                if oid not in blobs:
                    obj = reader.get(row["repo"], "blobs", oid)
                    raw = decode_blob(obj, oid)
                    if total + len(raw) > max_total:
                        raise ValueError("cumulative original-source byte bound exceeded")
                    total += len(raw)
                    location = originals / (oid + ".blob")
                    with location.open("xb") as stream:
                        stream.write(raw)
                        stream.flush()
                        os.fsync(stream.fileno())
                    blobs[oid] = dict(sha256=digest(raw), bytes=len(raw), blob_path="blobs/" + oid + ".blob")
                files.append(dict(
                    project=row["repo"], partition=row["partition"],
                    pull_number=row["pull_number"], head_sha=row["head_sha"],
                    tree_sha=row["tree_sha"], path=file["path"],
                    blob_sha=oid, mode=mode, **blobs[oid],
                ))
        if len(files) != 80 or len(manifest["cases"]) != 8:
            raise ValueError("incomplete original frozen project source census")
        inventory = dict(
            schema="hepta.memorycell.real-project-immutable-source-bytes.v1",
            source_cut_utc=CUT, source_manifest_sha256=manifest_sha,
            projects=len(PARTITIONS), source_prs=len(manifest["cases"]),
            original_file_bindings=len(files), unique_blobs=len(blobs),
            total_unique_original_bytes=total, remote_objects_read=reader.count,
            originals=files, selection_or_evaluation_labels_read=False,
            prompt_injection_from_sources_executed=False,
            human_review_performed=False, model_calls=0,
            semantic_citation_precision=None, production_accepted=False,
        )
        atomic_json(out / "inventory.json", inventory)
        ready = dict(
            schema="hepta.memorycell.real-project-original-source-ready.v1",
            inventory_sha256=digest((out / "inventory.json").read_bytes()),
            source_manifest_sha256=manifest_sha,
            original_file_bindings=80, unique_blobs=len(blobs),
            original_byte_count=total, original_objects_verified=True,
            independent_semantic_review=False,
            model_training_or_inference=False, production_accepted=False,
        )
        atomic_json(out / "READY.json", ready)
        return ready
    except Exception as exc:
        # A partial staging directory is evidence of failure, never READY.
        if not (out / "READY.json").exists():
            atomic_json(out / "INCOMPLETE.json", dict(
                status="incomplete", reason=type(exc).__name__,
                original_file_bindings_verified=len(files),
                verified_unique_bytes=total, research_result_valid=False,
            ))
        raise


def reopen_materialized(manifest, output, *, manifest_sha):
    """Recheck all 80 retained original Git blobs after a separate process opens READY.

    The precommitted manifest is independently SHA-pinned by the CLI. This
    read-only byte check is not a second Git fetch, semantic review, model run,
    source sufficiency judgment or production authorization.
    """
    root = Path(output)
    blobs_dir = root / "blobs"
    if (
        root.is_symlink()
        or not root.is_dir()
        or blobs_dir.is_symlink()
        or not blobs_dir.is_dir()
        or (root / "INCOMPLETE.json").exists()
    ):
        raise ValueError("missing, symlinked or incomplete original source directory")

    def read_record(filename):
        path = root / filename
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 256 * 1024:
            raise ValueError("missing or oversized source receipt")
        raw = path.read_bytes()
        data = strict_json(raw.decode("utf-8"))
        if not isinstance(data, dict) or raw != canonical(data) + b"\n":
            raise ValueError("ambiguous or noncanonical source receipt")
        return data, digest(raw)

    inventory, inventory_sha = read_record("inventory.json")
    ready, ready_sha = read_record("READY.json")
    if (
        inventory.get("schema") != "hepta.memorycell.real-project-immutable-source-bytes.v1"
        or ready.get("schema") != "hepta.memorycell.real-project-original-source-ready.v1"
        or inventory.get("source_cut_utc") != CUT
        or inventory.get("source_manifest_sha256") != manifest_sha
        or ready.get("source_manifest_sha256") != manifest_sha
        or ready.get("inventory_sha256") != inventory_sha
        or type(inventory.get("projects")) is not int
        or inventory["projects"] != len(PARTITIONS)
        or type(inventory.get("source_prs")) is not int
        or inventory["source_prs"] != 8
        or type(inventory.get("original_file_bindings")) is not int
        or inventory["original_file_bindings"] != 80
        or type(ready.get("original_file_bindings")) is not int
        or ready["original_file_bindings"] != 80
        or type(inventory.get("remote_objects_read")) is not int
        or not 1 <= inventory["remote_objects_read"] <= MAX_REQUESTS
        or inventory.get("selection_or_evaluation_labels_read") is not False
        or inventory.get("prompt_injection_from_sources_executed") is not False
        or inventory.get("human_review_performed") is not False
        or type(inventory.get("model_calls")) is not int
        or inventory["model_calls"] != 0
        or inventory.get("semantic_citation_precision") is not None
        or inventory.get("production_accepted") is not False
        or ready.get("original_objects_verified") is not True
        or ready.get("independent_semantic_review") is not False
        or ready.get("model_training_or_inference") is not False
        or ready.get("production_accepted") is not False
    ):
        raise ValueError("invalid original source inventory or false review authority")
    expected = [
        (
            case["repo"], case["partition"], case["pull_number"],
            case["head_sha"], case["tree_sha"], file["path"], file["blob_sha"],
        )
        for case in manifest["cases"]
        for file in case["files"]
    ]
    actual = inventory.get("originals")
    if not isinstance(actual, list) or len(actual) != 80:
        raise ValueError("missing original source binding")
    recorded = [
        (
            row["project"], row["partition"], row["pull_number"],
            row["head_sha"], row["tree_sha"], row["path"], row["blob_sha"],
        )
        for row in actual
    ]
    if recorded != expected or len(set(recorded)) != 80:
        raise ValueError("original project, commit, path or file identity changed")

    visited = {}
    for row in actual:
        oid = check_sha(row["blob_sha"])
        if (
            set(row) != {
                "project", "partition", "pull_number", "head_sha", "tree_sha",
                "path", "blob_sha", "mode", "sha256", "bytes", "blob_path",
            }
            or row["mode"] not in ("100644", "100755")
            or row["blob_path"] != "blobs/" + oid + ".blob"
            or type(row["bytes"]) is not int
            or not 0 <= row["bytes"] <= MAX_BLOB
            or not isinstance(row["sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
        ):
            raise ValueError("invalid original Git blob binding")
        if oid in visited:
            if visited[oid] != (row["sha256"], row["bytes"]):
                raise ValueError("identical original Git blob has contradictory bytes")
            continue
        path = blobs_dir / (oid + ".blob")
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BLOB:
            raise ValueError("missing, symlinked or oversized original file")
        raw = path.read_bytes()
        if (
            len(raw) != row["bytes"]
            or blob_sha(raw) != oid
            or digest(raw) != row["sha256"]
        ):
            raise ValueError("stored original source differs from pinned Git bytes")
        visited[oid] = (row["sha256"], len(raw))
    if {p.name for p in blobs_dir.iterdir()} != {oid + ".blob" for oid in visited}:
        raise ValueError("missing or extraneous retained original Git blobs")
    total = sum(n for _, n in visited.values())
    if (
        total > MAX_TOTAL
        or type(inventory.get("unique_blobs")) is not int
        or inventory["unique_blobs"] != len(visited)
        or type(ready.get("unique_blobs")) is not int
        or ready["unique_blobs"] != len(visited)
        or type(inventory.get("total_unique_original_bytes")) is not int
        or inventory["total_unique_original_bytes"] != total
        or type(ready.get("original_byte_count")) is not int
        or ready["original_byte_count"] != total
    ):
        raise ValueError("retained original source totals differ from committed READY")
    return dict(
        schema="hepta.memorycell.real-project-source-readback.v1",
        generating_source_manifest_sha256=manifest_sha,
        original_ready_sha256=ready_sha,
        original_inventory_sha256=inventory_sha,
        verified_file_bindings=len(actual),
        verified_git_blobs=len(visited),
        verified_unique_bytes=total,
        offline_reopen_without_network=True,
        model_calls=0,
        independent_human_semantic_review=False,
        production_accepted=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--reopen-only", action="store_true")
    args = parser.parse_args()
    manifest = read_pinned(args.source, args.source_sha256)
    if args.reopen_only:
        receipt = reopen_materialized(
            manifest, args.output, manifest_sha=args.source_sha256
        )
    else:
        token = os.environ.get("GITHUB_TOKEN")
        receipt = collect(
            manifest, args.output, manifest_sha=args.source_sha256,
            fetch=lambda repo, kind, oid: github_json(repo, kind, oid, token=token),
        )
    print(json.dumps(receipt, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
