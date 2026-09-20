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

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::FinalUseApprovalVerifier;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseControlError;
use codex_hepta_contracts::FinalUseRevocationFeedVerifier;
use codex_hepta_contracts::SignedFinalUseApproval;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;

use crate::BaoClient;
use crate::BaoClientError;
use crate::BaoReadRequest;
use crate::BaoLeaseError;
use crate::BaoReceiptKey;
use crate::BaoSecretLeaseReconcileRequest;
use crate::BaoSecretLeaseRenewRequest;
use crate::BaoSecretLeaseRequest;
use crate::BaoSecretLeaseRevokeRequest;
use crate::BaoSecretReceipt;
use crate::SecretLeaseMetadataV1;
use crate::SecretLeaseStore;

pub type BaoConsumerCallback = Arc<dyn Fn(&[u8]) -> Result<(), ()> + Send + Sync + 'static>;
pub type BaoLeaseConsumerCallback = Arc<
    dyn Fn(&SecretLeaseMetadataV1, u64, &str, &[u8]) -> Result<(), ()>
        + Send
        + Sync
        + 'static,
>;

#[derive(Clone)]
pub struct RegisteredBaoConsumer {
    id: String,
    callback: BaoConsumerCallback,
    lease_callback: BaoLeaseConsumerCallback,
}

impl fmt::Debug for RegisteredBaoConsumer {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("RegisteredBaoConsumer")
            .field("id", &self.id)
            .field("callback", &"[TRUSTED CALLBACK]")
            .finish()
    }
}

impl RegisteredBaoConsumer {
    pub fn new(
        id: String,
        callback: BaoConsumerCallback,
    ) -> Result<Self, BaoFinalUseHostError> {
        if !consumer_id(&id) {
            return Err(BaoFinalUseHostError::InvalidConsumerId);
        }
        let lease_callback_source = Arc::clone(&callback);
        let lease_callback: BaoLeaseConsumerCallback =
            Arc::new(move |_metadata, _authority_epoch, _grant_id, secret| {
                lease_callback_source(secret)
            });
        Ok(Self {
            id,
            callback,
            lease_callback,
        })
    }

    /// Register a consumer whose dynamic-lease delivery is explicitly aware of
    /// the committed lease metadata and the issuance grant frontier.
    pub fn new_lease_aware(
        id: String,
        callback: BaoConsumerCallback,
        lease_callback: BaoLeaseConsumerCallback,
    ) -> Result<Self, BaoFinalUseHostError> {
        if !consumer_id(&id) {
            return Err(BaoFinalUseHostError::InvalidConsumerId);
        }
        Ok(Self {
            id,
            callback,
            lease_callback,
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
    revocation_fresh_until_unix_ms: Arc<Mutex<u64>>,
    consumers: BTreeMap<String, RegisteredBaoConsumer>,
}

impl fmt::Debug for BaoFinalUseHost {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("BaoFinalUseHost")
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
            revocation_fresh_until_unix_ms: Arc::new(Mutex::new(0)),
            consumers: registry,
        })
    }

    pub fn consumer_count(&self) -> usize {
        self.consumers.len()
    }

    /// Apply one independently signed revocation head. The feed signature is
    /// checked before the durable authority owner sees the head; the authority
    /// itself enforces epoch/revision monotonicity and same-epoch superset rules.
    pub fn apply_revocation_update(
        &self,
        update: &SignedFinalUseRevocationUpdate,
    ) -> Result<(), BaoFinalUseHostError> {
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
        *fresh_until = receipt.valid_until_unix_ms;
        Ok(())
    }

    /// Production composition boundary. The request's signed `consumer_id`
    /// selects one pre-enrolled callback; callers cannot substitute a closure at
    /// the callsite. Independent operator approval is verified before any
    /// provider dispatch, then the lower-level client performs claim/network/
    /// digest/final-delivery fencing.
    pub async fn consume_kv_v2(
        &self,
        client: &BaoClient,
        grant: &SignedFinalUseGrant,
        approval: &SignedFinalUseApproval,
        request: &BaoReadRequest,
    ) -> Result<BaoSecretReceipt, BaoFinalUseHostError> {
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
        self.approval_verifier
            .verify(grant, approval)
            .map_err(BaoFinalUseHostError::Control)?;
        let consumer = self
            .consumers
            .get(&request.consumer_id)
            .cloned()
            .ok_or(BaoFinalUseHostError::UnregisteredConsumer)?;
        client
            .consume_kv_v2(&self.authority, grant, request, move |secret| {
                (consumer.callback)(secret)
            })
            .await
            .map_err(BaoFinalUseHostError::Client)
    }

    /// Build a read-only guard used by a registered consumer after a dynamic
    /// secret has been delivered. The guard shares the live revocation-feed
    /// freshness fence and revalidates the durable lease on every use.
    pub fn lease_use_guard(&self, store: SecretLeaseStore) -> BaoLeaseUseGuard {
        BaoLeaseUseGuard {
            authority: self.authority.clone(),
            clock: Arc::clone(&self.clock),
            revocation_fresh_until_unix_ms: Arc::clone(
                &self.revocation_fresh_until_unix_ms,
            ),
            store,
        }
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

    /// Issue one provider-native dynamic secret lease. Independent approval,
    /// current revocation freshness and durable operation identity are all
    /// required before the provider mutation can cross its dispatch fence.
    pub async fn request_secret_lease(
        &self,
        store: &SecretLeaseStore,
        client: &BaoClient,
        grant: &SignedFinalUseGrant,
        approval: &SignedFinalUseApproval,
        request: &BaoSecretLeaseRequest,
        receipt_key: &BaoReceiptKey,
    ) -> Result<SecretLeaseMetadataV1, BaoFinalUseHostError> {
        self.ensure_revocation_fresh()?;
        self.approval_verifier
            .verify(grant, approval)
            .map_err(BaoFinalUseHostError::Control)?;
        let consumer = self
            .consumers
            .get(&request.consumer_id)
            .cloned()
            .ok_or(BaoFinalUseHostError::UnregisteredConsumer)?;
        let authority_epoch = grant.grant.authority_epoch;
        let grant_id = grant.grant.grant_id.clone();
        client
            .request_secret_lease(
                store,
                &self.authority,
                grant,
                request,
                receipt_key,
                move |metadata, secret| {
                    (consumer.lease_callback)(
                        metadata,
                        authority_epoch,
                        &grant_id,
                        secret,
                    )
                },
            )
            .await
            .map_err(BaoFinalUseHostError::Lease)
    }

    pub async fn renew_secret_lease(
        &self,
        store: &SecretLeaseStore,
        client: &BaoClient,
        grant: &SignedFinalUseGrant,
        approval: &SignedFinalUseApproval,
        request: &BaoSecretLeaseRenewRequest,
    ) -> Result<SecretLeaseMetadataV1, BaoFinalUseHostError> {
        self.ensure_revocation_fresh()?;
        self.approval_verifier
            .verify(grant, approval)
            .map_err(BaoFinalUseHostError::Control)?;
        if !self.consumers.contains_key(&request.consumer_id) {
            return Err(BaoFinalUseHostError::UnregisteredConsumer);
        }
        client
            .renew_secret_lease(store, &self.authority, grant, request)
            .await
            .map_err(BaoFinalUseHostError::Lease)
    }

    pub async fn revoke_secret_lease(
        &self,
        store: &SecretLeaseStore,
        client: &BaoClient,
        grant: &SignedFinalUseGrant,
        approval: &SignedFinalUseApproval,
        request: &BaoSecretLeaseRevokeRequest,
    ) -> Result<SecretLeaseMetadataV1, BaoFinalUseHostError> {
        self.ensure_revocation_fresh()?;
        self.approval_verifier
            .verify(grant, approval)
            .map_err(BaoFinalUseHostError::Control)?;
        if !self.consumers.contains_key(&request.consumer_id) {
            return Err(BaoFinalUseHostError::UnregisteredConsumer);
        }
        client
            .revoke_secret_lease(store, &self.authority, grant, request)
            .await
            .map_err(BaoFinalUseHostError::Lease)
    }

    pub async fn reconcile_secret_lease(
        &self,
        store: &SecretLeaseStore,
        client: &BaoClient,
        grant: &SignedFinalUseGrant,
        approval: &SignedFinalUseApproval,
        request: &BaoSecretLeaseReconcileRequest,
    ) -> Result<SecretLeaseMetadataV1, BaoFinalUseHostError> {
        self.ensure_revocation_fresh()?;
        self.approval_verifier
            .verify(grant, approval)
            .map_err(BaoFinalUseHostError::Control)?;
        if !self.consumers.contains_key(&request.consumer_id) {
            return Err(BaoFinalUseHostError::UnregisteredConsumer);
        }
        client
            .reconcile_secret_lease(store, &self.authority, grant, request)
            .await
            .map_err(BaoFinalUseHostError::Lease)
    }

}

fn consumer_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value != "."
        && value != ".."
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_-.:".contains(&b))
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BaoLeaseUseWitness {
    pub lease_id: String,
    pub consumer_id: String,
    pub rotation_generation: u64,
    pub authority_epoch: u64,
    pub grant_id: String,
}

#[derive(Clone)]
pub struct BaoLeaseUseGuard {
    authority: FinalUseAuthority,
    clock: Arc<dyn AuthorityClock>,
    revocation_fresh_until_unix_ms: Arc<Mutex<u64>>,
    store: SecretLeaseStore,
}

impl fmt::Debug for BaoLeaseUseGuard {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("BaoLeaseUseGuard")
            .field("authority", &self.authority)
            .field("store", &self.store)
            .field("revocation_feed", &"[LIVE SIGNED FEED]")
            .finish()
    }
}

impl BaoLeaseUseGuard {
    pub async fn validate(
        &self,
        witness: &BaoLeaseUseWitness,
    ) -> Result<SecretLeaseMetadataV1, BaoFinalUseHostError> {
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
        if !self
            .authority
            .grant_is_current(witness.authority_epoch, &witness.grant_id)
            .map_err(BaoFinalUseHostError::Authority)?
        {
            return Err(BaoFinalUseHostError::GrantNoLongerCurrent);
        }
        let lease = self
            .store
            .lease(&witness.lease_id)
            .await
            .map_err(|error| BaoFinalUseHostError::Lease(BaoLeaseError::Store(error)))?
            .ok_or(BaoFinalUseHostError::Lease(BaoLeaseError::LeaseUnavailable))?;
        if lease.consumer_id != witness.consumer_id
            || lease.rotation_generation != witness.rotation_generation
            || !lease.is_usable_at(now_unix_ms)
        {
            return Err(BaoFinalUseHostError::Lease(BaoLeaseError::LeaseUnavailable));
        }
        Ok(lease)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BaoFinalUseHostError {
    InvalidConsumerId,
    DuplicateConsumer,
    EmptyConsumerRegistry,
    UnregisteredConsumer,
    StaleRevocationFeed,
    Unavailable,
    Trust(AuthorityTrustError),
    Authority(codex_hepta_contracts::FinalUseError),
    GrantNoLongerCurrent,
    Control(FinalUseControlError),
    Client(BaoClientError),
    Lease(BaoLeaseError),
}

impl fmt::Display for BaoFinalUseHostError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for BaoFinalUseHostError {}

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
        std::fs::set_permissions(
            directory.path(),
            std::fs::Permissions::from_mode(0o700),
        )
        .unwrap();
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
