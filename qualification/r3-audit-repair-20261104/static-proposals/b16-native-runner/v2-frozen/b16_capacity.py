"""Read-only final-A cache binding and explicit, conditional space planning."""

import json
from pathlib import Path
import shutil

from b16_guard import need, same_record
from b16_native import check_helper_roster


def cache_and_capacity(binding, baseline_metadata):
    pin = binding["last_tested_A_artifacts"]
    need(same_record(pin["path"], pin), "last-tested A full artifact receipt changed")
    artifact = json.loads(Path(pin["path"]).read_bytes())
    need(artifact["source"] == binding["last_tested_A_tree"], "actual tested artifact source identity differs")
    need(artifact["cargo_profile"] == "dev-small" and artifact["nextest_profile"] == "local", "cache profile differs")
    # The cache's last compilation may precede final A formatting. That fact is
    # explicit; each B scope rebuilds helpers/catalogue and records current bytes.
    need(binding.get("last_tested_A_to_final_A_review"), "review the actual tested source versus final A")
    members = set(baseline_metadata["workspace_members"])
    member_names = {p["name"] for p in baseline_metadata["packages"] if p["id"] in members}
    requested = set(artifact["packages"])
    allowed_new = {"sqlx-sqlite"} if binding["authorized_epoch"] in ("pool", "checkpoint", "owning") else set()
    need(requested and requested <= member_names and member_names - requested <= allowed_new,
         "cache receipt is not the original full A workspace selection")
    helpers = artifact["helpers_after_catalog_before_just"]
    programs = artifact["test_binaries_after_catalog_before_just"]
    need(programs, "full A test-program identities missing")
    observed_names = check_helper_roster(helpers, binding["A_helper_basename_roster"])
    target = Path(binding["target_directory"]).resolve()
    need(target.is_dir() and target == Path(binding["final_A_target_directory"]).resolve(), "reuse the existing final A target")
    cache = Path(binding["bazel_cache_directory"]).resolve()
    cache_existing = cache if cache.exists() else cache.parent
    locations = [Path(binding["source_directory"]).resolve(),
                 Path(binding["evidence_directory"]).resolve().parent, cache_existing]
    need(all(p.is_dir() and p.stat().st_dev == target.stat().st_dev for p in locations),
         "this reviewed capacity plan requires source, target, evidence and B cache on the same filesystem")
    rows = {}
    for row in [*programs, *helpers]:
        need(Path(row["path"]).resolve().is_relative_to(target), "artifact belongs to another target")
        need(isinstance(row["bytes"], int) and row["bytes"] > 0 and row.get("sha256"), "artifact byte identity missing")
        if row["path"] in rows:
            need(rows[row["path"]] == row, "inconsistent duplicate artifact identity")
        rows[row["path"]] = row
    artifact_bytes = sum(row["bytes"] for row in rows.values())
    budget = binding["capacity_plan"]
    families = budget["additional_executable_families"]
    need(isinstance(families, int) and families >= 0, "invalid remaining executable allowance")
    if binding["authorized_epoch"] in ("foundation", "driver"):
        need(families >= 1, "before adoption allow at least one additional executable family")
    extras = [budget[k] for k in ("other_cargo_growth_bytes", "bazel_growth_bytes", "evidence_growth_bytes")]
    need(all(isinstance(x, int) and x >= 0 for x in extras), "invalid reviewed remaining-growth allowance")
    need(budget.get("estimate_review_reference"), "conditional capacity estimate needs explicit review")
    growth = families * artifact_bytes + sum(extras)
    free = shutil.disk_usage(target).free
    required = growth + binding["min_free_bytes"]
    need(free >= required, "insufficient reviewed growth budget; stop without deleting caches or reducing scope")
    return {"target_reuse_mode": "reuse_final_A", "target_directory": str(target),
            "final_A_tree": binding["final_A_tree"], "last_tested_A_tree": artifact["source"],
            "last_tested_A_to_final_A_review": binding["last_tested_A_to_final_A_review"],
            "original_full_artifact_receipt": pin, "complete_helper_basename_roster": observed_names,
            "known_executable_files": len(rows), "known_executable_bytes": artifact_bytes,
            "actual_free_bytes": free, "required_free_bytes": required, "remaining_growth_plan": budget,
            "same_filesystem_locations": [str(p) for p in locations],
            "initial_cache_copy_bytes": 0, "existing_cache_deleted": False,
            "limit": "File-byte observations are not total target allocation or a proven compiler peak. Extra rlib/object/Bazel/evidence allowances are explicitly reviewed estimates. Per-command 8 GB reserve checks remain; a failed estimate stops the epoch without cleanup or selection changes."}
