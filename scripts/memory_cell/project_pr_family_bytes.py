"""Byte-verify the six source-only Git PR families, never certify answers.

Acquire ONLY precommitted Git objects. A complete READY is written after every
head tree, parent, historical commit and referenced original blob passes its
source check. This does not authenticate historical PR discussion or reviews.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from project_pr_family_extension import (
    CUT,
    PARTITIONS,
    PREVIOUS_SHA,
    audit,
)
from project_pr_source_materialize import (
    MAX_BLOB,
    ObjectReader,
    atomic_json,
    bind_path,
    blob_sha,
    check_sha,
    decode_blob,
    digest,
    strict_json,
)
from project_pr_source_precommit import read_pinned, timestamp

MAX_TOTAL = 24 * 1024 * 1024
MAX_REPLIES = 512
MAX_TREE_JSON = 6 * 1024 * 1024


def github_object(repo, category, sha, *, token=None):
    """The caller supplies a sealed SHA, never an arbitrary HTTP address."""
    if repo not in PARTITIONS or category not in ("commits", "trees", "blobs"):
        raise ValueError("unregistered original Git object request")
    sha = check_sha(sha)
    url = f"https://api.github.com/repos/{repo}/git/{category}/{sha}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "hepta-public-source-identity/1",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    request = Request(url, headers=headers)
    limit = MAX_TREE_JSON if category == "trees" else 2 * MAX_BLOB + 32768
    try:
        with urlopen(request, timeout=30) as response:
            if response.status != 200:
                raise ValueError("non-success GitHub original object response")
            payload = response.read(limit + 1)
    except (HTTPError, URLError) as error:
        raise ValueError("exact public Git object not available") from error
    if not payload or len(payload) > limit:
        raise ValueError("oversized or missing original Git object")
    result = strict_json(payload.decode("utf-8"))
    if not isinstance(result, dict) or result.get("sha") != sha:
        raise ValueError("remote object identity not the frozen source SHA")
    return result


def verify_commits(case, reader):
    """Verify source commit dates, head tree and contiguous PR ancestry."""
    prior = None
    count = 0
    for registered in case["commits"]:
        identity = registered["sha"]
        obj = reader.get(case["repo"], "commits", identity)
        parents = [item.get("sha") for item in obj.get("parents", ())]
        try:
            authored = timestamp(obj["author"]["date"])
            committed = timestamp(obj["committer"]["date"])
        except (TypeError, AttributeError, KeyError, ValueError) as error:
            raise ValueError("Git source commit missing actual dates") from error
        if (
            authored > timestamp(CUT)
            or committed > timestamp(CUT)
            or committed != timestamp(registered["committed_at"])
            or not 1 <= len(parents) <= 2
            or any(not isinstance(p, str) for p in parents)
        ):
            raise ValueError("source commit outside cut or invalid parents")
        for parent in parents:
            check_sha(parent)
        if prior is not None and prior not in parents:
            raise ValueError("listed PR commits lack ancestry continuity")
        if identity == case["head_sha"]:
            if (
                obj.get("tree", {}).get("sha") != case["tree_sha"]
                or parents != case["parents"]
                or committed != timestamp(case["head_committed_at"])
            ):
                raise ValueError("frozen PR head/tree/parents differ from Git")
        prior = identity
        count += 1
    if prior != case["head_sha"]:
        raise ValueError("last source commit is not frozen HEAD")
    return count


def reopen(output, inventory):
    """Independently read each delivered original blob and compare both hashes."""
    entries = inventory["originals"]
    if len(entries) != 32:
        raise ValueError("unverified or incomplete Git blob census")
    total = 0
    for item in entries:
        filename = output / "blobs" / (item["blob_sha"] + ".blob")
        if (
            filename.is_symlink()
            or not filename.is_file()
            or filename.stat().st_size != item["bytes"]
            or item["bytes"] > MAX_BLOB
        ):
            raise ValueError("original blob missing or changed after download")
        content = filename.read_bytes()
        if (
            blob_sha(content) != item["blob_sha"]
            or digest(content) != item["byte_sha256"]
        ):
            raise ValueError("reopened bytes differ from the frozen Git blob")
        total += len(content)
    if total != inventory["retained_source_bytes"] or total > MAX_TOTAL:
        raise ValueError("original source retained-byte bound differs")
    return {
        "schema": "hepta.memorycell.public-pr-extension.offline-reopen.v1",
        "original_source_files_reopened": len(entries),
        "original_source_bytes": total,
        "complete_blob_sha1_and_sha256_check": True,
        "model_calls": 0,
        "human_review_performed": False,
        "production_accepted": False,
    }


def collect(extension, previous, output, *, source_sha256, fetch):
    if output.exists() or output.is_symlink() or not output.parent.is_dir():
        raise ValueError("source archive must use an absent local output path")
    raw = Path(extension)
    if (
        not raw.is_file()
        or raw.is_symlink()
        or raw.stat().st_size > 128 * 1024
        or raw.stat().st_size == 0
        or not isinstance(source_sha256, str)
        or len(source_sha256) != 64
        or hashlib.sha256(raw.read_bytes()).hexdigest() != source_sha256
    ):
        raise ValueError("source extension not pinned to exact bytes")
    manifest = strict_json(raw.read_text(encoding="utf-8"))
    audit(manifest)
    original = read_pinned(previous, PREVIOUS_SHA)
    if len(original["cases"]) != 8:
        raise ValueError("original project source reference not intact")
    reader = ObjectReader(fetch, request_limit=MAX_REPLIES)
    output.mkdir()
    (output / "blobs").mkdir()
    originals = []
    source_total = 0
    source_commits = 0
    # Never publish READY on a partial source census.
    for case in manifest["cases"]:
        source_commits += verify_commits(case, reader)
        for file in case["files"]:
            mode = bind_path(case, file, reader)
            oid = file["blob_sha"]
            blob = reader.get(case["repo"], "blobs", oid)
            data = decode_blob(blob, oid)
            source_total += len(data)
            if source_total > MAX_TOTAL:
                raise ValueError("original code exceeds retained-byte budget")
            path = output / "blobs" / (oid + ".blob")
            with path.open("xb") as sink:
                sink.write(data)
                sink.flush()
                os.fsync(sink.fileno())
            originals.append({
                "project": case["repo"],
                "partition": case["partition"],
                "pull_number": case["pull_number"],
                "head_sha": case["head_sha"],
                "tree_sha": case["tree_sha"],
                "path": file["path"],
                "mode": mode,
                "blob_sha": oid,
                "byte_sha256": digest(data),
                "bytes": len(data),
            })
    if len(originals) != 32 or source_commits != 14:
        raise ValueError("missing original Git objects")
    inventory = {
        "schema": "hepta.memorycell.public-pr-extension.source-bytes.v1",
        "source_manifest_sha256": source_sha256,
        "previous_source_manifest_sha256": PREVIOUS_SHA,
        "source_cut_utc": CUT,
        "commits_checked": source_commits,
        "originals": originals,
        "original_files": len(originals),
        "retained_source_bytes": source_total,
        "request_count": reader.count,
        "source_project_proxies": len(PARTITIONS),
        "model_calls": 0,
        "answer_labels_consumed": False,
        "parent_diffs_verified": False,
        "historical_review_authenticated": False,
        "independent_reviewer_performed": False,
        "production_accepted": False,
    }
    audit_reopen = reopen(output, inventory)
    atomic_json(output / "inventory.json", inventory)
    atomic_json(output / "readback.json", audit_reopen)
    ready = {
        "schema": "hepta.memorycell.public-pr-extension.source-ready.v1",
        "source_manifest_sha256": source_sha256,
        "original_inventory_sha256": digest(
            (output / "inventory.json").read_bytes()
        ),
        "original_reopen_sha256": digest((output / "readback.json").read_bytes()),
        "original_files_verified": 32,
        "original_commits_verified": source_commits,
        "not_a_human_evidence_oracle": True,
        "not_model_ready_without_parent_diffs_and_review": True,
        "semantic_citation_precision": None,
        "production_accepted": False,
    }
    atomic_json(output / "READY.json", ready)
    descriptor = os.open(output, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return ready


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("extension", type=Path)
    parser.add_argument("previous", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-sha256", required=True)
    args = parser.parse_args()
    ready = collect(
        args.extension,
        args.previous,
        args.output,
        source_sha256=args.source_sha256,
        fetch=lambda repo, kind, oid: github_object(
            repo, kind, oid, token=os.environ.get("GH_TOKEN")
        ),
    )
    print(json.dumps(ready, allow_nan=False, sort_keys=True))


if __name__ == "__main__":
    main()
