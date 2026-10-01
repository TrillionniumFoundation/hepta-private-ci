//! Independent operator approves only Root-frozen KV scope and signs its head.

use crate::ConsumerPortError;
use crate::authority_role_config::load_key;
use crate::authority_role_owner::integer;
use crate::local_endpoint::BoundSocket;
use crate::local_service::LocalServiceConfig;
use crate::local_service::LocalServiceOwner;
use crate::role_client::AuthorityTimeSource;
use crate::role_storage::RoleCommitFence;
use crate::role_storage::open_role_pool;
use crate::role_storage::unavailable;
use crate::role_wire::OperatorRequest;
use crate::role_wire::OperatorResponse;
use codex_hepta_authbus::SignedTrustedTimeAttestation;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseRevocationUpdate;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use codex_hepta_types::Digest32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde::Deserialize;
use serde::Serialize;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::SqlitePool;
use sqlx::Transaction;
use std::future::Future;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

static MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./operator_migrations");

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SecretsOperatorServiceConfig {
    pub(crate) schema_version: u32,
    pub(crate) service: LocalServiceConfig,
    pub(crate) database_path: PathBuf,
    pub(crate) runtime_uid: u32,
    pub(crate) authority_time: AuthorityTimeSource,
    pub(crate) issuer_id: String,
    pub(crate) issuer_verifying_key: [u8; 32],
    pub(crate) approver_id: String,
    pub(crate) approval_signing_key_file: PathBuf,
    pub(crate) approval_verifying_key: [u8; 32],
    pub(crate) distributor_id: String,
    pub(crate) revocation_signing_key_file: PathBuf,
    pub(crate) revocation_verifying_key: [u8; 32],
    pub(crate) frozen_binding: FinalUseBinding,
    pub(crate) root_revocation_head_file: PathBuf,
    pub(crate) feed_lifetime_ms: u64,
    pub(crate) maximum_grant_lifetime_ms: u64,
}
impl SecretsOperatorServiceConfig {
    pub fn load_root_owned(path: &Path) -> Result<Self, ConsumerPortError> {
        crate::private_files::read_root_configuration(path)
    }
    fn keys_profile(&self) -> Result<(SigningKey, SigningKey, [u8; 32]), ConsumerPortError> {
        if self.schema_version != 1
            || self.service.service_uid != rustix::process::geteuid().as_raw()
            || self.runtime_uid == self.service.service_uid
            || self.authority_time.connection.peer_uid == self.service.service_uid
            || self.runtime_uid == self.authority_time.connection.peer_uid
            || self.service.allowed_peer_uids != [self.runtime_uid]
            || self.feed_lifetime_ms == 0
            || self.feed_lifetime_ms > 10_000
            || self.maximum_grant_lifetime_ms == 0
            || self.maximum_grant_lifetime_ms > 180_000
            || self.frozen_binding.destination_id != "provider:heptabao"
        {
            return Err(ConsumerPortError::Invalid);
        }
        for id in [&self.issuer_id, &self.approver_id, &self.distributor_id] {
            codex_hepta_types::StableId::new(id).map_err(unavailable)?;
        }
        if self.frozen_binding.request_sha256 == [0; 32]
            || self.frozen_binding.scope_sha256 == [0; 32]
            || self.frozen_binding.payload_sha256 == [0; 32]
        {
            return Err(ConsumerPortError::Invalid);
        }
        let pins = [
            self.issuer_verifying_key,
            self.approval_verifying_key,
            self.revocation_verifying_key,
            self.authority_time.verifying_key,
        ];
        if pins
            .iter()
            .copied()
            .collect::<std::collections::BTreeSet<_>>()
            .len()
            != pins.len()
        {
            return Err(ConsumerPortError::Invalid);
        }
        let approval = load_key(
            &self.approval_signing_key_file,
            &self.approval_verifying_key,
        )?;
        let revocation = load_key(
            &self.revocation_signing_key_file,
            &self.revocation_verifying_key,
        )?;
        let profile = serde_json::to_vec(&(
            "hepta.secrets.independent-operator.v1",
            &self.issuer_id,
            self.issuer_verifying_key,
            &self.approver_id,
            self.approval_verifying_key,
            &self.distributor_id,
            self.revocation_verifying_key,
            &self.authority_time.issuer_id,
            self.authority_time.key_epoch,
            self.authority_time.verifying_key,
            &self.frozen_binding,
        ))
        .map_err(unavailable)?;
        Ok((
            approval,
            revocation,
            Digest32::of_bytes(&profile).into_array(),
        ))
    }
    pub(super) fn root_head(&self) -> Result<FinalUseRevocations, ConsumerPortError> {
        let head = crate::private_files::read_root_configuration(&self.root_revocation_head_file)?;
        FinalUseFrontier::for_initial_head(&head).map_err(unavailable)?;
        Ok(head)
    }
}

pub(super) struct OperatorRoleOwner {
    pub config: SecretsOperatorServiceConfig,
    pub pool: SqlitePool,
    pub approval: SigningKey,
    revocation: SigningKey,
    fenced: Arc<AtomicBool>,
}
impl OperatorRoleOwner {
    pub async fn open(config: SecretsOperatorServiceConfig) -> Result<Self, ConsumerPortError> {
        let (approval, revocation, profile) = config.keys_profile()?;
        let head = config.root_head()?;
        let pool = open_role_pool(&config.database_path, &MIGRATOR).await?;
        let result = async {
            let mut tx = pool
                .begin_with("BEGIN IMMEDIATE")
                .await
                .map_err(unavailable)?;
            let observed: Option<Vec<u8>> = sqlx::query_scalar(
                "SELECT profile_sha256 FROM operator_role_meta WHERE singleton=1",
            )
            .fetch_optional(&mut *tx)
            .await
            .map_err(unavailable)?;
            if let Some(observed) = observed {
                if observed != profile {
                    return Err(ConsumerPortError::Conflict);
                }
            } else {
                let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM operator_role_approval")
                    .fetch_one(&mut *tx)
                    .await
                    .map_err(unavailable)?;
                if count != 0 {
                    return Err(ConsumerPortError::Unavailable);
                }
                sqlx::query("INSERT INTO operator_role_meta VALUES(1,?,0,0,?)")
                    .bind(profile.as_slice())
                    .bind(serde_json::to_vec(&head).map_err(unavailable)?)
                    .execute(&mut *tx)
                    .await
                    .map_err(unavailable)?;
            }
            tx.commit().await.map_err(unavailable)
        }
        .await;
        if let Err(error) = result {
            pool.close().await;
            return Err(error);
        }
        Ok(Self {
            config,
            pool,
            approval,
            revocation,
            fenced: Arc::new(AtomicBool::new(false)),
        })
    }
    pub(super) async fn begin(
        &self,
    ) -> Result<(Transaction<'static, Sqlite>, RoleCommitFence), ConsumerPortError> {
        let guard = RoleCommitFence::arm(&self.fenced)?;
        let tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        if self.fenced.load(Ordering::Acquire) {
            return Err(ConsumerPortError::Unavailable);
        }
        Ok((tx, guard))
    }
    pub(super) async fn commit(
        &self,
        tx: Transaction<'static, Sqlite>,
        mut guard: RoleCommitFence,
    ) -> Result<(), ConsumerPortError> {
        if self.fenced.load(Ordering::Acquire) {
            return Err(ConsumerPortError::Unavailable);
        }
        tx.commit().await.map_err(unavailable)?;
        guard.committed();
        Ok(())
    }
    pub(super) async fn observe_time_head(
        &self,
        tx: &mut Transaction<'static, Sqlite>,
        time: &SignedTrustedTimeAttestation,
        head: &FinalUseRevocations,
    ) -> Result<(), ConsumerPortError> {
        let row=sqlx::query("SELECT last_wall_time_ms,last_source_revision,head_json FROM operator_role_meta WHERE singleton=1")
            .fetch_one(&mut **tx).await.map_err(unavailable)?;
        let old_wall: i64 = row.try_get("last_wall_time_ms").map_err(unavailable)?;
        let old_revision: i64 = row.try_get("last_source_revision").map_err(unavailable)?;
        let old_head: FinalUseRevocations = serde_json::from_slice(
            &row.try_get::<Vec<u8>, _>("head_json")
                .map_err(unavailable)?,
        )
        .map_err(unavailable)?;
        if integer(time.claims.wall_time_ms)? < old_wall
            || integer(time.claims.source_revision)? <= old_revision
            || head.authority_epoch < old_head.authority_epoch
            || (head.authority_epoch == old_head.authority_epoch
                && (head.revision < old_head.revision
                    || !old_head
                        .revoked_grant_ids
                        .is_subset(&head.revoked_grant_ids)))
            || (head.authority_epoch == old_head.authority_epoch
                && head.revision == old_head.revision
                && head != &old_head)
        {
            return Err(ConsumerPortError::Rejected);
        }
        sqlx::query("UPDATE operator_role_meta SET last_wall_time_ms=?,last_source_revision=?,head_json=? WHERE singleton=1")
            .bind(integer(time.claims.wall_time_ms)?).bind(integer(time.claims.source_revision)?)
            .bind(serde_json::to_vec(head).map_err(unavailable)?).execute(&mut **tx).await.map_err(unavailable)?;
        Ok(())
    }
    async fn revocations(&self) -> Result<SignedFinalUseRevocationUpdate, ConsumerPortError> {
        let time = self.config.authority_time.trusted_time()?;
        let head = self.config.root_head()?;
        let (mut tx, guard) = self.begin().await?;
        self.observe_time_head(&mut tx, &time, &head).await?;
        let update = FinalUseRevocationUpdate::new(
            self.config.distributor_id.clone(),
            head,
            time.claims.wall_time_ms,
            time.claims
                .wall_time_ms
                .checked_add(self.config.feed_lifetime_ms)
                .ok_or(ConsumerPortError::Invalid)?,
        );
        let signature = self
            .revocation
            .sign(&update.signing_bytes().map_err(unavailable)?)
            .to_bytes()
            .to_vec();
        self.commit(tx, guard).await?;
        Ok(SignedFinalUseRevocationUpdate { update, signature })
    }
}

pub async fn serve_secrets_operator(
    config: SecretsOperatorServiceConfig,
    shutdown: impl Future<Output = ()>,
) -> Result<(), ConsumerPortError> {
    let endpoint = BoundSocket::bind(&config.service.socket_path, config.service.ipc_group_gid)?;
    let service = config.service.clone();
    let owner = Arc::new(OperatorRoleOwner::open(config).await?);
    crate::local_service::serve(service, owner, endpoint, shutdown).await
}
impl LocalServiceOwner for OperatorRoleOwner {
    async fn handle(&self, _peer_uid: u32, request: &[u8]) -> Result<Vec<u8>, ConsumerPortError> {
        let request: OperatorRequest = serde_json::from_slice(request).map_err(unavailable)?;
        let result = match request {
            OperatorRequest::Approve { grant } => self
                .approve(&grant)
                .await
                .map(|approval| OperatorResponse::Approval { approval }),
            OperatorRequest::Revocations => self
                .revocations()
                .await
                .map(|update| OperatorResponse::Revocations { update }),
        };
        let response = match result {
            Ok(response) => response,
            Err(ConsumerPortError::Conflict) => OperatorResponse::Conflict,
            Err(ConsumerPortError::Invalid | ConsumerPortError::Rejected) => {
                OperatorResponse::Rejected
            }
            Err(ConsumerPortError::Unavailable | ConsumerPortError::Capacity) => {
                OperatorResponse::Unknown
            }
        };
        serde_json::to_vec(&response).map_err(unavailable)
    }
    fn fence_unknown(&self) {
        self.fenced.store(true, Ordering::Release);
    }
    async fn close(&self) {
        self.pool.close().await;
    }
}
