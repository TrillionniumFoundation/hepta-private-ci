"""Fail-closed first-parent Git byte context for a pinned real-PR review cohort.

This produces paired, immutable Git source bytes for *unambiguous same-path*
first-parent comparisons only. A first-parent comparison is NEVER the entire
historical pull-request diff, a semantic answer, or independent review.
Unresolved merges, renames, absent paths and earlier unchanged paths stay
explicitly unresolved. Original source is untrusted and never executed.
"""

import argparse
from collections import Counter
from datetime import timezone
import json
import os
from pathlib import Path

from project_pr_source_materialize import (
    MAX_BLOB, ObjectReader, atomic_json, blob_sha, canonical, check_sha,
    decode_blob, digest, github_json, reopen_materialized, verify_head,
)
from project_pr_source_precommit import CUT, PARTITIONS, audit, read_pinned, timestamp

MAX_PARENT_BYTES = 32 * 1024 * 1024
MAX_PARENT_REQUESTS = 512
CATEGORIES = (
    "ambiguous-multi-parent-head",
    "unresolved-renamed-previous-path",
    "added-at-first-parent-step",
    "added-already-present-in-first-parent",
    "modified-absent-at-first-parent",
    "unchanged-versus-first-parent",
    "byte-different-versus-first-parent",
)


def parent_tree_entry(reader, repo, root_tree, path):
    """Resolve exactly one path in a SHA-pinned tree; no moving branch lookup."""
    parts = path.split("/")
    if not parts or any(not p or p in (".", "..") for p in parts):
        raise ValueError("unsafe original path in first-parent resolution")
    tree_sha = check_sha(root_tree)
    for index, part in enumerate(parts):
        tree = reader.get(repo, "trees", tree_sha)
        entries = tree.get("tree")
        if (
            tree.get("truncated") is not False
            or not isinstance(entries, list)
            or len(entries) > 10000
        ):
            raise ValueError("truncated or unbounded first-parent Git tree")
        matched = [e for e in entries if e.get("path") == part]
        if not matched:
            return None
        if len(matched) != 1:
            raise ValueError("ambiguous original first-parent Git tree path")
        node = matched[0]
        if index != len(parts) - 1:
            if node.get("type") != "tree" or node.get("mode") != "040000":
                return None
            tree_sha = check_sha(node.get("sha"))
        else:
            if (node.get("type") != "blob"
                    or node.get("mode") not in ("100644", "100755")):
                raise ValueError("nonregular original first-parent source path")
            return dict(
                blob_sha=check_sha(node.get("sha")),
                mode=node["mode"],
            )
    raise ValueError("failed first-parent path traversal")


def inspect(manifest, originals, reader, *, retain):
    """Return a complete 80-row census, never a fabricated PR-level patch.

    Reader is an injected immutable Git-object fetcher. Retain(sha,raw) must
    preserve the original bytes with exclusive creation and bounded size.
    """
    audit(manifest)
    if not isinstance(originals, list) or len(originals) != 80:
        raise ValueError("complete original head-byte inventory required")
    expected = [
        (case["repo"], case["partition"], case["pull_number"],
         case["head_sha"], file["path"], file["blob_sha"])
        for case in manifest["cases"] for file in case["files"]
    ]
    given = [
        (rec["project"], rec["partition"], rec["pull_number"],
         rec["head_sha"], rec["path"], rec["blob_sha"])
        for rec in originals
    ]
    if given != expected:
        raise ValueError("head original byte identity/order differs from frozen cohort")
    records, parent_receipts = [], []
    for case in manifest["cases"]:
        verify_head(case, reader)
        parents = tuple(case["parents"])
        if not 1 <= len(parents) <= 2:
            raise ValueError("unregistered frozen Git parent count")
        bound_parents = []
        for sha in parents:
            parent = reader.get(case["repo"], "commits", check_sha(sha))
            tree_oid = check_sha(parent.get("tree", {}).get("sha"))
            committed = timestamp(parent["committer"]["date"])
            if committed > timestamp(CUT):
                raise ValueError("parent commit postdates original frozen research cut")
            bound_parents.append(dict(
                commit_sha=sha, tree_sha=tree_oid,
                committed_at_utc=committed.astimezone(timezone.utc).isoformat(),
            ))
        parent_receipts.append(dict(
            project=case["repo"], pull_number=case["pull_number"],
            head_sha=case["head_sha"], parents=bound_parents,
            first_parent_is_complete_pull_request_base=False,
        ))
        for f in case["files"]:
            if len(records) >= 80:
                raise ValueError("extra source file beyond 80-row cohort")
            original = originals[len(records)]
            record = dict(
                project=case["repo"], partition=case["partition"],
                pull_number=case["pull_number"], head_sha=case["head_sha"],
                original_path=f["path"], declared_pr_file_status=f["status"],
                original_head_sha1=f["blob_sha"],
                original_head_sha256=original["sha256"],
                previous_git_blob_sha1=None,
                previous_sha256=None,
                previous_mode=None,
                before_blob_path=None,
                first_parent_commit_sha=parents[0] if len(parents) == 1 else None,
                full_pr_base_diff_certified=False,
                human_semantic_review_performed=False,
                independent_source_sufficiency=None,
            )
            if len(parents) != 1:
                status = "ambiguous-multi-parent-head"
            elif f["status"] == "renamed":
                status = "unresolved-renamed-previous-path"
            else:
                prev = parent_tree_entry(
                    reader, case["repo"], bound_parents[0]["tree_sha"], f["path"]
                )
                if prev is None:
                    status = (
                        "added-at-first-parent-step"
                        if f["status"] == "added"
                        else "modified-absent-at-first-parent"
                    )
                else:
                    sha = prev["blob_sha"]
                    record["previous_git_blob_sha1"] = sha
                    record["previous_mode"] = prev["mode"]
                    if sha == f["blob_sha"]:
                        record["previous_sha256"] = original["sha256"]
                        status = (
                            "added-already-present-in-first-parent"
                            if f["status"] == "added"
                            else "unchanged-versus-first-parent"
                        )
                    else:
                        old_blob = reader.get(case["repo"], "blobs", sha)
                        raw = decode_blob(old_blob, sha)
                        if len(raw) > MAX_BLOB or blob_sha(raw) != sha:
                            raise ValueError("unverified first-parent source bytes")
                        record["previous_sha256"] = digest(raw)
                        record["before_blob_path"] = retain(sha, raw)
                        status = "byte-different-versus-first-parent"
            if status not in CATEGORIES:
                raise ValueError("unknown source diff status")
            record["comparison_status"] = status
            records.append(record)
    if len(records) != 80 or len(parent_receipts) != 8:
        raise ValueError("incomplete frozen Git parent evidence census")
    counts = dict(sorted(Counter(x["comparison_status"] for x in records).items()))
    return dict(
        schema="hepta.memorycell.first-parent-byte-context.v1",
        source_cut_utc=CUT,
        original_project_count=len(PARTITIONS),
        original_pr_count=len(parent_receipts),
        original_file_count=len(records),
        comparison_counts=counts,
        original_file_order_preserved=True,
        head_only_first_parent_not_complete_pr_history=True,
        multimerge_parents_unresolved=True,
        rename_old_paths_not_in_original_manifest=True,
        parent_commits=parent_receipts,
        files=records,
        test_target_labels_read=False,
        source_code_executed=False,
        pretrained_model_calls=0,
        independently_adjudicated_semantic_precision=None,
        complete_pr_change_intent_verified=False,
        production_accepted=False,
    )


def collect_parent(manifest, original_root, destination, *, manifest_sha, fetch):
    """Verify original 80 HEAD bytes, then exclusively seal before-byte context."""
    if destination.exists() or destination.is_symlink():
        raise ValueError("parent context must have a new output directory")
    validated = reopen_materialized(
        manifest, original_root, manifest_sha=manifest_sha,
    )
    inventory_path = original_root / "inventory.json"
    if inventory_path.is_symlink() or not inventory_path.is_file():
        raise ValueError("missing canonical original inventory")
    raw_inventory = inventory_path.read_bytes()
    if digest(raw_inventory) != validated["original_inventory_sha256"]:
        raise ValueError("original source inventory drift")
    from project_pr_source_materialize import strict_json
    inventory = strict_json(raw_inventory.decode("utf-8"))
    destination.mkdir(parents=True, exist_ok=False)
    blobdir = destination / "before-blobs"
    blobdir.mkdir()
    seen, total = {}, 0

    def retain(sha, raw):
        nonlocal total
        if sha not in seen:
            if total + len(raw) > MAX_PARENT_BYTES:
                raise ValueError("first-parent source byte ceiling exceeded")
            path = blobdir / (sha + ".blob")
            with path.open("xb") as file:
                file.write(raw)
                file.flush()
                os.fsync(file.fileno())
            seen[sha] = (digest(raw), len(raw))
            total += len(raw)
        elif seen[sha] != (digest(raw), len(raw)):
            raise ValueError("same before-source SHA has conflicting bytes")
        return "before-blobs/" + sha + ".blob"

    reader = ObjectReader(fetch, request_limit=MAX_PARENT_REQUESTS)
    try:
        result = inspect(manifest, inventory["originals"], reader, retain=retain)
        if {x.name for x in blobdir.iterdir()} != {
            sha + ".blob" for sha in seen
        }:
            raise ValueError("unexpected first-parent evidence member")
        result.update(
            original_source_manifest_sha256=manifest_sha,
            original_inventory_sha256=validated["original_inventory_sha256"],
            original_ready_sha256=validated["original_ready_sha256"],
            parent_unique_blob_count=len(seen),
            parent_unique_source_bytes=total,
            git_object_requests=reader.count,
        )
        atomic_json(destination / "context.json", result)
        ready = dict(
            schema="hepta.memorycell.first-parent-context-ready.v1",
            original_source_manifest_sha256=manifest_sha,
            context_sha256=digest((destination / "context.json").read_bytes()),
            original_file_count=80,
            parent_unique_blob_count=len(seen),
            parent_unique_bytes=total,
            complete_pr_diff_certified=False,
            independent_semantic_review=False,
            model_calls=0,
            production_accepted=False,
        )
        atomic_json(destination / "READY.json", ready)
        return ready
    except Exception as error:
        if not (destination / "READY.json").exists():
            atomic_json(destination / "INCOMPLETE.json", dict(
                status="incomplete", failure_type=type(error).__name__,
                parent_blobs_written=len(seen),
                complete_pr_diff_certified=False,
                production_accepted=False,
            ))
        raise



def reopen_parent(manifest, original_root, destination, *, manifest_sha):
    """Independent local recheck of every retained first-parent source byte."""
    validated = reopen_materialized(
        manifest, original_root, manifest_sha=manifest_sha,
    )
    directory = Path(destination)
    store = directory / "before-blobs"
    if (
        directory.is_symlink() or not directory.is_dir()
        or store.is_symlink() or not store.is_dir()
        or (directory / "INCOMPLETE.json").exists()
    ):
        raise ValueError("incomplete or unsafe first-parent archive")

    def read_record(name):
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
            raise ValueError("missing or oversized first-parent metadata")
        raw = path.read_bytes()
        from project_pr_source_materialize import strict_json
        obj = strict_json(raw.decode("utf-8"))
        if not isinstance(obj, dict) or raw != canonical(obj) + b"\n":
            raise ValueError("noncanonical first-parent metadata")
        return obj, digest(raw)

    report, report_sha = read_record("context.json")
    ready, _ = read_record("READY.json")
    if (
        report.get("schema") != "hepta.memorycell.first-parent-byte-context.v1"
        or ready.get("schema") != "hepta.memorycell.first-parent-context-ready.v1"
        or report.get("source_cut_utc") != CUT
        or report.get("original_source_manifest_sha256") != manifest_sha
        or ready.get("original_source_manifest_sha256") != manifest_sha
        or report.get("original_inventory_sha256")
        != validated["original_inventory_sha256"]
        or report.get("original_ready_sha256")
        != validated["original_ready_sha256"]
        or ready.get("context_sha256") != report_sha
        or report.get("original_file_count") != 80
        or ready.get("original_file_count") != 80
        or report.get("original_pr_count") != 8
        or report.get("original_project_count") != len(PARTITIONS)
        or report.get("test_target_labels_read") is not False
        or report.get("source_code_executed") is not False
        or report.get("pretrained_model_calls") != 0
        or report.get("production_accepted") is not False
        or report.get("complete_pr_change_intent_verified") is not False
        or ready.get("complete_pr_diff_certified") is not False
        or ready.get("production_accepted") is not False
        or ready.get("independent_semantic_review") is not False
        or ready.get("model_calls") != 0
        or not isinstance(report.get("git_object_requests"), int)
        or not 1 <= report["git_object_requests"] <= MAX_PARENT_REQUESTS
    ):
        raise ValueError("untrusted or promoted original first-parent receipt")
    expected = [
        (case["repo"], case["partition"], case["pull_number"],
         case["head_sha"], file["path"], file["status"], file["blob_sha"])
        for case in manifest["cases"] for file in case["files"]
    ]
    rows = report.get("files")
    if not isinstance(rows, list) or len(rows) != 80:
        raise ValueError("missing original first-parent file census")
    actual = [
        (row["project"], row["partition"], row["pull_number"],
         row["head_sha"], row["original_path"],
         row["declared_pr_file_status"], row["original_head_sha1"])
        for row in rows
    ]
    if actual != expected or len(set(actual)) != 80:
        raise ValueError("first-parent corpus detached from precommitted source")
    counter, visited, total = Counter(), {}, 0
    for row in rows:
        status = row["comparison_status"]
        if status not in CATEGORIES:
            raise ValueError("invalid first-parent outcome")
        counter[status] += 1
        if row["full_pr_base_diff_certified"] is not False or row[
            "human_semantic_review_performed"
        ] is not False or row["independent_source_sufficiency"] is not None:
            raise ValueError("fabricated parent diff or reviewer qualification")
        if status == "byte-different-versus-first-parent":
            oid = check_sha(row["previous_git_blob_sha1"])
            filename = "before-blobs/" + oid + ".blob"
            if row["before_blob_path"] != filename:
                raise ValueError("first-parent file path identity drift")
            path = store / (oid + ".blob")
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BLOB:
                raise ValueError("missing or unsafe original first-parent blob")
            raw = path.read_bytes()
            if blob_sha(raw) != oid or digest(raw) != row["previous_sha256"]:
                raise ValueError("tampered or unpinned parent source bytes")
            if oid in visited and visited[oid] != (len(raw), row["previous_sha256"]):
                raise ValueError("contradictory reused parent Git blob")
            if oid not in visited:
                visited[oid] = (len(raw), row["previous_sha256"])
                total += len(raw)
        elif row["before_blob_path"] is not None:
            raise ValueError("invented source bytes for unresolved first-parent row")
        if status in ("ambiguous-multi-parent-head",
                      "unresolved-renamed-previous-path",
                      "added-at-first-parent-step",
                      "modified-absent-at-first-parent"):
            if row["previous_git_blob_sha1"] is not None:
                raise ValueError("fabricated previous file for unresolved parent")
        if status in ("unchanged-versus-first-parent",
                      "added-already-present-in-first-parent"):
            if (
                row["previous_git_blob_sha1"] != row["original_head_sha1"]
                or row["previous_sha256"] != row["original_head_sha256"]
            ):
                raise ValueError("unverified unchanged parent comparison")

    parent_cases = report.get("parent_commits")
    if (
        not isinstance(parent_cases, list)
        or len(parent_cases) != len(manifest["cases"])
        or any(
            p["project"] != c["repo"]
            or p["pull_number"] != c["pull_number"]
            or [x["commit_sha"] for x in p["parents"]] != c["parents"]
            or p["first_parent_is_complete_pull_request_base"] is not False
            for p, c in zip(parent_cases, manifest["cases"], strict=True)
        )
    ):
        raise ValueError("first-parent Git commits differ from frozen manifest")
    if (
        {path.name for path in store.iterdir()} != {
            oid + ".blob" for oid in visited
        }
        or dict(sorted(counter.items())) != report["comparison_counts"]
        or total > MAX_PARENT_BYTES
        or type(report.get("parent_unique_blob_count")) is not int
        or report["parent_unique_blob_count"] != len(visited)
        or ready.get("parent_unique_blob_count") != len(visited)
        or report.get("parent_unique_source_bytes") != total
        or ready.get("parent_unique_bytes") != total
    ):
        raise ValueError("first-parent byte/census manifest altered")
    return dict(
        schema="hepta.memorycell.first-parent-offline-reopen.v1",
        original_file_count=80,
        saved_before_blobs=len(visited),
        verified_before_bytes=total,
        unresolved_first_parent_rows=(
            counter["ambiguous-multi-parent-head"]
            + counter["unresolved-renamed-previous-path"]
            + counter["modified-absent-at-first-parent"]
        ),
        offline_source_hash_verification=True,
        complete_pr_diff_certified=False,
        human_review_performed=False,
        model_calls=0,
        production_accepted=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("original", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--reopen-only", action="store_true")
    args = parser.parse_args()
    manifest = read_pinned(args.manifest, args.source_sha256)
    if args.reopen_only:
        receipt = reopen_parent(
            manifest, args.original, args.destination,
            manifest_sha=args.source_sha256,
        )
    else:
        receipt = collect_parent(
            manifest, args.original, args.destination,
            manifest_sha=args.source_sha256,
            fetch=lambda repo, kind, oid: github_json(
                repo, kind, oid, token=os.environ.get("GITHUB_TOKEN")
            ),
        )
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
