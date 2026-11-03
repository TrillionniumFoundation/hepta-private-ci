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
use codex_hepta_contracts::FinalUseAuthenticationProfile;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseControlError;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocationFeedVerifier;
use codex_hepta_contracts::FinalUseRevocationReceipt;
use codex_hepta_contracts::SignedFinalUseApproval;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;

use crate::BaoClient;
use crate::BaoClientError;
use crate::BaoReadRequest;
use crate::BaoSecretReceipt;

pub type BaoConsumerCallback = Arc<dyn Fn(&[u8]) -> Result<(), ()> + Send + Sync + 'static>;

#[derive(Clone)]
pub struct RegisteredBaoConsumer {
    id: String,
    callback: BaoConsumerCallback,
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
    pub fn new(id: String, callback: BaoConsumerCallback) -> Result<Self, BaoFinalUseHostError> {
        if !consumer_id(&id) {
            return Err(BaoFinalUseHostError::InvalidConsumerId);
        }
        Ok(Self { id, callback })
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
    revocation_lease: Mutex<Option<FinalUseRevocationReceipt>>,
    consumers: BTreeMap<String, BaoConsumerCallback>,
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
        if authority.authentication_profile() != approval_verifier.authentication_profile()
            || authority.authentication_profile() != revocation_verifier.authentication_profile()
        {
            return Err(BaoFinalUseHostError::AuthenticationProfileMismatch);
        }
        let mut registry = BTreeMap::new();
        for consumer in consumers {
            if registry.insert(consumer.id, consumer.callback).is_some() {
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
            revocation_lease: Mutex::new(None),
            consumers: registry,
        })
    }

    pub fn consumer_count(&self) -> usize {
        self.consumers.len()
    }

    fn ensure_joint_authority(
        &self,
        grant: &FinalUseGrant,
    ) -> Result<(u64, u64), BaoFinalUseHostError> {
        // Every host path takes this lease lock before reading/updating the
        // authority owner. It is released before I/O and consumer callbacks.
        let lease = self
            .revocation_lease
            .lock()
            .map_err(|_| BaoFinalUseHostError::Unavailable)?;
        let lease = lease
            .as_ref()
            .ok_or(BaoFinalUseHostError::StaleRevocationFeed)?;
        let head = self
            .authority
            .revocation_head()
            .map_err(|error| BaoFinalUseHostError::Client(BaoClientError::Authority(error)))?;
        let now_unix_ms = self
            .clock
            .now_unix_ms()
            .map_err(BaoFinalUseHostError::Trust)?;
        if head.authority_epoch != lease.authority_epoch()
            || head.revision != lease.revision()
            || now_unix_ms >= lease.valid_until_unix_ms()
        {
            return Err(BaoFinalUseHostError::StaleRevocationFeed);
        }
        // One protected time sample must be inside both the grant and feed
        // windows. Signature/nonce ownership stays with the original verifier.
        let grant_error = if grant.authority_epoch != head.authority_epoch {
            Some(FinalUseError::EpochMismatch)
        } else if head.revoked_grant_ids.contains(&grant.grant_id) {
            Some(FinalUseError::Revoked)
        } else if now_unix_ms < grant.not_before_unix_ms {
            Some(FinalUseError::NotYetValid)
        } else if now_unix_ms >= grant.expires_at_unix_ms {
            Some(FinalUseError::Expired)
        } else {
            None
        };
        if let Some(error) = grant_error {
            return Err(BaoFinalUseHostError::Client(BaoClientError::Authority(
                error,
            )));
        }
        Ok((head.authority_epoch, head.revision))
    }

    fn ensure_claimed_authority(
        &self,
        grant: &FinalUseGrant,
        claimed_head: (u64, u64),
    ) -> Result<(), BaoFinalUseHostError> {
        if self.ensure_joint_authority(grant)? != claimed_head {
            return Err(BaoFinalUseHostError::Client(BaoClientError::Authority(
                FinalUseError::StaleRevocationHead,
            )));
        }
        Ok(())
    }

    /// Apply one independently signed revocation head. The feed signature is
    /// checked before the durable authority owner sees the head; the authority
    /// itself enforces epoch/revision monotonicity and same-epoch superset rules.
    /// PQ may freshly authenticate the current durable head after a restart;
    /// that confirmation neither advances the owner nor restores spent nonces.
    pub fn apply_revocation_update(
        &self,
        update: &SignedFinalUseRevocationUpdate,
    ) -> Result<FinalUseRevocationReceipt, BaoFinalUseHostError> {
        // Keep apply/confirm and lease publication in one ordered operation.
        // An older head's longer lease must never overwrite a newer head's lease.
        let mut lease = self
            .revocation_lease
            .lock()
            .map_err(|_| BaoFinalUseHostError::Unavailable)?;
        let now_unix_ms = self
            .clock
            .now_unix_ms()
            .map_err(BaoFinalUseHostError::Trust)?;
        let receipt = match self.authority.authentication_profile() {
            FinalUseAuthenticationProfile::ClassicalV1 => {
                self.revocation_verifier
                    .apply(&self.authority, update, now_unix_ms)
            }
            FinalUseAuthenticationProfile::MlDsa65V2 => self
                .revocation_verifier
                .apply_or_confirm_current(&self.authority, update, now_unix_ms),
        }
        .map_err(BaoFinalUseHostError::Control)?;
        let retain_longer_same_head = lease.as_ref().is_some_and(|current| {
            current.authority_epoch() == receipt.authority_epoch()
                && current.revision() == receipt.revision()
                && current.valid_until_unix_ms() > receipt.valid_until_unix_ms()
        });
        if !retain_longer_same_head {
            *lease = Some(receipt.clone());
        }
        Ok(receipt)
    }

    /// Production composition boundary. The request's signed `consumer_id`
    /// selects one pre-enrolled callback; callers cannot substitute a closure at
    /// the callsite. Independent operator approval is verified before any
    /// provider dispatch. The grant, claimed head and feed must agree at one
    /// protected time before dispatch and again at registered consumer entry.
    /// A feed that expires or changes while provider I/O is in flight cannot
    /// release a secret under the older claim. The lower-level client retains
    /// the original claim/network/digest/final-delivery authority boundaries.
    pub async fn consume_kv_v2(
        &self,
        client: &BaoClient,
        grant: &SignedFinalUseGrant,
        approval: &SignedFinalUseApproval,
        request: &BaoReadRequest,
    ) -> Result<BaoSecretReceipt, BaoFinalUseHostError> {
        self.ensure_joint_authority(&grant.grant)?;
        self.approval_verifier
            .verify(grant, approval)
            .map_err(BaoFinalUseHostError::Control)?;
        let consumer = self
            .consumers
            .get(&request.consumer_id)
            .cloned()
            .ok_or(BaoFinalUseHostError::UnregisteredConsumer)?;
        match client
            .consume_kv_v2_guarded(
                &self.authority,
                grant,
                request,
                |token| {
                    self.ensure_claimed_authority(
                        &grant.grant,
                        (
                            token.claimed_authority_epoch(),
                            token.claimed_revocation_revision(),
                        ),
                    )
                },
                move |secret, claimed_head| {
                    self.ensure_claimed_authority(&grant.grant, claimed_head)?;
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

fn consumer_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value != "."
        && value != ".."
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_-.:".contains(&b))
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BaoFinalUseHostError {
    AuthenticationProfileMismatch,
    InvalidConsumerId,
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
