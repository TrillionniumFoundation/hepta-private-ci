//! Trusted host composition for the Bao final-use consumer.
//!
//! Product code enters the Bao secret-use boundary through this host rather
//! than passing an arbitrary closure directly to `BaoClient`. The signed
//! request's `consumer_id` must resolve to one statically registered callback,
//! the exact grant must have an independent operator approval, and revocation
//! updates are accepted only through an independently pinned signed feed.

use std::collections::BTreeMap;
use std::fmt;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_authbus::AuthBusAuthorityHost;
use codex_hepta_authbus::QuotaReservation;
use codex_hepta_authbus::ReservationState;
use codex_hepta_authbus::SettlementStatus;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseApprovalVerifier;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseControlError;
use codex_hepta_contracts::FinalUseRevocationFeedVerifier;
use codex_hepta_contracts::FinalUseRevocationReceipt;
use codex_hepta_contracts::SignedFinalUseApproval;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

#[path = "registered_consumption.rs"]
mod registered_consumption;
#[path = "consumption_recovery.rs"]
mod consumption_recovery;
#[path = "legacy_consumption_recovery.rs"]
mod legacy_recovery;

use crate::BaoAuthBusAdmission;
use crate::BaoAuthBusError;
use crate::BaoAuthBusEvidenceProvider;
use crate::BaoClient;
use crate::BaoClientError;
use crate::BaoReadRequest;
use crate::BaoSecretReceipt;
use crate::{
    BaoConsumptionOperationV1, BaoConsumptionStateV1, DurableLeaseRegistryV1, LeaseRegistryErrorV1,
};

/// Independently approved operation inputs; dependencies remain host-owned.
#[derive(Clone, Copy)]
pub struct BaoApprovedReadV1<'a> {
    pub admission: &'a BaoAuthBusAdmission,
    pub grant: &'a SignedFinalUseGrant,
    pub approval: &'a SignedFinalUseApproval,
    pub request: &'a BaoReadRequest,
}

pub type BaoOperationConsumerCallback =
    Arc<dyn Fn(&str, [u8; 32], &[u8]) -> Result<(), ()> + Send + Sync + 'static>;
pub type BaoConsumerObserverCallback =
    Arc<dyn Fn(&str, [u8; 32]) -> Result<BaoConsumerObservationV1, ()> + Send + Sync + 'static>;

/// Durable observation of the original consumer effect.
///
/// The legacy `NotApplied` value remains conservative and cannot release quota.
/// `NotAppliedWithEvidence` is the terminal negative outcome: the enrolled
/// observer must return a nonzero immutable evidence digest for the original
/// operation identity and semantic digest.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BaoConsumerObservationV1 {
    Succeeded,
    NotApplied,
    NotAppliedWithEvidence { evidence_sha256: [u8; 32] },
    Unknown,
}

pub type BaoConsumerCallback = Arc<dyn Fn(&[u8]) -> Result<(), ()> + Send + Sync + 'static>;

#[derive(Clone)]
pub struct RegisteredBaoConsumer {
    id: String,
    callback: BaoConsumerCallback,
    configuration_sha256: Option<[u8; 32]>,
    operation_callback: Option<BaoOperationConsumerCallback>,
    observer: Option<BaoConsumerObserverCallback>,
}

impl fmt::Debug for RegisteredBaoConsumer {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("RegisteredBaoConsumer")
            .field("id", &self.id)
            .field("callback", &"[TRUSTED CALLBACK]")
            .finish()
    }
}

impl RegisteredBaoConsumer {
    pub fn new(id: String, callback: BaoConsumerCallback) -> Result<Self, BaoFinalUseHostError> {
        if !consumer_id(&id) {
            return Err(BaoFinalUseHostError::InvalidConsumerId);
        }
        Ok(Self {
            id,
            callback,
            configuration_sha256: None,
            operation_callback: None,
            observer: None,
        })
    }

    /// A product registration must bind its immutable implementation/configuration
    /// identity and provide an operation-bound observer for restart reconciliation.
    pub fn for_operations(
        id: String,
        configuration_sha256: [u8; 32],
        callback: BaoOperationConsumerCallback,
        observer: BaoConsumerObserverCallback,
    ) -> Result<Self, BaoFinalUseHostError> {
        if !consumer_id(&id) || configuration_sha256 == [0; 32] {
            return Err(BaoFinalUseHostError::InvalidConsumerConfiguration);
        }
        Ok(Self {
            id,
            callback: Arc::new(|_| Err(())),
            configuration_sha256: Some(configuration_sha256),
            operation_callback: Some(callback),
            observer: Some(observer),
        })
    }

    pub fn id(&self) -> &str {
        &self.id
    }
}

/// Host-selected composition of final-use authority, independent approval,
/// authenticated revocation distribution and a closed consumer registry.
pub struct BaoFinalUseHost {
    authority: FinalUseAuthority,
    approval_verifier: FinalUseApprovalVerifier,
    revocation_verifier: FinalUseRevocationFeedVerifier,
    clock: Arc<dyn AuthorityClock>,
    revocation_fresh_until_unix_ms: Mutex<u64>,
    consumers: BTreeMap<String, RegisteredBaoConsumer>,
    pub(crate) metrics: crate::runtime_metrics::BaoRuntimeMetrics,
}

impl fmt::Debug for BaoFinalUseHost {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("BaoFinalUseHost")
            .field("authority", &self.authority)
            .field("approval_verifier", &self.approval_verifier)
            .field("revocation_verifier", &self.revocation_verifier)
            .field("consumer_count", &self.consumers.len())
            .finish()
    }
}

impl BaoFinalUseHost {
    pub fn new(
        authority: FinalUseAuthority,
        approval_verifier: FinalUseApprovalVerifier,
        revocation_verifier: FinalUseRevocationFeedVerifier,
        clock: Arc<dyn AuthorityClock>,
        consumers: impl IntoIterator<Item = RegisteredBaoConsumer>,
    ) -> Result<Self, BaoFinalUseHostError> {
        let mut registry = BTreeMap::new();
        for consumer in consumers {
            if registry.insert(consumer.id.clone(), consumer).is_some() {
                return Err(BaoFinalUseHostError::DuplicateConsumer);
            }
        }
        if registry.is_empty() {
            return Err(BaoFinalUseHostError::EmptyConsumerRegistry);
        }
        Ok(Self {
            authority,
            approval_verifier,
            revocation_verifier,
            clock,
            revocation_fresh_until_unix_ms: Mutex::new(0),
            consumers: registry,
            metrics: Default::default(),
        })
    }

    pub fn consumer_count(&self) -> usize {
        self.consumers.len()
    }

    fn ensure_revocation_fresh(&self) -> Result<(), BaoFinalUseHostError> {
        let now_unix_ms = self
            .clock
            .now_unix_ms()
            .map_err(BaoFinalUseHostError::Trust)?;
        let fresh_until = *self
            .revocation_fresh_until_unix_ms
            .lock()
            .map_err(|_| BaoFinalUseHostError::Unavailable)?;
        if fresh_until == 0 || now_unix_ms >= fresh_until {
            return Err(BaoFinalUseHostError::StaleRevocationFeed);
        }
        Ok(())
    }

    fn approved_consumer(
        &self,
        grant: &SignedFinalUseGrant,
        approval: &SignedFinalUseApproval,
        consumer_id: &str,
    ) -> Result<BaoConsumerCallback, BaoFinalUseHostError> {
        self.ensure_revocation_fresh()?;
        self.approval_verifier
            .verify(grant, approval)
            .map_err(BaoFinalUseHostError::Control)?;
        self.consumers
            .get(consumer_id)
            .map(|consumer| consumer.callback.clone())
            .ok_or(BaoFinalUseHostError::UnregisteredConsumer)
    }

    /// Apply one independently signed revocation head. The feed signature is
    /// checked before the durable authority owner sees the head; the authority
    /// itself enforces epoch/revision monotonicity and same-epoch superset rules.
    pub fn apply_revocation_update(
        &self,
        update: &SignedFinalUseRevocationUpdate,
    ) -> Result<FinalUseRevocationReceipt, BaoFinalUseHostError> {
        let now_unix_ms = self
            .clock
            .now_unix_ms()
            .map_err(BaoFinalUseHostError::Trust)?;
        let receipt = self
            .revocation_verifier
            .apply(&self.authority, update, now_unix_ms)
            .map_err(BaoFinalUseHostError::Control)?;
        let mut fresh_until = self
            .revocation_fresh_until_unix_ms
            .lock()
            .map_err(|_| BaoFinalUseHostError::Unavailable)?;
        *fresh_until = receipt.valid_until_unix_ms();
        Ok(receipt)
    }

    /// Registered final-use boundary without quota composition. This remains a
    /// bounded source integration path; product callers that reserve quota must
    /// use `consume_kv_v2_with_authbus` below.
    pub async fn consume_kv_v2(
        &self,
        client: &BaoClient,
        grant: &SignedFinalUseGrant,
        approval: &SignedFinalUseApproval,
        request: &BaoReadRequest,
    ) -> Result<BaoSecretReceipt, BaoFinalUseHostError> {
        let consumer = self.approved_consumer(grant, approval, &request.consumer_id)?;
        match client
            .consume_kv_v2_guarded(
                &self.authority,
                grant,
                request,
                |_| Ok(()),
                move |secret, _receipt| {
                    self.ensure_revocation_fresh()?;
                    consumer(secret).map_err(|()| {
                        BaoFinalUseHostError::Client(BaoClientError::ConsumerIndeterminate)
                    })
                },
            )
            .await
            .map_err(BaoFinalUseHostError::Client)?
        {
            Ok(receipt) => Ok(receipt),
            Err(error) => Err(error),
        }
    }

}

fn validate_reservation(
    row: &BaoConsumptionOperationV1,
    reservation: &QuotaReservation,
) -> Result<(), BaoProductHostError> {
    if row.reservation_id.as_deref().is_some_and(|id| id != reservation.reservation_id.as_str())
        || reservation.operation_id.as_str() != row.operation_id
        || reservation.amount != row.amount
        || reservation.effect_digest.into_array() != row.effect_sha256
    {
        return Err(BaoProductHostError::Store(
            LeaseRegistryErrorV1::ObservationMismatch,
        ));
    }
    Ok(())
}

fn abort_evidence(
    row: &BaoConsumptionOperationV1,
    code: &str,
    reservation: Option<&QuotaReservation>,
) -> [u8; 32] {
    let reservation_id = reservation
        .map(|value| value.reservation_id.as_str())
        .unwrap_or("");
    let reservation_revision = reservation.map(|value| value.revision).unwrap_or(0);
    Digest32::of_bytes(
        &serde_json::to_vec(&(
            "hepta.bao.abort.v1",
            row.operation_id.as_str(),
            row.semantic_sha256,
            row.effect_sha256,
            code,
            reservation_id,
            reservation_revision,
        ))
        .unwrap_or_default(),
    )
    .into_array()
}

fn provider_failure_code(error: BaoClientError) -> Option<&'static str> {
    match error {
        BaoClientError::ProviderDenied => Some("provider_denied"),
        BaoClientError::ProviderUnavailable => Some("provider_unavailable"),
        BaoClientError::NotFound => Some("not_found"),
        BaoClientError::ResponseTooLarge => Some("response_too_large"),
        BaoClientError::InvalidResponse => Some("invalid_response"),
        BaoClientError::VersionMismatch => Some("version_mismatch"),
        BaoClientError::SecretDigestMismatch => Some("secret_digest_mismatch"),
        BaoClientError::InvalidConfiguration
        | BaoClientError::InvalidRequest
        | BaoClientError::Authority(_)
        | BaoClientError::TransportUnavailable
        | BaoClientError::TimedOut
        | BaoClientError::ConsumerIndeterminate => None,
    }
}

fn consumer_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value != "."
        && value != ".."
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:".contains(&byte))
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BaoFinalUseHostError {
    InvalidConsumerId,
    InvalidConsumerConfiguration,
    DuplicateConsumer,
    EmptyConsumerRegistry,
    UnregisteredConsumer,
    StaleRevocationFeed,
    Unavailable,
    Trust(AuthorityTrustError),
    Control(FinalUseControlError),
    Client(BaoClientError),
}

impl fmt::Display for BaoFinalUseHostError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl std::error::Error for BaoFinalUseHostError {}

#[derive(Debug)]
pub enum BaoProductHostError {
    Host(BaoFinalUseHostError),
    AuthBus(BaoAuthBusError),
    Store(LeaseRegistryErrorV1),
    ConsumerProfileRequired,
    OutcomePending(BaoConsumptionOperationV1),
    TerminalFailure(BaoConsumptionOperationV1),
}

impl fmt::Display for BaoProductHostError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Host(error) => write!(formatter, "host admission failed: {error}"),
            Self::AuthBus(error) => write!(formatter, "AuthBus product path failed: {error}"),
            Self::Store(error) => write!(formatter, "durable operation failed: {error}"),
            Self::ConsumerProfileRequired => {
                formatter.write_str("matching operation-aware consumer profile required")
            }
            Self::OutcomePending(_) => {
                formatter.write_str("original operation requires reconciliation; no redispatch")
            }
            Self::TerminalFailure(row) => write!(
                formatter,
                "original operation reached immutable terminal failure ({})",
                row.terminal_code.as_deref().unwrap_or("unspecified")
            ),
        }
    }
}
impl std::error::Error for BaoProductHostError {}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use ed25519_dalek::SigningKey;

    fn callback() -> BaoConsumerCallback {
        Arc::new(|_| Ok(()))
    }

    #[test]
    fn consumer_registry_is_closed_and_unique() {
        assert_eq!(
            RegisteredBaoConsumer::new("../escape".into(), callback()).unwrap_err(),
            BaoFinalUseHostError::InvalidConsumerId
        );
        let consumer = RegisteredBaoConsumer::new("model-provider".into(), callback()).unwrap();
        assert_eq!(consumer.id(), "model-provider");
    }

    #[test]
    fn host_rejects_duplicate_consumer_identity() {
        let directory = tempfile::tempdir().unwrap();
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        let issuer = SigningKey::from_bytes(&[31; 32]);
        let approver = SigningKey::from_bytes(&[32; 32]);
        let distributor = SigningKey::from_bytes(&[33; 32]);
        let authority = FinalUseAuthority::open_state_dir(
            directory.path(),
            "security-owner".into(),
            issuer.verifying_key().to_bytes(),
            codex_hepta_contracts::FinalUseRevocations {
                authority_epoch: 1,
                revision: 1,
                revoked_grant_ids: Default::default(),
            },
        )
        .unwrap();
        let approval_verifier = FinalUseApprovalVerifier::new(
            "operator-approver".into(),
            approver.verifying_key().to_bytes(),
        )
        .unwrap();
        let revocation_verifier = FinalUseRevocationFeedVerifier::new(
            "revocation-distributor".into(),
            distributor.verifying_key().to_bytes(),
        )
        .unwrap();
        let first = RegisteredBaoConsumer::new("model-provider".into(), callback()).unwrap();
        let second = RegisteredBaoConsumer::new("model-provider".into(), callback()).unwrap();
        assert_eq!(
            BaoFinalUseHost::new(
                authority,
                approval_verifier,
                revocation_verifier,
                Arc::new(codex_hepta_contracts::SystemAuthorityClock),
                [first, second],
            )
            .unwrap_err(),
            BaoFinalUseHostError::DuplicateConsumer
        );
    }
}
