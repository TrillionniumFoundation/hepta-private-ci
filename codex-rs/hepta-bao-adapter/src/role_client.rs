//! Kernel-peer RPC clients contain public trust only and never retry effects.

use crate::ConsumerPortError;
use crate::consumer_port::PreparedConnection;
use crate::role_storage::unavailable;
use crate::role_wire::AuthorityRequest;
use crate::role_wire::AuthorityResponse;
use crate::role_wire::OperatorRequest;
use crate::role_wire::OperatorResponse;
use codex_hepta_authbus::SignedTrustedTimeAttestation;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::SignedFinalUseApproval;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use codex_hepta_types::Digest32;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct RoleConnection {
    pub socket_path: PathBuf,
    pub peer_uid: u32,
    pub timeout_ms: u64,
}
impl RoleConnection {
    pub fn call<Q: Serialize, R: serde::de::DeserializeOwned>(
        &self,
        request: &Q,
    ) -> Result<R, ConsumerPortError> {
        if self.peer_uid == rustix::process::geteuid().as_raw()
            || self.timeout_ms == 0
            || self.timeout_ms > 2_000
        {
            return Err(ConsumerPortError::Invalid);
        }
        PreparedConnection::connect(
            &self.socket_path,
            self.peer_uid,
            Duration::from_millis(self.timeout_ms),
        )?
        .exchange(request)
    }
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct AuthorityTimeSource {
    pub connection: RoleConnection,
    pub issuer_id: String,
    pub key_epoch: u64,
    pub verifying_key: [u8; 32],
}
impl AuthorityTimeSource {
    pub fn trusted_time(&self) -> Result<SignedTrustedTimeAttestation, ConsumerPortError> {
        match self.connection.call(&AuthorityRequest::Time)? {
            AuthorityResponse::Time { attestation } => {
                attestation.verify(&self.issuer_id, self.key_epoch, &self.verifying_key)
            }
            _ => Err(ConsumerPortError::Unavailable),
        }
    }
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SecretsRoleClientConfig {
    pub(crate) schema_version: u32,
    pub(crate) runtime_uid: u32,
    pub(crate) authority: AuthorityTimeSource,
    pub(crate) operator: RoleConnection,
    pub(crate) issuer_id: String,
    pub(crate) issuer_verifying_key: [u8; 32],
    pub(crate) approver_id: String,
    pub(crate) approver_verifying_key: [u8; 32],
    pub(crate) frozen_binding: FinalUseBinding,
}
impl SecretsRoleClientConfig {
    pub fn load_root_owned(path: &Path) -> Result<Self, ConsumerPortError> {
        let config: Self = crate::private_files::read_root_configuration(path)?;
        config.validate()?;
        Ok(config)
    }
    fn validate(&self) -> Result<(), ConsumerPortError> {
        if self.schema_version != 1
            || self.runtime_uid != rustix::process::geteuid().as_raw()
            || self.runtime_uid == self.authority.connection.peer_uid
            || self.runtime_uid == self.operator.peer_uid
            || self.operator.peer_uid == self.authority.connection.peer_uid
            || self.authority.verifying_key == self.issuer_verifying_key
            || self.approver_verifying_key == self.issuer_verifying_key
        {
            return Err(ConsumerPortError::Invalid);
        }
        Ok(())
    }
}

type OriginalAdmissionDigests = ([u8; 32], [u8; 32]);

#[derive(Clone)]
pub struct SecretsAuthorityClient {
    config: SecretsRoleClientConfig,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ApprovedSecretOperation {
    pub original_operation_id: String,
    pub grant: SignedFinalUseGrant,
    pub approval: SignedFinalUseApproval,
}
impl SecretsAuthorityClient {
    pub fn new(config: SecretsRoleClientConfig) -> Result<Self, ConsumerPortError> {
        config.validate()?;
        Ok(Self { config })
    }
    pub fn trusted_time(&self) -> Result<SignedTrustedTimeAttestation, ConsumerPortError> {
        self.config.authority.trusted_time()
    }
    pub fn authorize_original(
        &self,
        operation: &str,
    ) -> Result<ApprovedSecretOperation, ConsumerPortError> {
        crate::authority_role_owner::original_id(operation)?;
        self.refresh_revocations()?;
        let grant = match self.call(&AuthorityRequest::Issue {
            original_operation_id: operation.to_owned(),
        })? {
            AuthorityResponse::Grant { grant } => grant,
            _ => return Err(ConsumerPortError::Unavailable),
        };
        if grant.grant.signer_id != self.config.issuer_id
            || grant.grant.binding != self.config.frozen_binding
            || grant.grant.grant_id != format!("secrets.read:{operation}")
        {
            return Err(ConsumerPortError::Rejected);
        }
        verify_grant(&grant, &self.config.issuer_verifying_key)?;
        let approval = match self.config.operator.call(&OperatorRequest::Approve {
            grant: Box::new(grant.clone()),
        })? {
            OperatorResponse::Approval { approval } => approval,
            _ => return Err(ConsumerPortError::Unavailable),
        };
        codex_hepta_contracts::FinalUseApprovalVerifier::new(
            self.config.approver_id.clone(),
            self.config.approver_verifying_key,
        )
        .map_err(unavailable)?
        .verify(&grant, &approval)
        .map_err(unavailable)?;
        Ok(ApprovedSecretOperation {
            original_operation_id: operation.to_owned(),
            grant,
            approval,
        })
    }
    /// Only the first durable admission can proceed. Lost replies and already
    /// started originals remain Unknown; querying Status cannot redispatch them.
    pub fn begin_original(
        &self,
        operation: &ApprovedSecretOperation,
    ) -> Result<(), ConsumerPortError> {
        let expected = (
            Digest32::of_bytes(&serde_json::to_vec(&operation.grant).map_err(unavailable)?)
                .into_array(),
            Digest32::of_bytes(&serde_json::to_vec(&operation.approval).map_err(unavailable)?)
                .into_array(),
        );
        match self.call(&AuthorityRequest::BeginOriginal {
            original_operation_id: operation.original_operation_id.clone(),
            approval: operation.approval.clone(),
        })? {
            AuthorityResponse::OriginalAdmitted {
                grant_sha256,
                approval_sha256,
            } if (grant_sha256, approval_sha256) == expected => Ok(()),
            _ => Err(ConsumerPortError::Unavailable),
        }
    }
    pub fn original_status(
        &self,
        operation: &str,
    ) -> Result<Option<OriginalAdmissionDigests>, ConsumerPortError> {
        crate::authority_role_owner::original_id(operation)?;
        match self.call(&AuthorityRequest::OriginalStatus {
            original_operation_id: operation.to_owned(),
        })? {
            AuthorityResponse::OriginalStarted {
                grant_sha256,
                approval_sha256,
            } => Ok(Some((grant_sha256, approval_sha256))),
            AuthorityResponse::Unknown => Ok(None),
            _ => Err(ConsumerPortError::Unavailable),
        }
    }
    pub fn refresh_revocations(&self) -> Result<SignedFinalUseRevocationUpdate, ConsumerPortError> {
        let update = match self.config.operator.call(&OperatorRequest::Revocations)? {
            OperatorResponse::Revocations { update } => update,
            _ => return Err(ConsumerPortError::Unavailable),
        };
        match self.call(&AuthorityRequest::ApplyRevocations {
            update: update.clone(),
        })? {
            AuthorityResponse::Frontier { revocations, .. }
                if revocations == update.update.head =>
            {
                Ok(update)
            }
            _ => Err(ConsumerPortError::Unavailable),
        }
    }
    fn call(&self, request: &AuthorityRequest) -> Result<AuthorityResponse, ConsumerPortError> {
        self.config.authority.connection.call(request)
    }
}
impl AuthorityFrontierStore<FinalUseFrontier> for SecretsAuthorityClient {
    fn load(&self, owner_id: &str) -> Result<FinalUseFrontier, AuthorityTrustError> {
        if owner_id != self.config.issuer_id {
            return Err(AuthorityTrustError::Invalid);
        }
        match self
            .call(&AuthorityRequest::Frontier {
                owner_id: owner_id.to_owned(),
            })
            .map_err(trust)?
        {
            AuthorityResponse::Frontier { frontier, .. } => Ok(frontier),
            _ => Err(AuthorityTrustError::Unavailable),
        }
    }
    fn compare_and_set(
        &self,
        owner_id: &str,
        expected: &FinalUseFrontier,
        next: &FinalUseFrontier,
    ) -> Result<(), AuthorityTrustError> {
        if owner_id != self.config.issuer_id {
            return Err(AuthorityTrustError::Invalid);
        }
        match self
            .call(&AuthorityRequest::CompareAndSet {
                owner_id: owner_id.to_owned(),
                expected: *expected,
                next: *next,
            })
            .map_err(trust)?
        {
            AuthorityResponse::Frontier { frontier, .. } if frontier == *next => Ok(()),
            AuthorityResponse::Conflict => Err(AuthorityTrustError::Conflict),
            _ => Err(AuthorityTrustError::Unavailable),
        }
    }
}
pub(crate) fn verify_grant(
    grant: &SignedFinalUseGrant,
    key: &[u8; 32],
) -> Result<(), ConsumerPortError> {
    let key = VerifyingKey::from_bytes(key).map_err(unavailable)?;
    if key.is_weak() {
        return Err(ConsumerPortError::Invalid);
    }
    key.verify_strict(
        &grant.grant.signing_bytes().map_err(unavailable)?,
        &Signature::from_slice(&grant.signature).map_err(unavailable)?,
    )
    .map_err(|_| ConsumerPortError::Rejected)
}
fn trust(error: ConsumerPortError) -> AuthorityTrustError {
    match error {
        ConsumerPortError::Invalid | ConsumerPortError::Rejected => AuthorityTrustError::Invalid,
        ConsumerPortError::Conflict => AuthorityTrustError::Conflict,
        ConsumerPortError::Unavailable | ConsumerPortError::Capacity => {
            AuthorityTrustError::Unavailable
        }
    }
}
