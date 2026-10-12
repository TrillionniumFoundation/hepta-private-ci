"""Acquire the original Git code bytes for the precommitted project cohort.

This is research evidence acquisition, NOT gold labels, a trained model,
independent review, an authenticated historical PR discussion or production use.
All remote object identities are pinned before fetching. A partial download
cannot publish READY. Retrieved source is untrusted data, never instructions.
"""

import argparse
import base64
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from project_pr_source_precommit import CUT, PARTITIONS, read_pinned

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
    author = commit.get("author", {})
    try:
        authored = datetime.fromisoformat(author["date"].replace("Z", "+00:00"))
        cut = datetime.fromisoformat(CUT.replace("Z", "+00:00"))
        if authored > cut or authored.tzinfo is None:
            raise ValueError("source was committed after frozen cut")
    except (KeyError, AttributeError) as exc:
        raise ValueError("missing original commit timestamp") from exc


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-sha256", required=True)
    args = parser.parse_args()
    manifest = read_pinned(args.source, args.source_sha256)
    token = os.environ.get("GITHUB_TOKEN")
    ready = collect(
        manifest, args.output, manifest_sha=args.source_sha256,
        fetch=lambda repo, kind, oid: github_json(repo, kind, oid, token=token),
    )
    print(json.dumps(ready, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
