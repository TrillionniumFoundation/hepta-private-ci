#!/usr/bin/env python3
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
inventory = json.loads((ROOT / "INVENTORY.json").read_text(encoding="utf-8"))

assert inventory["status"] == "HOLD_NO_GO"
assert inventory["all_closed"] is False
assert inventory["global_status"] == "HOLD / NoUpdate / all_closed=false"
assert all(value == 0 for value in inventory["execution"].values())

searches = inventory["bounded_searches"]
assert len(searches) == 2
assert all(search["state"] == "completed" for search in searches)
assert all(search["traversal_complete"] is True for search in searches)
assert all(search["coverage_complete"] is True for search in searches)
assert all(search["entries"] == 16 for search in searches)
assert all(search["results"] == 6 for search in searches)

files = inventory["files"]
assert len(files) == 6
assert [item["late_epoch"] for item in files] == [116, 76, 126, 50, 127, 72]
assert len({item["fit"] for item in files}) == 6
assert len({item["path"] for item in files}) == 6
assert len({item["sha256"] for item in files}) == 6
assert all(len(item["sha256"]) == 64 for item in files)
assert all(item["bytes"] > 0 for item in files)

parents = set(inventory["source_context"]["original_start_parent_sha256"])
late = set(inventory["source_context"]["last_observed_late_checkpoint_sha256"])
observed = {item["sha256"] for item in files}
assert len(parents) == 6
assert len(late) == 6
assert not parents & late
assert observed == late

result = inventory["directory_scope_result"]
assert result == {
    "v1_pt_files": 6,
    "v2_pt_files": 6,
    "unique_pt_hashes": 6,
    "original_start_parent_hash_matches": 0,
    "late_checkpoint_hash_matches": 12,
}
assert inventory["duplicate_sets_byte_identical"] is True

broader = inventory["broader_host_search"]
assert broader["state"] == "limited"
assert broader["reason"] == "entry_limit"
assert broader["coverage_complete"] is False
assert broader["results"] == 0
assert "No global host-absence conclusion" in broader["claim"]

assert "the six original start-parent PT bytes remain missing" in inventory["preserved_unknowns"]
assert "this evidence does not admit or start a full replay" in inventory["non_transfer"]
print("PASS: both bounded live-run inventories contain only the six later checkpoints; HOLD preserved")
