//! Corrected durable-owner facade.
//!
//! The reviewed V1 store implementation remains the single schema and helper
//! implementation. This facade reuses it verbatim and overrides only the
//! active-head bootstrap rule: a newly materialized local owner may begin at
//! the next generation bound by its authoritative source snapshot. Requiring
//! generation one made the public qualified path unreachable because
//! `Generation(0)` is deliberately unrepresentable.

mod original {
    include!("durable.rs");

    pub(super) mod corrected {
        use super::*;

        #[derive(Clone)]
        pub struct DurableCompactionStoreV1 {
            inner: super::DurableCompactionStoreV1,
        }

        impl DurableCompactionStoreV1 {
            pub async fn open(
                database_url: &str,
                owner_id: impl Into<String>,
            ) -> Result<Self, DurableCompactionError> {
                Ok(Self {
                    inner: super::DurableCompactionStoreV1::open(database_url, owner_id).await?,
                })
            }

            #[must_use]
            pub fn owner_id(&self) -> &str {
                self.inner.owner_id()
            }

            pub async fn publish(
                &self,
                bundle: &DurableCompactionBundleV1,
            ) -> Result<DurableCompactionPublicationReceiptV1, DurableCompactionError> {
                if bundle.owner_id != self.inner.owner_id {
                    return Err(invalid(
                        "publication owner does not match the opened store",
                    ));
                }
                let mut connection = self.inner.pool.acquire().await?;
                sqlx::query("BEGIN IMMEDIATE")
                    .execute(&mut *connection)
                    .await?;
                let result = self.publish_tx(&mut connection, bundle).await;
                match result {
                    Ok(receipt) => {
                        sqlx::query("COMMIT")
                            .execute(&mut *connection)
                            .await?;
                        Ok(receipt)
                    }
                    Err(error) => {
                        let _ = sqlx::query("ROLLBACK")
                            .execute(&mut *connection)
                            .await;
                        Err(error)
                    }
                }
            }

            async fn publish_tx(
                &self,
                connection: &mut SqliteConnection,
                bundle: &DurableCompactionBundleV1,
            ) -> Result<DurableCompactionPublicationReceiptV1, DurableCompactionError> {
                if let Some(row) = sqlx::query(
                    "SELECT candidate_digest FROM compaction_candidates
                     WHERE owner_id = ? AND idempotency_key = ?",
                )
                .bind(&self.inner.owner_id)
                .bind(&bundle.idempotency_key)
                .fetch_optional(&mut *connection)
                .await?
                {
                    let existing: String = row.try_get("candidate_digest")?;
                    if existing != bundle.candidate_digest.to_string() {
                        return Err(conflict(
                            "idempotency key was reused with different semantics",
                        ));
                    }
                    let row = sqlx::query(
                        "SELECT publication_digest FROM compaction_checkpoints
                         WHERE owner_id = ? AND checkpoint_digest = ?",
                    )
                    .bind(&self.inner.owner_id)
                    .bind(bundle.checkpoint_digest.to_string())
                    .fetch_one(&mut *connection)
                    .await?;
                    let publication: String = row.try_get("publication_digest")?;
                    if publication != bundle.publication_digest.to_string() {
                        return Err(corrupt(
                            "idempotent checkpoint publication digest drift",
                        ));
                    }
                    return Ok(bundle.receipt(DurableCompactionDisposition::Unchanged));
                }

                for enrollment in [
                    &bundle.trust.selector,
                    &bundle.trust.generator,
                    &bundle.trust.tokenizer,
                    &bundle.trust.evaluator,
                ] {
                    persist_trust_enrollment(
                        connection,
                        &self.inner.owner_id,
                        enrollment,
                        bundle.accepted_at_unix_seconds,
                    )
                    .await?;
                }

                insert_payload(connection, bundle).await?;
                insert_candidate(connection, bundle).await?;
                insert_evaluation(connection, bundle).await?;
                insert_proof(connection, bundle).await?;
                insert_checkpoint(connection, bundle).await?;
                advance_active_checkpoint(connection, bundle).await?;
                insert_outbox(
                    connection,
                    bundle,
                    "checkpoint-published",
                    outbox_payload(bundle),
                )
                .await?;
                Ok(bundle.receipt(DurableCompactionDisposition::Inserted))
            }

            pub async fn select_current(
                &self,
                scope_id: &str,
                purpose_id: &str,
            ) -> Result<Option<DurableCompactionSelectionV1>, DurableCompactionError> {
                self.inner.select_current(scope_id, purpose_id).await
            }

            pub async fn revoke_checkpoint(
                &self,
                checkpoint_digest: Digest32,
                reason_digest: Digest32,
                revoked_at_unix_seconds: u64,
            ) -> Result<Digest32, DurableCompactionError> {
                self.inner
                    .revoke_checkpoint(
                        checkpoint_digest,
                        reason_digest,
                        revoked_at_unix_seconds,
                    )
                    .await
            }

            pub async fn claim_next_outbox(
                &self,
                now_unix_seconds: u64,
                claim_token: &str,
            ) -> Result<Option<DurableCompactionOutboxEventV1>, DurableCompactionError> {
                self.inner
                    .claim_next_outbox(now_unix_seconds, claim_token)
                    .await
            }

            pub async fn complete_outbox(
                &self,
                event: &DurableCompactionOutboxEventV1,
                delivered_at_unix_seconds: u64,
            ) -> Result<(), DurableCompactionError> {
                self.inner
                    .complete_outbox(event, delivered_at_unix_seconds)
                    .await
            }

            pub async fn reconcile_claims(
                &self,
                retry_at_unix_seconds: u64,
            ) -> Result<u64, DurableCompactionError> {
                self.inner.reconcile_claims(retry_at_unix_seconds).await
            }

            pub async fn revoke_trust(
                &self,
                role: CompactionTrustRoleV1,
                key_id: &StableId,
                trust_epoch: u64,
                revoked_at_unix_seconds: u64,
            ) -> Result<(), DurableCompactionError> {
                self.inner
                    .revoke_trust(
                        role,
                        key_id,
                        trust_epoch,
                        revoked_at_unix_seconds,
                    )
                    .await
            }

            pub async fn verify_integrity(&self) -> Result<(), DurableCompactionError> {
                self.inner.verify_integrity().await
            }
        }

        async fn advance_active_checkpoint(
            connection: &mut SqliteConnection,
            bundle: &DurableCompactionBundleV1,
        ) -> Result<(), DurableCompactionError> {
            let active = sqlx::query(
                "SELECT generation, checkpoint_digest
                 FROM active_compaction_checkpoint
                 WHERE owner_id = ? AND scope_id = ? AND purpose_id = ?",
            )
            .bind(&bundle.owner_id)
            .bind(&bundle.scope_id)
            .bind(&bundle.purpose_id)
            .fetch_optional(&mut *connection)
            .await?;

            match active {
                None => {
                    // The qualified kernel already proves:
                    // checkpoint.generation == source_snapshot.compact_generation.next().
                    // A local durable owner can therefore be materialized at any positive
                    // generation. It becomes the local lineage root and must not invent an
                    // unavailable predecessor digest.
                    if bundle.predecessor_checkpoint_digest.is_some() {
                        return Err(conflict(
                            "first local durable checkpoint must not invent a predecessor",
                        ));
                    }
                    sqlx::query(
                        "INSERT INTO active_compaction_checkpoint
                         (owner_id, scope_id, purpose_id, generation,
                          checkpoint_digest, predecessor_checkpoint_digest,
                          publication_digest, updated_at_unix_seconds)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    )
                    .bind(&bundle.owner_id)
                    .bind(&bundle.scope_id)
                    .bind(&bundle.purpose_id)
                    .bind(to_i64(bundle.generation, "generation")?)
                    .bind(bundle.checkpoint_digest.to_string())
                    .bind(Option::<String>::None)
                    .bind(bundle.publication_digest.to_string())
                    .bind(to_i64(
                        bundle.accepted_at_unix_seconds,
                        "active updated at",
                    )?)
                    .execute(&mut *connection)
                    .await?;
                }
                Some(row) => {
                    let previous_generation: i64 = row.try_get("generation")?;
                    let previous_digest: String =
                        row.try_get("checkpoint_digest")?;
                    if to_i64(bundle.generation, "generation")?
                        != previous_generation + 1
                        || bundle
                            .predecessor_checkpoint_digest
                            .map(|value| value.to_string())
                            != Some(previous_digest.clone())
                    {
                        return Err(conflict(
                            "checkpoint predecessor/generation CAS failed",
                        ));
                    }
                    let updated = sqlx::query(
                        "UPDATE active_compaction_checkpoint
                         SET generation = ?, checkpoint_digest = ?,
                             predecessor_checkpoint_digest = ?,
                             publication_digest = ?,
                             updated_at_unix_seconds = ?
                         WHERE owner_id = ? AND scope_id = ? AND purpose_id = ?
                           AND generation = ? AND checkpoint_digest = ?",
                    )
                    .bind(to_i64(bundle.generation, "generation")?)
                    .bind(bundle.checkpoint_digest.to_string())
                    .bind(previous_digest.clone())
                    .bind(bundle.publication_digest.to_string())
                    .bind(to_i64(
                        bundle.accepted_at_unix_seconds,
                        "active updated at",
                    )?)
                    .bind(&bundle.owner_id)
                    .bind(&bundle.scope_id)
                    .bind(&bundle.purpose_id)
                    .bind(previous_generation)
                    .bind(previous_digest)
                    .execute(&mut *connection)
                    .await?;
                    if updated.rows_affected() != 1 {
                        return Err(conflict(
                            "active checkpoint CAS lost a concurrent writer race",
                        ));
                    }
                }
            }
            Ok(())
        }
    }
}

pub use original::CompactionArtifactImagesV1;
pub use original::DurableCompactionBundleV1;
pub use original::DurableCompactionDisposition;
pub use original::DurableCompactionError;
pub use original::DurableCompactionOutboxEventV1;
pub use original::DurableCompactionPublicationReceiptV1;
pub use original::DurableCompactionSelectionV1;
pub use original::DurableCompactionTrustSetV1;
pub use original::corrected::DurableCompactionStoreV1;
