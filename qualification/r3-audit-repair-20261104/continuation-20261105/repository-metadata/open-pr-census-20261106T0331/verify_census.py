#!/usr/bin/env python3
"""Read-only replay of the frozen direct-REST metadata census. No network."""
import argparse
import collections
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

def identity(b):
    return {"bytes": len(b), "git_blob": hashlib.sha1(b"blob " + str(len(b)).encode() + b"\0" + b).hexdigest(),
            "sha256": hashlib.sha256(b).hexdigest()}

def get_projection(r):
    return {
        "number": r["number"], "id": r["id"], "node_id": r["node_id"], "url": r["html_url"],
        "title": r["title"], "state": r["state"], "draft": r.get("draft"),
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "head": {"repository": (r["head"].get("repo") or {}).get("full_name"),
                 "repository_id": (r["head"].get("repo") or {}).get("id"),
                 "ref": r["head"]["ref"], "sha": r["head"]["sha"]},
        "base": {"repository": (r["base"].get("repo") or {}).get("full_name"),
                 "repository_id": (r["base"].get("repo") or {}).get("id"),
                 "ref": r["base"]["ref"], "sha": r["base"]["sha"]},
        "merge_commit_sha": r["merge_commit_sha"],
    }

def anchor_delta(original, current):
    old = {r["number"]: r for r in original}
    new = {r["number"]: r for r in current}
    changes = []
    for n in sorted(old.keys() & new.keys()):
        op, np = get_projection(old[n]), get_projection(new[n])
        fields = {k: {"before": op[k], "after": np[k]} for k in op if op[k] != np[k]}
        if old[n].get("body") != new[n].get("body"):
            fields["body"] = {"changed": True, "full_originals_retained": True}
        if fields:
            changes.append({"number": n, "fields": fields})
    return {
        "same_ordered_membership": [r["number"] for r in original] == [r["number"] for r in current],
        "added": sorted(new.keys() - old.keys()),
        "removed": sorted(old.keys() - new.keys()),
        "semantic_metadata_changes": changes,
        "comparison_fields": list(get_projection(original[0])) + ["body"] if original else [],
        "embedded_repository_pushed_at_or_counter_refresh_is_not_PR_membership_change": True,
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--inventory", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = json.loads((root / "original-manifest.json").read_bytes())
    for row in manifest["files"]:
        p = root / row["path"]
        assert p.is_file() and not p.is_symlink(), row["path"]
        assert identity(p.read_bytes()) == row["identity"], row["path"]
    collection = json.loads((root / "collection.json").read_bytes())
    repo = collection["repository"]
    records, parsed, receipts = collection["records"], {}, []
    for record in records:
        original_bytes = (root / record["file"]).read_bytes()
        raw = json.loads(original_bytes)
        assert not raw.get("isError"), record["file"]
        text = raw["structuredContent"]["content"]
        assert text == raw["structuredContent"]["structuredContent"]["content"]
        response = text.encode("utf-8")
        rows = json.loads(text)
        assert isinstance(rows, list)
        assert len(rows) == record["count"]
        assert record["before"]["current_time"] <= record["after"]["current_time"]
        url = urlparse(record["url"])
        assert url.netloc == "api.github.com"
        assert url.path == "/repos/" + repo + "/pulls"
        assert parse_qs(url.query) == {
            "state": ["open"], "sort": ["created"], "direction": ["asc"],
            "per_page": ["100"], "page": [str(record["page"])]}
        assert raw["structuredContent"]["url"] == record["url"]
        if "response_identity" in record:
            assert identity(response) == record["response_identity"]
        if "raw_json_identity" in record:
            assert original_bytes.endswith(b"\n")
            assert identity(original_bytes[:-1]) == record["raw_json_identity"]
        key = "page-" + str(record["page"]) if record["kind"] == "primary" else record["kind"]
        assert key not in parsed
        parsed[key] = rows
        receipts.append({
            "kind": record["kind"], "page": record["page"], "path": record["file"],
            "before_utc": record["before"]["current_time"], "after_utc": record["after"]["current_time"],
            "url": record["url"], "count": len(rows),
            "original_serialized_MCP": identity(original_bytes), "complete_delivered_REST_text": identity(response),
            "first_number": rows[0]["number"] if rows else None,
            "last_number": rows[-1]["number"] if rows else None,
        })
    primary = [r for r in records if r["kind"] == "primary"]
    assert [r["page"] for r in primary] == list(range(1, len(primary) + 1))
    assert all(r["count"] == 100 for r in primary[:-1])
    assert 0 < primary[-1]["count"] < 100
    empty_record = next(r for r in records if r["kind"] == "terminal-empty")
    assert empty_record["page"] == len(primary) + 1
    assert parsed["terminal-empty"] == []
    assert next(r for r in records if r["kind"] == "anchor-first")["page"] == 1
    assert next(r for r in records if r["kind"] == "anchor-last")["page"] == len(primary)
    occurrences, seen, duplicates = [], {}, []
    for record in primary:
        for index, r in enumerate(parsed["page-" + str(record["page"])]):
            assert r["state"] == "open"
            assert r["html_url"] == "https://github.com/" + repo + "/pull/" + str(r["number"])
            assert isinstance(r["number"], int) and isinstance(r["id"], int)
            assert r["created_at"].endswith("Z") and r["updated_at"].endswith("Z")
            occurrence = {"page": record["page"], "zero_based_index": index, "number": r["number"]}
            occurrences.append((r, occurrence))
            if r["number"] in seen:
                duplicates.append({"number": r["number"], "first": seen[r["number"]][1], "later": occurrence,
                                   "same_full_PR_object": seen[r["number"]][0] == r})
            else:
                seen[r["number"]] = (r, occurrence)
    rows = [r for r, _ in seen.values()]
    inventory = [dict(get_projection(r), observation=location) for r, location in seen.values()]
    if args.inventory:
        print(json.dumps({"schema": "hepta-open-pr-metadata-first-pass-inventory-v1",
                          "first_pass_metadata_not_replaced_by_later_anchors": True,
                          "count": len(inventory), "items": inventory}, ensure_ascii=False, indent=2))
        return
    violations = []
    ties = 0
    for (a, al), (b, bl) in zip(occurrences, occurrences[1:]):
        if b["created_at"] < a["created_at"]:
            violations.append({"before": al, "after": bl})
        if b["created_at"] == a["created_at"]:
            ties += 1
    base = collections.Counter(r["base"]["ref"] for r in rows)
    head_repository = collections.Counter((r["head"].get("repo") or {}).get("full_name") for r in rows)
    drafts = collections.Counter(str(r.get("draft")).lower() for r in rows)
    created_dates = collections.Counter(r["created_at"][:10] for r in rows)
    updated_dates = collections.Counter(r["updated_at"][:10] for r in rows)
    missing_head = sum(r["head"].get("repo") is None for r in rows)
    same_head = sum((r["head"].get("repo") or {}).get("full_name", "").lower() == repo.lower() for r in rows)
    boundary = collection["historical_comparison_upper_utc"]
    first_anchor = anchor_delta(parsed["page-1"], parsed["anchor-first"])
    last_anchor = anchor_delta(parsed["page-" + str(len(primary))], parsed["anchor-last"])
    report = {
        "schema": "hepta-direct-rest-open-pr-metadata-census-verification-v1",
        "result": "COMPLETE_PAGINATION_METADATA_ONLY_NON_ATOMIC_OBSERVATION",
        "repository": repo,
        "query": collection["query"],
        "primary_window_utc": [primary[0]["before"]["current_time"], primary[-1]["after"]["current_time"]],
        "anchor_and_empty_terminal_window_utc": [next(r for r in records if r["kind"] == "anchor-first")["before"]["current_time"], records[-1]["after"]["current_time"]],
        "original_response_count": len(records),
        "primary_page_count": len(primary),
        "page_sizes": [r["count"] for r in primary],
        "empty_terminal_page": empty_record["page"],
        "empty_terminal_response": [],
        "pagination_complete_for_recorded_sequence": True,
        "atomic_snapshot": False,
        "unobserved_interior_concurrent_changes_excluded": False,
        "guarantee_of_no_concurrent_omissions": False,
        "transport_failure_count": len(collection["transport_failures"]),
        "per_page_fallback_used": collection["per_page_fallback_used"],
        "search_used": False,
        "repository_open_issues_count_used_as_PR_denominator": False,
        "PR_occurrences_in_primary_pages": len(occurrences),
        "unique_open_PR_numbers": len(rows),
        "unique_PR_database_ids": len({r["id"] for r in rows}),
        "duplicate_occurrences": duplicates,
        "created_sort_inversions": violations,
        "equal_created_timestamp_adjacent_pairs": ties,
        "draft": drafts["true"], "non_draft": drafts["false"],
        "draft_unknown": len(rows) - drafts["true"] - drafts["false"],
        "base_main": base["main"], "base_nonmain": len(rows) - base["main"],
        "distinct_base_refs": len(base),
        "base_ref_distribution": [{"ref": k, "count": v} for k, v in sorted(base.items(), key=lambda x: (-x[1], x[0]))],
        "head_same_repository": same_head,
        "head_other_repository": len(rows) - same_head - missing_head,
        "head_repository_unavailable": missing_head,
        "head_repository_distribution": [{"repository": k, "count": v} for k, v in sorted(head_repository.items(), key=lambda x: str(x[0]))],
        "distinct_head_refs": len({r["head"]["ref"] for r in rows}),
        "created_range_UTC": [min(r["created_at"] for r in rows), max(r["created_at"] for r in rows)],
        "updated_range_UTC_first_pass": [min(r["updated_at"] for r in rows), max(r["updated_at"] for r in rows)],
        "created_by_UTC_day": dict(sorted(created_dates.items())),
        "updated_by_UTC_day": dict(sorted(updated_dates.items())),
        "non_draft_numbers": sorted(r["number"] for r in rows if r.get("draft") is False),
        "anchors": {"first": first_anchor, "last": last_anchor},
        "observed_semantic_metadata_drift_numbers": sorted({x["number"] for a in [first_anchor, last_anchor] for x in a["semantic_metadata_changes"]}),
        "historical_comparison": {
            "prior_reported_count": collection["prior_reported_open_PR_count"],
            "old_upper_boundary_UTC": boundary,
            "current_rows_created_after_old_boundary": sum(r["created_at"] > boundary for r in rows),
            "current_rows_updated_at_or_before_old_boundary": sum(r["updated_at"] <= boundary for r in rows),
            "arithmetic_count_difference": len(rows) - collection["prior_reported_open_PR_count"],
            "difference_is_not_claimed_new_PR_growth": True,
            "old_pagination_requalified_by_this_verifier": False,
            "difference_cause": "UNKNOWN_PENDING_SEPARATE_OLD_SOURCE_REVIEW",
        },
        "body_and_wrapper_integrity": {
            "all_complete_delivered_texts_JSON_parsed": True,
            "both_embedded_body_copies_equal_in_each_original": True,
            "first_eight_original_JS_body_and_serialized_object_hashes_equal": True,
            "MCP_serialization_is_not_HTTP_wire_capture": True,
            "original_manifest_rows": len(manifest["files"]),
            "original_manifest": identity((root / "original-manifest.json").read_bytes()),
        },
        "page_receipts": receipts,
        "limits": [
            "All observed records are metadata. Neither source changes nor CI/product acceptance of 3555 PRs was reviewed.",
            "The sequence was paginated to a short page followed by an actual empty next page. It is not an atomic snapshot.",
            "First/last anchors retained membership and order, but do not exclude invisible concurrent changes in interior pages.",
            "Primary counts use the first occurrence per PR number in the main traversal; later anchor metadata does not overwrite it.",
            "No new branch census was performed; historical branch count 5193 is not a current branch measurement.",
            "The old count 1103 is retained as a historical reported observation. The numerical difference is not interpreted as growth.",
            "No per-PR source/commit/native/CI query, ref update, PR write, dispatch, retry, or cancellation was performed.",
        ],
    }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))

if __name__ == "__main__":
    main()
