//! Fenced product access to the original private storage implementation.
use super::*;
use crate::archive_codec::Decoder;
use crate::archive_codec::Wire;
use crate::owner_fence::OwnerWriteFenceV2;
use sqlx::Sqlite;
use sqlx::Transaction;

const COMPACT_ARCHIVE_DOMAIN: &[u8] = b"hepta.compaction.durable-publication-archive.v2\0";

#[derive(Clone)]
pub(crate) struct DurableCompactionStoreV1 {
    inner: super::DurableCompactionStoreV1,
    write_fence: OwnerWriteFenceV2,
    active_manifest_digest: Digest32,
}

impl DurableCompactionStoreV1 {
    pub(crate) async fn open(
        database_url: &str,
        owner_id: impl Into<String>,
        write_fence: OwnerWriteFenceV2,
        active_manifest_digest: Digest32,
        now: u64,
    ) -> Result<Self, DurableCompactionError> {
        // Base schema initialization is shared with the raw storage tests.
        // Installing the live-owner hardening trigger is itself an owned write.
        let inner = super::DurableCompactionStoreV1::open(database_url, owner_id).await?;
        let value = Self {
            inner,
            write_fence,
            active_manifest_digest,
        };
        let mut transaction = value.begin_write(now).await?;
        sqlx::raw_sql(include_str!("compaction_schema_hardening.sql"))
            .execute(&mut *transaction)
            .await?;
        transaction.commit().await?;
        Ok(value)
    }

    pub(crate) fn owner_id(&self) -> &str {
        self.inner.owner_id()
    }

    // Only the private coordinator calls this after verifying a signed successor.
    // Its candidate clone is installed only after the metadata transaction commits.
    pub(crate) fn set_active_manifest(&mut self, digest: Digest32) {
        self.active_manifest_digest = digest;
    }

    async fn begin_write(
        &self,
        now: u64,
    ) -> Result<Transaction<'static, Sqlite>, DurableCompactionError> {
        self.write_fence
            .begin(
                &self.inner.pool,
                self.owner_id(),
                self.active_manifest_digest,
                now,
            )
            .await
    }

    pub(crate) async fn publish(
        &self,
        bundle: &DurableCompactionBundleV1,
        now: u64,
    ) -> Result<DurableCompactionPublicationReceiptV1, DurableCompactionError> {
        if bundle.owner_id != self.inner.owner_id {
            return Err(invalid("publication owner does not match the opened store"));
        }
        let mut transaction = self.begin_write(now).await?;
        let (owner, root, manifest) = publication_archive_identity(&bundle.images.proof_image)?;
        self.verify_publication_fence_identity_tx(&mut transaction, &owner, root, manifest, now)
            .await?;
        // Reuse the original idempotency, immutable rows, strict (1,None)
        // genesis and exact predecessor CAS rather than a second lineage policy.
        let result = self.inner.publish_tx(&mut transaction, bundle).await;
        finish(transaction, result).await
    }

    async fn verify_publication_fence_identity_tx(
        &self,
        connection: &mut SqliteConnection,
        archive_owner: &StableId,
        archive_root: Digest32,
        archive_manifest: Digest32,
        now: u64,
    ) -> Result<(), DurableCompactionError> {
        if archive_owner.as_str() != self.owner_id()
            || archive_root != self.write_fence.root_key_digest
            || archive_manifest != self.active_manifest_digest
        {
            return Err(conflict(
                "publication archive owner, root or manifest differs from the fenced owner",
            ));
        }
        self.write_fence
            .verify_tx(
                connection,
                self.owner_id(),
                self.active_manifest_digest,
                now,
            )
            .await
    }

    pub(crate) async fn select_current(
        &self,
        scope_id: &str,
        purpose_id: &str,
    ) -> Result<Option<DurableCompactionSelectionV1>, DurableCompactionError> {
        self.inner.select_current(scope_id, purpose_id).await
    }

    pub(crate) async fn revoke_checkpoint(
        &self,
        checkpoint_digest: Digest32,
        reason_digest: Digest32,
        revoked_at_unix_seconds: u64,
    ) -> Result<Digest32, DurableCompactionError> {
        let mut transaction = self.begin_write(revoked_at_unix_seconds).await?;
        let result = self
            .inner
            .revoke_checkpoint_tx(
                &mut transaction,
                checkpoint_digest,
                reason_digest,
                revoked_at_unix_seconds,
            )
            .await;
        finish(transaction, result).await
    }

    pub(crate) async fn claim_next_outbox(
        &self,
        now_unix_seconds: u64,
        claim_token: &str,
    ) -> Result<Option<DurableCompactionOutboxEventV1>, DurableCompactionError> {
        let mut transaction = self.begin_write(now_unix_seconds).await?;
        let result = self
            .inner
            .claim_next_outbox_tx(&mut transaction, now_unix_seconds, claim_token)
            .await;
        finish(transaction, result).await
    }

    pub(crate) async fn complete_outbox(
        &self,
        event: &DurableCompactionOutboxEventV1,
        delivered_at_unix_seconds: u64,
    ) -> Result<(), DurableCompactionError> {
        let mut transaction = self.begin_write(delivered_at_unix_seconds).await?;
        let result = self
            .inner
            .complete_outbox_tx(&mut transaction, event, delivered_at_unix_seconds)
            .await;
        finish(transaction, result).await
    }

    pub(crate) async fn reconcile_claims(
        &self,
        retry_at_unix_seconds: u64,
    ) -> Result<u64, DurableCompactionError> {
        let mut transaction = self.begin_write(retry_at_unix_seconds).await?;
        let result = self
            .inner
            .reconcile_claims_tx(&mut transaction, retry_at_unix_seconds)
            .await;
        finish(transaction, result).await
    }

    pub(crate) async fn revoke_trust(
        &self,
        role: CompactionTrustRoleV1,
        key_id: &StableId,
        trust_epoch: u64,
        revoked_at_unix_seconds: u64,
    ) -> Result<(), DurableCompactionError> {
        let mut transaction = self.begin_write(revoked_at_unix_seconds).await?;
        let result = self
            .inner
            .revoke_trust_tx(
                &mut transaction,
                role,
                key_id,
                trust_epoch,
                revoked_at_unix_seconds,
            )
            .await;
        finish(transaction, result).await
    }

    pub(crate) async fn verify_integrity(&self) -> Result<(), DurableCompactionError> {
        self.inner.verify_integrity().await
    }
}

async fn finish<T>(
    transaction: Transaction<'static, Sqlite>,
    result: Result<T, DurableCompactionError>,
) -> Result<T, DurableCompactionError> {
    match result {
        Ok(value) => {
            transaction.commit().await?;
            Ok(value)
        }
        Err(error) => {
            let _ = transaction.rollback().await;
            Err(error)
        }
    }
}

fn publication_archive_identity(
    bytes: &[u8],
) -> Result<(StableId, Digest32, Digest32), DurableCompactionError> {
    let mut decoder = Decoder::new(bytes, COMPACT_ARCHIVE_DOMAIN)
        .map_err(|error| corrupt(format!("publication archive identity: {}", error.0)))?;
    if u32::read(&mut decoder)
        .map_err(|error| corrupt(format!("publication archive schema: {}", error.0)))?
        != 1
    {
        return Err(corrupt("unsupported publication archive schema"));
    }
    let owner = StableId::read(&mut decoder)
        .map_err(|error| corrupt(format!("publication archive owner: {}", error.0)))?;
    let root = Digest32::read(&mut decoder)
        .map_err(|error| corrupt(format!("publication archive root: {}", error.0)))?;
    let manifest = Digest32::read(&mut decoder)
        .map_err(|error| corrupt(format!("publication archive manifest: {}", error.0)))?;
    Ok((owner, root, manifest))
}

#[cfg(test)]
#[path = "durable_fence_tests.rs"]
mod fence_tests;
