"""Byte-exact original Git source acquisition for six frozen external project proxies.

Research-only. Preserve Latin-1 and all other non-UTF-8 blob bytes verbatim;
never use decoded Contents API text as an original-source attestation. This
worker has no targets, source reviewer, model, training or production issuer.
"""

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MANIFEST_BLOB = "5c7ba1b6dd4cafb445794346afb21687816f726e"
PREVIOUS_SHA256 = "ef2a46ce037db4a91affddd2498eb8e089771ae5734bc13c56cb8a97b840a463"
CUT = "2026-10-12T16:05:00Z"
PARTITIONS = {
    "python/cpython": "evaluation",
    "pandas-dev/pandas": "train",
    "scikit-learn/scikit-learn": "evaluation",
    "tokio-rs/tokio": "train",
    "prometheus/prometheus": "selection",
    "denoland/deno": "evaluation",
}
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
MAX_BLOB = 1024 * 1024
MAX_TOTAL = 16 * 1024 * 1024
MAX_TREE_JSON = 8 * 1024 * 1024
MAX_REQUESTS = 256


def strict_json(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError("duplicate Git source metadata key")
            out[key] = value
        return out

    def bad(value):
        raise ValueError("nonfinite Git source metadata: " + value)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad)


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8") + b"\n"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def git_blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def sha(value):
    if type(value) is not str or not HEX40.fullmatch(value):
        raise ValueError("invalid immutable Git object ID")
    return value


def asof(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.utcoffset() is None:
            raise ValueError("missing timezone")
        return result.astimezone(timezone.utc)
    except (TypeError, AttributeError, ValueError) as error:
        raise ValueError("invalid immutable Git timestamp") from error


def original_file(path, *, limit):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError("missing, symlinked or oversized source")
    raw = path.read_bytes()
    if len(raw) > limit:
        raise ValueError("oversized pinned source")
    return raw


def load_manifest(manifest_path, previous_path):
    raw = original_file(manifest_path, limit=512 * 1024)
    if git_blob(raw) != MANIFEST_BLOB:
        raise ValueError("externally frozen extension manifest changed")
    if digest(original_file(previous_path, limit=512 * 1024)) != PREVIOUS_SHA256:
        raise ValueError("original earlier cohort changed")
    value = strict_json(raw)
    from project_pr_family_extension import audit

    audit(value)
    if value["source_cut_utc"] != CUT or value["partitions"] != PARTITIONS:
        raise ValueError("external family assignment changed")
    return value, digest(raw)


def fetch_git(repo, kind, object_sha, *, token=None):
    """Fetch only allowlisted immutable public Git objects, not moving paths."""
    if repo not in PARTITIONS or kind not in {"commits", "trees", "blobs"}:
        raise ValueError("unregistered Git source request")
    oid = sha(object_sha)
    url = f"https://api.github.com/repos/{repo}/git/{kind}/{oid}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "hepta-extension-bytes/1",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    limit = MAX_TREE_JSON if kind == "trees" else (2 * MAX_BLOB + 65536)
    try:
        with urlopen(Request(url, headers=headers), timeout=30) as response:
            if response.status != 200:
                raise ValueError("remote Git request failed")
            raw = response.read(limit + 1)
    except (HTTPError, URLError) as error:
        raise ValueError("original immutable Git object unavailable") from error
    if not raw or len(raw) > limit:
        raise ValueError("bounded immutable Git response required")
    result = strict_json(raw)
    if not isinstance(result, dict) or result.get("sha") != oid:
        raise ValueError("remote Git object changed identity")
    return result


class GitObjects:
    def __init__(self, fetch, *, maximum=MAX_REQUESTS):
        self.fetch = fetch
        self.maximum = maximum
        self.cache = {}
        self.count = 0

    def get(self, repo, kind, oid):
        if repo not in PARTITIONS or kind not in ("commits", "trees", "blobs"):
            raise ValueError("unregistered project or Git object category")
        key = (repo, kind, sha(oid))
        if key not in self.cache:
            if self.count >= self.maximum:
                raise ValueError("Git object request bound exhausted")
            self.count += 1
            response = self.fetch(*key)
            if not isinstance(response, dict) or response.get("sha") != oid:
                raise ValueError("fetched source ID differs from frozen object")
            self.cache[key] = response
        return self.cache[key]


def verify_commit(case, commit, objects, *, head=False):
    obj = objects.get(case["repo"], "commits", commit["sha"])
    when = obj.get("committer", {}).get("date")
    if when != commit["committed_at"] or asof(when) > asof(CUT):
        raise ValueError("committer time no longer matches frozen cut")
    if asof(obj.get("author", {}).get("date")) > asof(CUT):
        raise ValueError("authored future source admitted before cut")
    raw_parents = obj.get("parents")
    if not isinstance(raw_parents, list) or len(raw_parents) > 8:
        raise ValueError("invalid frozen Git parent census")
    parents = [sha(x.get("sha")) for x in raw_parents]
    if len(set(parents)) != len(parents):
        raise ValueError("duplicate parent in original Git commit")
    tree_sha = sha(obj.get("tree", {}).get("sha"))
    if head and (
        obj.get("tree", {}).get("sha") != case["tree_sha"]
        or parents != case["parents"]
        or commit["sha"] != case["head_sha"]
    ):
        raise ValueError("original head tree/parent binding differs")
    return {
        "repo": case["repo"],
        "sha": obj["sha"],
        "tree": tree_sha,
        "parents": parents,
    }


def verify_path(case, source, objects):
    path = source["path"]
    if (
        not isinstance(path, str)
        or not path
        or len(path) > 512
        or any(p in ("", ".", "..") for p in path.split("/"))
    ):
        raise ValueError("unsafe registered source path")
    tree_sha = sha(case["tree_sha"])
    nodes = path.split("/")
    for i, name in enumerate(nodes):
        tree = objects.get(case["repo"], "trees", tree_sha)
        entries = tree.get("tree")
        if (
            tree.get("truncated") is not False
            or not isinstance(entries, list)
            or len(entries) > 10000
        ):
            raise ValueError("missing or truncated exact Git tree")
        hits = [x for x in entries if x.get("path") == name]
        if len(hits) != 1:
            raise ValueError("source path not bound to original tree")
        row = hits[0]
        if i < len(nodes) - 1:
            if row.get("type") != "tree" or row.get("mode") != "040000":
                raise ValueError("non-directory traversed as source parent")
            tree_sha = sha(row.get("sha"))
        elif (
            row.get("type") != "blob"
            or row.get("mode") not in ("100644", "100755")
            or row.get("sha") != source["blob_sha"]
        ):
            raise ValueError("source blob/path/mode detached from HEAD tree")
    return row["mode"]


def original_blob(obj, expected):
    """Git Base64 blob bytes: no lossy UTF-8 conversion, ever."""
    if obj.get("sha") != expected or obj.get("encoding") != "base64":
        raise ValueError("wrong original Git blob encoding or identity")
    size = obj.get("size")
    if type(size) is not int or not 0 <= size <= MAX_BLOB:
        raise ValueError("original source exceeds file cap")
    content = obj.get("content")
    if type(content) is not str or len(content) > 2 * MAX_BLOB + 16:
        raise ValueError("oversized Git Base64 envelope")
    try:
        raw = base64.b64decode(content.replace("\n", "").encode("ascii"), validate=True)
    except (ValueError, UnicodeError) as error:
        raise ValueError("malformed original Git Base64 bytes") from error
    if len(raw) != size or git_blob(raw) != expected:
        raise ValueError("original binary bytes do not match Git SHA")
    return raw


def store(path, raw):
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def acquire(manifest, output, *, manifest_sha, fetch):
    """Only a full 6-HEAD/14-commit/32-file census may publish READY."""
    if output.exists():
        raise ValueError("immutable output directory already exists")
    output.mkdir(parents=True, exist_ok=False)
    (output / "blobs").mkdir()
    reader = GitObjects(fetch)
    rows, commits, seen, total, non_utf8 = [], [], {}, 0, 0
    try:
        for case in manifest["cases"]:
            chain = []
            for item in case["commits"]:
                is_head = item["sha"] == case["head_sha"]
                chain.append(verify_commit(case, item, reader, head=is_head))
            if (
                not chain
                or chain[-1]["sha"] != case["head_sha"]
                or len({row["sha"] for row in chain}) != len(chain)
            ):
                raise ValueError("registered original Git commits must end at HEAD")
            for predecessor, successor in zip(chain, chain[1:], strict=False):
                if predecessor["sha"] not in successor["parents"]:
                    raise ValueError("registered Git commit is not an ancestor of HEAD")
            commits.extend(chain)
            for source in case["files"]:
                mode = verify_path(case, source, reader)
                oid = sha(source["blob_sha"])
                if oid not in seen:
                    raw = original_blob(reader.get(case["repo"], "blobs", oid), oid)
                    if total + len(raw) > MAX_TOTAL:
                        raise ValueError("full source bytes exceed cap")
                    total += len(raw)
                    try:
                        raw.decode("utf-8", "strict")
                    except UnicodeDecodeError:
                        non_utf8 += 1
                    store(output / "blobs" / (oid + ".blob"), raw)
                    seen[oid] = {"sha256": digest(raw), "bytes": len(raw)}
                rows.append(
                    {
                        "repo": case["repo"],
                        "partition": case["partition"],
                        "pull_number": case["pull_number"],
                        "head_sha": case["head_sha"],
                        "tree_sha": case["tree_sha"],
                        "path": source["path"],
                        "blob_sha": oid,
                        "mode": mode,
                        **seen[oid],
                    }
                )
        if len(rows) != 32 or len(commits) != 14 or len(manifest["cases"]) != 6:
            raise ValueError("incomplete precommitted external source census")
        inventory = {
            "schema": "hepta.memorycell.external-project-original-bytes.v1",
            "source_cut_utc": CUT,
            "source_manifest_git_blob_sha1": MANIFEST_BLOB,
            "source_manifest_sha256": manifest_sha,
            "source_family_proxies": 6,
            "original_commit_objects": len(commits),
            "registered_parent_edges": sum(
                len(case["commits"]) - 1 for case in manifest["cases"]
            ),
            "original_file_bindings": len(rows),
            "unique_original_blobs": len(seen),
            "total_original_bytes": total,
            "non_utf8_original_blobs": non_utf8,
            "remote_git_objects_read": reader.count,
            "files": rows,
            "commits": commits,
            "no_answer_targets_opened": True,
            "model_calls": 0,
            "independent_semantic_review": False,
            "production_accepted": False,
        }
        store(output / "inventory.json", canonical(inventory))
        ready = {
            "schema": "hepta.memorycell.external-project-source-ready.v1",
            "inventory_sha256": digest((output / "inventory.json").read_bytes()),
            "source_manifest_git_blob_sha1": MANIFEST_BLOB,
            "source_manifest_sha256": manifest_sha,
            "verified_file_bindings": 32,
            "verified_commit_objects": 14,
            "verified_original_bytes": total,
            "all_original_binary_bytes_reopened": False,
            "independent_semantic_review": False,
            "production_accepted": False,
        }
        store(output / "READY.json", canonical(ready))
        return ready
    except Exception as error:
        if not (output / "READY.json").exists():
            store(
                output / "INCOMPLETE.json",
                canonical(
                    {
                        "status": "incomplete",
                        "verified_file_bindings": len(rows),
                        "verified_original_bytes": total,
                        "reason": type(error).__name__,
                        "research_result_valid": False,
                    }
                ),
            )
        raise


def reopen(manifest, output, *, manifest_sha):
    """A separate invocation checks every original binary member from disk."""
    if (
        output.is_symlink()
        or not output.is_dir()
        or (output / "blobs").is_symlink()
        or (output / "INCOMPLETE.json").exists()
    ):
        raise ValueError("unverified original-source directory")
    raw = original_file(output / "inventory.json", limit=512 * 1024)
    raw_ready = original_file(output / "READY.json", limit=8192)
    inventory, ready = strict_json(raw), strict_json(raw_ready)
    if raw != canonical(inventory) or raw_ready != canonical(ready):
        raise ValueError("noncanonical source inventory/READY")
    if (
        inventory.get("schema") != "hepta.memorycell.external-project-original-bytes.v1"
        or ready.get("schema") != "hepta.memorycell.external-project-source-ready.v1"
        or inventory.get("source_cut_utc") != CUT
        or inventory.get("source_manifest_git_blob_sha1") != MANIFEST_BLOB
        or inventory.get("source_manifest_sha256") != manifest_sha
        or ready.get("source_manifest_sha256") != manifest_sha
        or ready.get("source_manifest_git_blob_sha1") != MANIFEST_BLOB
        or ready.get("inventory_sha256") != digest(raw)
        or ready.get("verified_file_bindings") != 32
        or ready.get("verified_commit_objects") != 14
        or inventory.get("source_family_proxies") != 6
        or inventory.get("original_file_bindings") != 32
        or inventory.get("original_commit_objects") != 14
        or inventory.get("registered_parent_edges") != sum(
            len(case["commits"]) - 1 for case in manifest["cases"]
        )
        or inventory.get("no_answer_targets_opened") is not True
        or inventory.get("model_calls") != 0
        or inventory.get("production_accepted") is not False
        or ready.get("production_accepted") is not False
        or ready.get("independent_semantic_review") is not False
    ):
        raise ValueError("original source inventory lineage or authority changed")
    expected = [
        (
            c["repo"], c["partition"], c["pull_number"], c["head_sha"],
            c["tree_sha"], f["path"], f["blob_sha"],
        )
        for c in manifest["cases"]
        for f in c["files"]
    ]
    recorded = [
        (
            r["repo"], r["partition"], r["pull_number"], r["head_sha"],
            r["tree_sha"], r["path"], r["blob_sha"],
        )
        for r in inventory.get("files", [])
    ]
    if recorded != expected or len(set(recorded)) != 32:
        raise ValueError("original source path and partition census changed")
    expected_commits = [
        (c["repo"], row["sha"])
        for c in manifest["cases"]
        for row in c["commits"]
    ]
    got_commits = [(c["repo"], c["sha"]) for c in inventory.get("commits", [])]
    if got_commits != expected_commits:
        raise ValueError("registered commit object identities differ")
    cursor = 0
    for case in manifest["cases"]:
        chain = inventory["commits"][cursor : cursor + len(case["commits"])]
        cursor += len(chain)
        if (
            not chain
            or chain[-1]["sha"] != case["head_sha"]
            or chain[-1].get("tree") != case["tree_sha"]
            or chain[-1].get("parents") != case["parents"]
            or len({row["sha"] for row in chain}) != len(chain)
        ):
            raise ValueError("reopened Git HEAD/commit ancestry differs")
        for predecessor, successor in zip(chain, chain[1:], strict=False):
            if predecessor["sha"] not in successor.get("parents", []):
                raise ValueError("reopened Git commit chain disconnected")
    seen, total, non_utf8 = {}, 0, 0
    for row in inventory["files"]:
        oid = sha(row["blob_sha"])
        if oid in seen:
            if seen[oid] != (row["sha256"], row["bytes"]):
                raise ValueError("same Git source has conflicting bytes")
            continue
        original = original_file(output / "blobs" / (oid + ".blob"), limit=MAX_BLOB)
        if (
            git_blob(original) != oid
            or digest(original) != row["sha256"]
            or len(original) != row["bytes"]
        ):
            raise ValueError("original Git blob mutated on disk")
        try:
            original.decode("utf-8", "strict")
        except UnicodeDecodeError:
            non_utf8 += 1
        seen[oid] = (row["sha256"], len(original))
        total += len(original)
    if (
        total > MAX_TOTAL
        or total != inventory["total_original_bytes"]
        or total != ready["verified_original_bytes"]
        or len(seen) != inventory["unique_original_blobs"]
        or non_utf8 != inventory["non_utf8_original_blobs"]
        or {p.name for p in (output / "blobs").iterdir()}
        != {oid + ".blob" for oid in seen}
    ):
        raise ValueError("incomplete or extraneous retained Git source bytes")
    return {
        "schema": "hepta.memorycell.external-project-independent-reopen.v1",
        "verified_original_file_bindings": len(recorded),
        "verified_original_commit_objects": len(got_commits),
        "verified_original_byte_count": total,
        "non_utf8_original_blobs": non_utf8,
        "original_binary_reopen_completed": True,
        "independent_semantic_review": False,
        "production_accepted": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("acquire", "reopen"))
    parser.add_argument("extension", type=Path)
    parser.add_argument("previous", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    manifest, manifest_sha = load_manifest(args.extension, args.previous)
    if args.phase == "acquire":
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        result = acquire(
            manifest,
            args.output,
            manifest_sha=manifest_sha,
            fetch=lambda repo, kind, oid: fetch_git(repo, kind, oid, token=token),
        )
    else:
        result = reopen(manifest, args.output, manifest_sha=manifest_sha)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
