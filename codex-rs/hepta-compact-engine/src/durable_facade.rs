//! Corrected durable-owner facade.
//!
//! The reviewed V1 store implementation remains the single schema and helper
//! implementation. This facade reuses it verbatim, fixes local-root bootstrap,
//! and binds every artifact publication to the exact live V2 owner lease,
//! root pin and active signed trust manifest in the same SQLite transaction.

mod original {
    include!("durable.rs");

    pub(super) mod corrected {
        use super::*;
        use crate::archive_codec::{Decoder, Wire};

        const COMPACT_ARCHIVE_DOMAIN: &[u8] =
            b"hepta.compaction.durable-publication-archive.v2\0";

        #[derive(Clone, Copy, Debug, Eq, PartialEq)]
        struct PublicationFenceV2 {
            root_key_digest: Digest32,
            lease_token_digest: Digest32,
            lease_epoch: u64,
            minimum_expiry_unix_seconds: u64,
        }

        #[derive(Clone)]
        pub struct DurableCompactionStoreV1 {
            inner: super::DurableCompactionStoreV1,
            publication_fence: Option<PublicationFenceV2>,
        }

        impl DurableCompactionStoreV1 {
            pub async fn open(
                database_url: &str,
                owner_id: impl Into<String>,
            ) -> Result<Self, DurableCompactionError> {
                let inner =
                    super::DurableCompactionStoreV1::open(database_url, owner_id).await?;
                sqlx::raw_sql(include_str!("compaction_schema_hardening.sql"))
                    .execute(&inner.pool)
                    .await?;
                let publication_fence =
                    load_publication_fence(&inner.pool, &inner.owner_id).await?;
                Ok(Self {
                    inner,
                    publication_fence,
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
                self.verify_publication_fence_tx(connection, bundle)
                    .await?;

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

            async fn verify_publication_fence_tx(
                &self,
                connection: &mut SqliteConnection,
                bundle: &DurableCompactionBundleV1,
            ) -> Result<(), DurableCompactionError> {
                let (archive_owner, archive_root, archive_manifest) =
                    publication_archive_identity(&bundle.images.proof_image)?;
                self.verify_publication_fence_identity_tx(
                    connection,
                    &archive_owner,
                    archive_root,
                    archive_manifest,
                )
                .await
            }

            async fn verify_publication_fence_identity_tx(
                &self,
                connection: &mut SqliteConnection,
                archive_owner: &StableId,
                archive_root: Digest32,
                archive_manifest: Digest32,
            ) -> Result<(), DurableCompactionError> {
                let fence = self.publication_fence.ok_or_else(|| {
                    conflict(
                        "durable publication requires a live V2 owner fence and active manifest",
                    )
                })?;
                if archive_owner.as_str() != self.inner.owner_id
                    || archive_root != fence.root_key_digest
                {
                    return Err(conflict(
                        "publication archive owner or root differs from the fenced owner",
                    ));
                }

                let row = sqlx::query(
                    "SELECT f.root_key_digest AS fence_root_key_digest,
                            f.lease_token_digest, f.lease_epoch,
                            f.lease_expires_at_unix_seconds,
                            a.manifest_digest,
                            m.root_key_digest AS manifest_root_key_digest
                     FROM compaction_owner_fence_v2 AS f
                     JOIN active_compaction_manifest_v2 AS a
                       ON a.owner_id = f.owner_id
                     JOIN compaction_manifest_log_v2 AS m
                       ON m.owner_id = a.owner_id
                      AND m.manifest_digest = a.manifest_digest
                     WHERE f.owner_id = ?",
                )
                .bind(&self.inner.owner_id)
                .fetch_optional(&mut *connection)
                .await?
                .ok_or_else(|| conflict("durable owner fence or active manifest disappeared"))?;

                let fence_root: String = row.try_get("fence_root_key_digest")?;
                let lease_token: String = row.try_get("lease_token_digest")?;
                let lease_epoch: i64 = row.try_get("lease_epoch")?;
                let lease_expiry: i64 =
                    row.try_get("lease_expires_at_unix_seconds")?;
                let active_manifest: String = row.try_get("manifest_digest")?;
                let manifest_root: String =
                    row.try_get("manifest_root_key_digest")?;

                if fence_root != fence.root_key_digest.to_string()
                    || lease_token != fence.lease_token_digest.to_string()
                    || u64::try_from(lease_epoch).ok() != Some(fence.lease_epoch)
                    || u64::try_from(lease_expiry).ok().is_none_or(|value| {
                        value < fence.minimum_expiry_unix_seconds
                    })
                    || active_manifest != archive_manifest.to_string()
                    || manifest_root != archive_root.to_string()
                {
                    return Err(conflict(
                        "publication lost its exact lease, root pin or active manifest fence",
                    ));
                }
                Ok(())
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

        async fn load_publication_fence(
            pool: &SqlitePool,
            owner_id: &str,
        ) -> Result<Option<PublicationFenceV2>, DurableCompactionError> {
            let table_count: i64 = sqlx::query_scalar(
                "SELECT COUNT(*) FROM sqlite_master
                 WHERE type = 'table'
                   AND name IN (
                     'compaction_owner_fence_v2',
                     'compaction_manifest_log_v2',
                     'active_compaction_manifest_v2'
                   )",
            )
            .fetch_one(pool)
            .await?;
            if table_count != 3 {
                return Ok(None);
            }

            let row = sqlx::query(
                "SELECT f.root_key_digest AS fence_root_key_digest,
                        f.lease_token_digest, f.lease_epoch,
                        f.lease_expires_at_unix_seconds,
                        m.root_key_digest AS manifest_root_key_digest
                 FROM compaction_owner_fence_v2 AS f
                 JOIN active_compaction_manifest_v2 AS a
                   ON a.owner_id = f.owner_id
                 JOIN compaction_manifest_log_v2 AS m
                   ON m.owner_id = a.owner_id
                  AND m.manifest_digest = a.manifest_digest
                 WHERE f.owner_id = ?",
            )
            .bind(owner_id)
            .fetch_optional(pool)
            .await?;
            let Some(row) = row else {
                return Ok(None);
            };

            let fence_root_text: String = row.try_get("fence_root_key_digest")?;
            let manifest_root_text: String =
                row.try_get("manifest_root_key_digest")?;
            if fence_root_text != manifest_root_text {
                return Err(corrupt(
                    "owner fence root differs from the active manifest root",
                ));
            }
            let lease_epoch: i64 = row.try_get("lease_epoch")?;
            let lease_expiry: i64 =
                row.try_get("lease_expires_at_unix_seconds")?;
            Ok(Some(PublicationFenceV2 {
                root_key_digest: parse_digest(&fence_root_text, "owner fence root")?,
                lease_token_digest: parse_digest(
                    &row.try_get::<String, _>("lease_token_digest")?,
                    "owner lease token",
                )?,
                lease_epoch: from_i64(lease_epoch, "owner lease epoch")?,
                minimum_expiry_unix_seconds: from_i64(
                    lease_expiry,
                    "owner lease expiry",
                )?,
            }))
        }

        fn publication_archive_identity(
            bytes: &[u8],
        ) -> Result<(StableId, Digest32, Digest32), DurableCompactionError> {
            let mut input = Decoder::new(bytes, COMPACT_ARCHIVE_DOMAIN)
                .map_err(|error| corrupt(format!("invalid compact archive: {}", error.0)))?;
            if u32::read(&mut input)
                .map_err(|error| corrupt(format!("invalid archive schema: {}", error.0)))?
                != 1
            {
                return Err(corrupt("unsupported compact publication archive schema"));
            }
            let owner = StableId::read(&mut input)
                .map_err(|error| corrupt(format!("invalid archive owner: {}", error.0)))?;
            let root = Digest32::read(&mut input)
                .map_err(|error| corrupt(format!("invalid archive root: {}", error.0)))?;
            let manifest = Digest32::read(&mut input)
                .map_err(|error| corrupt(format!("invalid archive manifest: {}", error.0)))?;
            Ok((owner, root, manifest))
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

        #[cfg(test)]
        mod fence_tests {
            include!("durable_fence_tests.rs");
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
