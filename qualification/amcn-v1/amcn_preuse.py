"""Fail-closed pre-use shadow Cell artifact lease; never grants production authority.

Each call MUST re-check a separately pinned authoritative source frontier and
the full ancestry census, plus an external persistent quarantine tombstone.
A locally 'unaffected' artifact cannot become production-authorized here.
"""
from __future__ import annotations

from amcn_core import digest, is_sha, require, shadow_disposition
from amcn_revocation import CellGeneration, revocation_census


def preuse_cell_candidate(artifact_id, artifacts, current_sources, *,
                          scope, generation, pinned_frontier_sha256,
                          persisted_quarantine_ids, quarantine_ledger_sha256,
                          runtime_generation):
    require(is_sha(artifact_id) and isinstance(runtime_generation, str)
            and runtime_generation == generation, "artifact runtime generation drift")
    require(isinstance(persisted_quarantine_ids, (list, tuple))
            and len(set(persisted_quarantine_ids)) == len(persisted_quarantine_ids)
            and all(is_sha(x) for x in persisted_quarantine_ids),
            "quarantine ledger invalid")
    require(is_sha(quarantine_ledger_sha256)
            and digest(sorted(persisted_quarantine_ids)) == quarantine_ledger_sha256,
            "quarantine ledger not externally bound")
    require(any(isinstance(a, CellGeneration) and a.artifact_id == artifact_id
                for a in artifacts), "unknown candidate")
    result = revocation_census(
        artifacts, current_sources, scope=scope, generation=generation,
        externally_pinned_frontier_sha256=pinned_frontier_sha256,
        old_quarantined=persisted_quarantine_ids)
    status = result["metrics"]
    invalid = set(status["quarantined_artifact_ids"])
    return shadow_disposition(
        profile="hepta.amcn.preuse-shadow-lease.v1",
        artifact_id=artifact_id,
        artifact_admissible_for_isolated_research_only=artifact_id not in invalid,
        source_frontier_sha256=status["source_frontier_sha256"],
        quarantine_ledger_sha256=quarantine_ledger_sha256,
        manifest_inventory_sha256=status["artifact_manifest_sha256"],
        must_recheck_before_every_execution=True,
        persistent_owner_ledger_authenticated_here=False,
        runtime_owner_mutated=False,
        production_execution_permitted=False,
        model_unlearning_proven=False,
        final_use_permitted=False,
    )
