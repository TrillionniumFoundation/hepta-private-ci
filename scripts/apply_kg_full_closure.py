#!/usr/bin/env python3
"""Apply the bounded knowledge.graph runtime-delta closure patch exactly once.

This bootstrap helper is intentionally temporary. The workflow that invokes it
removes the helper after formatting, focused qualification and generated-status
checks pass.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "codex-rs/hepta-memory/src/cognitive_kg_store.rs"
TEST = ROOT / "codex-rs/hepta-memory/src/cognitive_kg_store_tests.rs"
TECHNICAL = ROOT / "docs/modules/knowledge.graph/TECHNICAL.md"
MIGRATION_16 = ROOT / "codex-rs/hepta-memory/migrations/0016_kg_generation_transition_receipts.sql"
MIGRATION_17 = ROOT / "codex-rs/hepta-memory/migrations/0017_kg_generation_kernel_delta_receipts.sql"


class PatchError(RuntimeError):
    pass


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise PatchError(f"{label}: expected one exact predecessor, found {count}")
    return text.replace(old, new, 1)


def patch_store() -> None:
    text = STORE.read_text(encoding="utf-8")
    if "persist_kernel_delta_plan_tx" in text:
        return

    text = replace_once(
        text,
        "use codex_hepta_kg::KnowledgeEdgeIdentityV2;\n",
        "use codex_hepta_kg::KnowledgeDependencyIndexV2;\n"
        "use codex_hepta_kg::KnowledgeEdgeIdentityV2;\n",
        "dependency-index import",
    )
    text = replace_once(
        text,
        "use codex_hepta_kg::KnowledgeGenerationV2;\n",
        "use codex_hepta_kg::KnowledgeGenerationV2;\n"
        "use codex_hepta_kg::KnowledgeIncrementalPlanV2;\n",
        "incremental-plan import",
    )
    text = replace_once(
        text,
        "use codex_hepta_kg::publish_generation;\n",
        "use codex_hepta_kg::plan_generation_transition_v2;\n"
        "use codex_hepta_kg::publish_generation;\n",
        "transition-planner import",
    )

    helper_anchor = """pub(crate) fn sha256_from_digest32(value: Digest32) -> Result<Sha256Digest, CognitiveStoreError> {
    Sha256Digest::parse(value.to_string()).map_err(CognitiveStoreError::Corrupt)
}

fn framed_sha256_hex(domain: &[u8], parts: &[&[u8]]) -> String {
"""
    helper_replacement = """pub(crate) fn sha256_from_digest32(value: Digest32) -> Result<Sha256Digest, CognitiveStoreError> {
    Sha256Digest::parse(value.to_string()).map_err(CognitiveStoreError::Corrupt)
}

async fn persist_kernel_delta_plan_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    projection_scope: &str,
    plan: &KnowledgeIncrementalPlanV2,
) -> Result<(), CognitiveStoreError> {
    let delta = &plan.storage_delta;
    sqlx::query(
        "INSERT INTO kg_projection_generation_kernel_deltas (
            projection_scope, generation, predecessor_generation_sha256,
            generation_sha256, delta_mode, remove_node_count,
            upsert_node_count, remove_edge_count, upsert_edge_count,
            impact_node_count, impact_edge_count,
            full_candidate_oracle_verified, recorded_at_unix_seconds
         ) VALUES (?, ?, ?, ?, 'canonical_transition_v1', ?, ?, ?, ?, ?, ?, 1, unixepoch())",
    )
    .bind(projection_scope)
    .bind(to_i64(delta.generation.get(), "KG generation")?)
    .bind(delta.expected_predecessor_digest.to_string())
    .bind(delta.generation_digest.to_string())
    .bind(to_i64_len(
        delta.remove_node_ids.len(),
        "removed KG node count",
    )?)
    .bind(to_i64_len(
        delta.upsert_nodes.len(),
        "upserted KG node count",
    )?)
    .bind(to_i64_len(
        delta.remove_edge_identities.len(),
        "removed KG edge count",
    )?)
    .bind(to_i64_len(
        delta.upsert_edges.len(),
        "upserted KG edge count",
    )?)
    .bind(to_i64_len(
        delta.impact.node_ids.len(),
        "impacted KG node count",
    )?)
    .bind(to_i64_len(
        delta.impact.edge_identities.len(),
        "impacted KG edge count",
    )?)
    .execute(&mut **transaction)
    .await
    .map_err(unavailable)?;
    Ok(())
}

fn framed_sha256_hex(domain: &[u8], parts: &[&[u8]]) -> String {
"""
    text = replace_once(text, helper_anchor, helper_replacement, "delta receipt helper")

    predecessor_anchor = """        let predecessor = if current == 0 {
            None
        } else {
            Some(load_canonical_generation_tx(transaction, &projection_scope, current).await?)
        };
        let publication =
            publish_generation(predecessor.as_ref(), &candidate).map_err(|error| {
                CognitiveStoreError::Corrupt(format!(
                    "canonical hepta-kg V2 publication rejected SQLite projection: {error}"
                ))
            })?;
"""
    predecessor_replacement = """        let predecessor = if current == 0 {
            None
        } else {
            Some(load_canonical_generation_tx(transaction, &projection_scope, current).await?)
        };
        let incremental_plan = match predecessor.as_ref() {
            Some(predecessor) => {
                let dependency_index = KnowledgeDependencyIndexV2::build(predecessor).map_err(
                    |error| {
                        CognitiveStoreError::Corrupt(format!(
                            "canonical hepta-kg dependency index rejected SQLite predecessor: {error}"
                        ))
                    },
                )?;
                Some(
                    plan_generation_transition_v2(predecessor, &dependency_index, &candidate)
                        .map_err(|error| {
                            CognitiveStoreError::Corrupt(format!(
                                "canonical hepta-kg transition plan diverged from SQLite candidate: {error}"
                            ))
                        })?,
                )
            }
            None => None,
        };
        let publication =
            publish_generation(predecessor.as_ref(), &candidate).map_err(|error| {
                CognitiveStoreError::Corrupt(format!(
                    "canonical hepta-kg V2 publication rejected SQLite projection: {error}"
                ))
            })?;
"""
    text = replace_once(
        text,
        predecessor_anchor,
        predecessor_replacement,
        "runtime transition planning",
    )

    storage_anchor = """        .execute(&mut **transaction)
        .await
        .map_err(unavailable)?;
        #[cfg(test)]
        kg_projection_crash_rendezvous("after_semantic_receipt_before_current_pointer");
        let updated = sqlx::query(
"""
    storage_replacement = """        .execute(&mut **transaction)
        .await
        .map_err(unavailable)?;
        if let Some(plan) = incremental_plan.as_ref() {
            persist_kernel_delta_plan_tx(transaction, &projection_scope, plan).await?;
        }
        #[cfg(test)]
        kg_projection_crash_rendezvous("after_semantic_receipt_before_current_pointer");
        let updated = sqlx::query(
"""
    # The anchor occurs exactly once immediately after the generation-storage insert.
    text = replace_once(
        text,
        storage_anchor,
        storage_replacement,
        "kernel delta persistence",
    )

    STORE.write_text(text, encoding="utf-8")


def patch_test() -> None:
    text = TEST.read_text(encoding="utf-8")
    if "second kernel delta receipt" in text:
        return

    anchor = """    let transition_immutable = sqlx::query(
        "UPDATE kg_projection_generation_transitions
         SET full_oracle_verified = 1
         WHERE projection_scope = ? AND generation = 2",
    )
"""
    insertion = """    assert_eq!(
        sqlx::query_scalar::<_, i64>(
            "SELECT COUNT(*) FROM kg_projection_generation_kernel_deltas
             WHERE projection_scope = ? AND generation = 1",
        )
        .bind(scope.projection_key())
        .fetch_one(&store.pool)
        .await
        .expect("baseline kernel delta count"),
        0
    );

    let second_kernel_delta = sqlx::query(
        "SELECT predecessor_generation_sha256, generation_sha256, delta_mode,
                remove_node_count, upsert_node_count, remove_edge_count,
                upsert_edge_count, impact_node_count, impact_edge_count,
                full_candidate_oracle_verified
         FROM kg_projection_generation_kernel_deltas
         WHERE projection_scope = ? AND generation = 2",
    )
    .bind(scope.projection_key())
    .fetch_one(&store.pool)
    .await
    .expect("second kernel delta receipt");
    assert_eq!(
        second_kernel_delta
            .try_get::<String, _>("predecessor_generation_sha256")
            .expect("kernel predecessor digest"),
        first.projection.generation_sha256.as_str()
    );
    assert_eq!(
        second_kernel_delta
            .try_get::<String, _>("generation_sha256")
            .expect("kernel generation digest"),
        second.projection.generation_sha256.as_str()
    );
    assert_eq!(
        second_kernel_delta
            .try_get::<String, _>("delta_mode")
            .expect("kernel delta mode"),
        "canonical_transition_v1"
    );
    assert_eq!(
        second_kernel_delta
            .try_get::<i64, _>("remove_node_count")
            .expect("removed nodes"),
        1
    );
    assert_eq!(
        second_kernel_delta
            .try_get::<i64, _>("upsert_node_count")
            .expect("upserted nodes"),
        1
    );
    assert_eq!(
        second_kernel_delta
            .try_get::<i64, _>("remove_edge_count")
            .expect("removed edges"),
        1
    );
    assert_eq!(
        second_kernel_delta
            .try_get::<i64, _>("upsert_edge_count")
            .expect("upserted edges"),
        0
    );
    assert_eq!(
        second_kernel_delta
            .try_get::<i64, _>("impact_node_count")
            .expect("impacted nodes"),
        2
    );
    assert_eq!(
        second_kernel_delta
            .try_get::<i64, _>("impact_edge_count")
            .expect("impacted edges"),
        1
    );
    assert_eq!(
        second_kernel_delta
            .try_get::<i64, _>("full_candidate_oracle_verified")
            .expect("kernel oracle verification"),
        1
    );

    let kernel_delta_immutable = sqlx::query(
        "UPDATE kg_projection_generation_kernel_deltas
         SET full_candidate_oracle_verified = 1
         WHERE projection_scope = ? AND generation = 2",
    )
    .bind(scope.projection_key())
    .execute(&store.pool)
    .await
    .expect_err("kernel delta receipts are append-only");
    assert!(
        kernel_delta_immutable
            .to_string()
            .contains("KG generation kernel delta receipts are immutable")
    );

    let transition_immutable = sqlx::query(
        "UPDATE kg_projection_generation_transitions
         SET full_oracle_verified = 1
         WHERE projection_scope = ? AND generation = 2",
    )
"""
    text = replace_once(text, anchor, insertion, "kernel delta assertions")
    TEST.write_text(text, encoding="utf-8")


def patch_technical_doc() -> None:
    text = TECHNICAL.read_text(encoding="utf-8")
    marker = "## Runtime delta closure (2026-09-29)"
    if marker in text:
        return
    addition = """

## Runtime delta closure (2026-09-29)

The cognitive SQLite writer now derives and validates a canonical
`KnowledgeStorageDeltaV2` for every non-baseline generation, persists an immutable
kernel-delta receipt bound to predecessor/candidate generation digests, and cannot
advance the current pointer unless SQLite verifies that receipt. Automatic transition
receipts also retain trigger support counts, touched canonical identities and the bounded
trigger payload bytes. See
[`RUNTIME_DELTA_CLOSURE_20260929.md`](RUNTIME_DELTA_CLOSURE_20260929.md) for the exact
transaction, recovery, physical-resource and authority boundary.

The complete canonical candidate remains the per-mutation equivalence oracle. Therefore
this closes transition correctness and durable observability, but does not claim that
full source-cut scanning has already been replaced by asymptotically local computation.
Independent operator acceptance, activation and release remain false until external
current-candidate evidence is signed and verified.
"""
    TECHNICAL.write_text(text.rstrip() + addition + "\n", encoding="utf-8")


def main() -> int:
    for migration in (MIGRATION_16, MIGRATION_17):
        if not migration.is_file():
            raise PatchError(f"missing required migration: {migration.relative_to(ROOT)}")
    patch_store()
    patch_test()
    patch_technical_doc()
    print("PASS_APPLY_KG_FULL_CLOSURE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
