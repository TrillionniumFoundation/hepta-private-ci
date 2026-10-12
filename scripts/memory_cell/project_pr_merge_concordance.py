"""Only SHA-addressed byte agreement between BOTH parents of a merge HEAD.

Supplementary public-source acquisition, not the full PR base diff, a review,
a model experiment, new independent families or production authorization.
The original first-parent archive remains unchanged and separately verifiable.
"""

import argparse
from collections import Counter
import json
import os
from pathlib import Path

from project_pr_parent_context import parent_tree_entry, reopen_parent
from project_pr_source_materialize import (
    MAX_BLOB, ObjectReader, atomic_json, blob_sha, canonical, decode_blob,
    digest, github_json, strict_json,
)
from project_pr_source_precommit import audit, read_pinned

SCHEMA = "hepta.memorycell.merge-parent-concordance.v1"
MAX_BYTES = 24 * 1024 * 1024
MAX_REQUESTS = 512
STATES = (
    "unresolved-rename", "absent-both", "absent-one", "parents-diverge",
    "identical-to-both-parents", "changed-from-identical-parents",
)


def classify(head, first, second, *, renamed=False):
    if renamed:
        return "unresolved-rename"
    if first is None and second is None:
        return "absent-both"
    if first is None or second is None:
        return "absent-one"
    if first != second:
        return "parents-diverge"
    return (
        "identical-to-both-parents"
        if first["blob_sha"] == head
        else "changed-from-identical-parents"
    )


def read_canonical(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("unsafe or missing canonical source record")
    raw = path.read_bytes()
    item = strict_json(raw.decode("utf-8"))
    if raw != canonical(item) + b"\n":
        raise ValueError("noncanonical source record")
    return item, digest(raw)


def inspect(manifest, parent, reader, retain):
    audit(manifest)
    if (
        parent.get("schema") != "hepta.memorycell.first-parent-byte-context.v1"
        or parent.get("original_file_count") != 80
        or parent.get("head_only_first_parent_not_complete_pr_history") is not True
        or parent.get("production_accepted") is not False
        or parent.get("test_target_labels_read") is not False
        or len(parent.get("files", [])) != 80
        or len(parent.get("parent_commits", [])) != 8
    ):
        raise ValueError("unverified first-parent census")
    rows, index = [], 0
    for case, receipt in zip(manifest["cases"], parent["parent_commits"], strict=True):
        parents = receipt["parents"]
        if (
            receipt["project"] != case["repo"]
            or receipt["pull_number"] != case["pull_number"]
            or receipt["head_sha"] != case["head_sha"]
            or [p["commit_sha"] for p in parents] != case["parents"]
            or receipt["first_parent_is_complete_pull_request_base"] is not False
        ):
            raise ValueError("unregistered merge-parent Git ancestry")
        for file in case["files"]:
            original = parent["files"][index]
            index += 1
            if (
                original["project"] != case["repo"]
                or original["pull_number"] != case["pull_number"]
                or original["original_path"] != file["path"]
                or original["original_head_sha1"] != file["blob_sha"]
                or original["full_pr_base_diff_certified"] is not False
            ):
                raise ValueError("original head-source binding drift")
            if len(case["parents"]) == 1:
                continue
            if len(case["parents"]) != 2 or original["comparison_status"] != "ambiguous-multi-parent-head":
                raise ValueError("two-parent audit requires the unresolved legacy record")
            entries = (
                [None, None]
                if file["status"] == "renamed"
                else [
                    parent_tree_entry(reader, case["repo"], p["tree_sha"], file["path"])
                    for p in parents
                ]
            )
            state = classify(file["blob_sha"], *entries, renamed=file["status"] == "renamed")
            before_sha = before_digest = before_file = None
            if state in ("identical-to-both-parents", "changed-from-identical-parents"):
                before_sha = entries[0]["blob_sha"]
                if state == "identical-to-both-parents":
                    before_digest = original["original_head_sha256"]
                else:
                    raw = decode_blob(
                        reader.get(case["repo"], "blobs", before_sha), before_sha
                    )
                    if len(raw) > MAX_BLOB or blob_sha(raw) != before_sha:
                        raise ValueError("invalid prior source SHA-addressed blob")
                    before_digest = digest(raw)
                    before_file = retain(before_sha, raw)
            rows.append(dict(
                project=case["repo"], partition=case["partition"],
                pull_number=case["pull_number"], head_sha=case["head_sha"],
                head_path=file["path"], head_blob_sha1=file["blob_sha"],
                head_sha256=original["original_head_sha256"],
                parent_commits=list(case["parents"]),
                parent_trees=[p["tree_sha"] for p in parents],
                parent_entries=entries, classification=state,
                common_previous_blob_sha1=before_sha,
                common_previous_sha256=before_digest,
                common_previous_path=before_file,
                complete_pr_base_diff_certified=False,
                independent_review=None,
            ))
    if index != 80 or len(rows) != 31:
        raise ValueError("fixed 80/31 original Git source census changed")
    return dict(
        schema=SCHEMA, original_file_count=80, merge_file_count=31,
        classification_counts=dict(sorted(Counter(r["classification"] for r in rows).items())),
        rows=rows, both_parents_required=True,
        single_parent_selection_prohibited=True,
        complete_pr_base_diff_certified=False, independent_review=None,
        answer_labels_read=False, model_calls=0, production_accepted=False,
    )


def reopen(manifest, original_dir, parent_dir, output, *, source_sha):
    reopen_parent(manifest, original_dir, parent_dir, manifest_sha=source_sha)
    folder = Path(output)
    store = folder / "common-previous"
    if (
        folder.is_symlink() or not folder.is_dir()
        or store.is_symlink() or not store.is_dir()
        or (folder / "INCOMPLETE.json").exists()
    ):
        raise ValueError("incomplete or unsafe merge-source archive")
    previous, previous_digest = read_canonical(Path(parent_dir) / "context.json")
    report, report_digest = read_canonical(folder / "concordance.json")
    ready, _ = read_canonical(folder / "READY.json")
    if (
        report.get("schema") != SCHEMA
        or ready.get("schema") != "hepta.memorycell.merge-parent-ready.v1"
        or ready.get("source_manifest_sha256") != source_sha
        or ready.get("parent_context_sha256") != previous_digest
        or ready.get("concordance_sha256") != report_digest
        or report.get("original_file_count") != 80
        or report.get("merge_file_count") != 31
        or len(report.get("rows", [])) != 31
        or report.get("both_parents_required") is not True
        or report.get("single_parent_selection_prohibited") is not True
        or report.get("complete_pr_base_diff_certified") is not False
        or report.get("independent_review") is not None
        or report.get("answer_labels_read") is not False
        or report.get("model_calls") != 0
        or report.get("production_accepted") is not False
        or ready.get("production_accepted") is not False
    ):
        raise ValueError("untrusted or promoted two-parent source artifact")
    expected = [
        (c["repo"], c["pull_number"], f["path"])
        for c in manifest["cases"] if len(c["parents"]) == 2
        for f in c["files"]
    ]
    actual = [(r["project"], r["pull_number"], r["head_path"]) for r in report["rows"]]
    if actual != expected:
        raise ValueError("merge HEAD files missing, duplicated or reordered")
    sources = {
        (r["project"], r["pull_number"], r["original_path"]): r
        for r in previous["files"]
    }
    cases = {(c["repo"], c["pull_number"]): c for c in manifest["cases"]}
    receipts = {
        (r["project"], r["pull_number"]): r
        for r in previous["parent_commits"]
    }
    found, counts = {}, Counter()
    for row in report["rows"]:
        key = (row["project"], row["pull_number"])
        case = cases[key]
        original = sources[key + (row["head_path"],)]
        item = next(f for f in case["files"] if f["path"] == row["head_path"])
        entries = row["parent_entries"]
        if (
            original["comparison_status"] != "ambiguous-multi-parent-head"
            or row["head_sha"] != case["head_sha"]
            or row["partition"] != case["partition"]
            or row["head_blob_sha1"] != original["original_head_sha1"]
            or row["head_sha256"] != original["original_head_sha256"]
            or row["parent_commits"] != case["parents"]
            or row["parent_trees"] != [
                p["tree_sha"] for p in receipts[key]["parents"]
            ]
            or not isinstance(entries, list) or len(entries) != 2
            or any(
                e is not None and (
                    not isinstance(e, dict) or set(e) != {"blob_sha", "mode"}
                    or not isinstance(e["blob_sha"], str) or len(e["blob_sha"]) != 40
                    or e["mode"] not in ("100644", "100755")
                )
                for e in entries
            )
            or row["complete_pr_base_diff_certified"] is not False
            or row["independent_review"] is not None
        ):
            raise ValueError("merge context detached from verified source")
        state = classify(
            row["head_blob_sha1"], *entries, renamed=item["status"] == "renamed"
        )
        if state not in STATES or row["classification"] != state:
            raise ValueError("fabricated common-ancestor classification")
        counts[state] += 1
        oid = row["common_previous_blob_sha1"]
        if state in ("identical-to-both-parents", "changed-from-identical-parents"):
            if oid != entries[0]["blob_sha"]:
                raise ValueError("wrong common Git identity")
            if state == "identical-to-both-parents":
                if (
                    row["common_previous_sha256"] != row["head_sha256"]
                    or row["common_previous_path"] is not None
                ):
                    raise ValueError("unbound unchanged source")
            else:
                if row["common_previous_path"] != "common-previous/" + oid + ".blob":
                    raise ValueError("missing common previous byte member")
                blob = store / (oid + ".blob")
                if blob.is_symlink() or not blob.is_file() or blob.stat().st_size > MAX_BLOB:
                    raise ValueError("unsafe previous Git blob")
                raw = blob.read_bytes()
                if blob_sha(raw) != oid or digest(raw) != row["common_previous_sha256"]:
                    raise ValueError("changed previous Git bytes")
                if oid in found and found[oid] != (len(raw), digest(raw)):
                    raise ValueError("same Git identity with incompatible contents")
                found[oid] = len(raw), digest(raw)
        elif any(row[key] is not None for key in (
            "common_previous_blob_sha1", "common_previous_sha256", "common_previous_path"
        )):
            raise ValueError("ambiguous parent was relabelled as known")
    if (
        dict(sorted(counts.items())) != report.get("classification_counts")
        or {p.name for p in store.iterdir()} != {oid + ".blob" for oid in found}
        or ready.get("common_previous_files") != len(found)
        or ready.get("common_previous_bytes") != sum(length for length, _ in found.values())
        or ready.get("merge_file_count") != 31
        or sum(length for length, _ in found.values()) > MAX_BYTES
    ):
        raise ValueError("incomplete or tampered common-source store")
    return dict(
        schema="hepta.memorycell.merge-parent-reopen.v1",
        merge_file_count=31, matched_previous_blobs=len(found),
        classification_counts=dict(sorted(counts.items())),
        unchanged_git_bytes_verified=True, independent_review=None,
        model_calls=0, production_accepted=False,
    )


def collect(manifest, original_dir, parent_dir, output, *, source_sha, fetch):
    if output.exists() or output.is_symlink():
        raise ValueError("merge-source output must be a new directory")
    reopen_parent(manifest, original_dir, parent_dir, manifest_sha=source_sha)
    _, parent_hash = read_canonical(Path(parent_dir) / "context.json")
    output.mkdir()
    store = output / "common-previous"
    store.mkdir()
    kept, total = {}, 0

    def retain(oid, raw):
        nonlocal total
        if oid not in kept:
            if total + len(raw) > MAX_BYTES:
                raise ValueError("common-ancestor byte bound exceeded")
            path = store / (oid + ".blob")
            with path.open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            kept[oid] = len(raw), digest(raw)
            total += len(raw)
        elif kept[oid] != (len(raw), digest(raw)):
            raise ValueError("one Git blob SHA has different content")
        return "common-previous/" + oid + ".blob"

    try:
        report = inspect(
            manifest, read_canonical(Path(parent_dir) / "context.json")[0],
            ObjectReader(fetch, request_limit=MAX_REQUESTS), retain,
        )
        atomic_json(output / "concordance.json", report)
        ready = dict(
            schema="hepta.memorycell.merge-parent-ready.v1",
            source_manifest_sha256=source_sha, parent_context_sha256=parent_hash,
            concordance_sha256=digest((output / "concordance.json").read_bytes()),
            merge_file_count=31, common_previous_files=len(kept),
            common_previous_bytes=total, production_accepted=False,
        )
        atomic_json(output / "READY.json", ready)
        return reopen(manifest, original_dir, parent_dir, output, source_sha=source_sha)
    except Exception as error:
        # An invalid offline reopen must not leave a successful commit marker.
        (output / "READY.json").unlink(missing_ok=True)
        atomic_json(output / "INCOMPLETE.json", dict(
            status="incomplete", error_type=type(error).__name__,
            production_accepted=False,
        ))
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("original", type=Path)
    parser.add_argument("parents", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--reopen-only", action="store_true")
    args = parser.parse_args()
    manifest = read_pinned(args.manifest, args.source_sha256)
    if args.reopen_only:
        result = reopen(
            manifest, args.original, args.parents, args.output,
            source_sha=args.source_sha256,
        )
    else:
        result = collect(
            manifest, args.original, args.parents, args.output,
            source_sha=args.source_sha256,
            fetch=lambda repo, category, oid: github_json(
                repo, category, oid, token=os.environ.get("GITHUB_TOKEN")
            ),
        )
    print(json.dumps(result, sort_keys=True))
