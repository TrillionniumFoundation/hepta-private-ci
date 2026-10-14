"""Source-witness ancestry for research-only typed MemoryCell Head generations.

Reuses the existing AMCN SourceWitness/CellGeneration/revocation_census.
This emits candidate lineage only; it is not a source or Artifact owner.
"""
from __future__ import annotations

from amcn_core import digest, is_sha, require, shadow_disposition
from amcn_learning import FeatureMatrix
from amcn_revocation import SourceWitness, freeze_generation
from amcn_typed_budget import type_inventory_digest
from experiments.shared_stem_cell.execution import parameters

PROFILE = "hepta.amcn.typed-head-source-lineage.shadow.v1"
ARMS = ("untyped_equal_budget", "typed_equal_budget")


def source_binding_digest(matrix, source_by_train_row):
    """Bind frozen TRAIN input digests to complete versioned source witnesses."""
    require(isinstance(matrix, FeatureMatrix), "frozen FeatureMatrix required")
    train = [r for r in matrix.rows if r.split == "train"]
    require(isinstance(source_by_train_row, dict) and train and
            set(source_by_train_row) == {r.row_id for r in train},
            "incomplete or non-TRAIN source witness inventory")
    seen = {}
    entries = []
    for row in train:
        w = source_by_train_row[row.row_id]
        require(isinstance(w, SourceWitness) and not w.revoked and
                (w.source_root, w.scope, w.generation) ==
                (row.source_root, row.scope, row.generation),
                "source witness fails case/scope/epoch binding")
        other = seen.setdefault(w.evidence_id, w.immutable_key())
        require(other == w.immutable_key(), "conflicting source revision for same evidence ID")
        entries.append((row.row_id, row.input_sha256, w.immutable_key()))
    return digest({"profile": PROFILE, "features": matrix.identity,
                   "bindings": sorted(entries)})


def freeze_typed_head_lineage(matrix, type_by_row, trained_run,
                              source_by_train_row, *, pinned_source_binding_sha256):
    """Freeze 4 actual Head/version/source manifests, never register or select.

    An unspecialized Head depends on ALL TRAIN sources; a specialized Head
    depends on its type-only TRAIN sources. No synthetic source witness is
    created here. The caller must obtain these from the actual source owner.
    """
    require(is_sha(pinned_source_binding_sha256) and
            pinned_source_binding_sha256 == source_binding_digest(matrix, source_by_train_row),
            "externally pinned TRAIN source-to-feature binding mismatch")
    require(isinstance(trained_run, dict) and
            set(trained_run) == {"predictions", "receipt", "trained_heads", "single_head", "frozen_head"},
            "unknown trained trial shape")
    receipt = trained_run["receipt"]
    require(isinstance(receipt, dict) and receipt.get("production_accepted") is False,
            "only negative-authority research candidates are eligible")
    recorded = receipt.get("metrics")
    require(isinstance(recorded, dict) and
            recorded.get("frozen_feature_sha256") == matrix.identity and
            recorded.get("precommitted_type_inventory_sha256") ==
            type_inventory_digest(matrix, type_by_row),
            "trained Head source/typed experiment drift")
    kinds = sorted(set(type_by_row.values()))
    require(len(kinds) == 2 and recorded.get("functional_types") == kinds,
            "invalid frozen type inventory")
    heads = trained_run["trained_heads"]
    require(isinstance(heads, dict) and set(heads) == set(ARMS),
            "incomplete original physical Head banks")
    rows = [r for r in matrix.rows if r.split == "train"]
    result, support_counts = [], {}
    for arm in ARMS:
        require(set(heads[arm]) == set(kinds), "incomplete original trained type bank")
        for k in kinds:
            model_sha = parameters(heads[arm][k])["sha256"]
            require(is_sha(model_sha) and model_sha ==
                    recorded[f"{'untyped' if arm.startswith('untyped') else 'typed'}_budget"]
                    ["head_sha256"][k], "physical trained weights/receipt mismatch")
            rows_for_head = rows if arm == "untyped_equal_budget" else [
                r for r in rows if type_by_row[r.row_id] == k]
            supports = {}
            for row in rows_for_head:
                witness = source_by_train_row[row.row_id]
                supports[witness.evidence_id] = witness
            require(1 <= len(supports) <= 512, "Head source lineage capacity")
            support = tuple(sorted(supports.values(), key=lambda w: w.evidence_id))
            artifact_id = digest([PROFILE, matrix.identity, arm, k,
                                  model_sha, pinned_source_binding_sha256])
            candidate = freeze_generation(artifact_id, "typed_memory_head", matrix.scope,
                                          matrix.generation, matrix.encoder_sha256,
                                          model_sha, (), support)
            result.append(candidate)
            support_counts[arm + "/" + k] = len(support)
    require(len({x.artifact_id for x in result}) == len(result),
            "duplicated Head lineage artifacts")
    return {"artifacts": tuple(result), "receipt": shadow_disposition(
        profile=PROFILE, frozen_feature_sha256=matrix.identity,
        source_binding_sha256=pinned_source_binding_sha256,
        artifact_manifest_sha256=digest(sorted(a.manifest_sha256 for a in result)),
        artifact_count=len(result), source_support_counts=support_counts,
        original_source_owner_authenticated=False,
        feature_source_alignment_independently_attested=False,
        inherited_parent_weights_qualified=False,
        original_artifact_cas_persisted=False,
        future_use_fenced=False, deletion_or_unlearning_performed=False)}
