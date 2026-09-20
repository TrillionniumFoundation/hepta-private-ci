//! Lease-bound product authentication backed by a HeptaBao dynamic secret.
//!
//! Raw credential bytes exist only in zeroizing process memory after delivery
//! through the registered lease-aware consumer. Every outbound request
//! revalidates the signed revocation-feed freshness, issuance grant frontier,
//! and durable lease currentness before constructing an Authorization header.

use std::fmt;
use std::sync::Arc;
use std::sync::RwLock;

use codex_api::AuthError;
use codex_api::AuthHeadersFuture;
use codex_api::AuthProvider;
use codex_api::SharedAuthProvider;
use http::HeaderMap;
use http::HeaderValue;
use http::header::AUTHORIZATION;
use zeroize::Zeroizing;

use crate::BaoConsumerCallback;
use crate::BaoLeaseConsumerCallback;
use crate::BaoLeaseUseGuard;
use crate::BaoLeaseUseWitness;
use crate::BaoFinalUseHostError;
use crate::RegisteredBaoConsumer;
use crate::SecretLeaseMetadataV1;

const MAX_PRODUCT_CREDENTIAL_BYTES: usize = 8 * 1024;

#[derive(Clone)]
struct InstalledCredential {
    secret: Zeroizing<String>,
    witness: BaoLeaseUseWitness,
}

impl fmt::Debug for InstalledCredential {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("InstalledCredential")
            .field("secret", &"[REDACTED]")
            .field("witness", &self.witness)
            .finish()
    }
}

#[derive(Default)]
struct State {
    guard: Option<BaoLeaseUseGuard>,
    credential: Option<InstalledCredential>,
}

#[derive(Clone)]
pub struct BaoLeasedProviderAuth {
    consumer_id: String,
    state: Arc<RwLock<State>>,
}

impl fmt::Debug for BaoLeasedProviderAuth {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let ready = self
            .state
            .read()
            .is_ok_and(|state| state.guard.is_some() && state.credential.is_some());
        formatter
            .debug_struct("BaoLeasedProviderAuth")
            .field("consumer_id", &self.consumer_id)
            .field("ready", &ready)
            .field("credential", &"[REDACTED]")
            .finish()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BaoLeasedProviderAuthError {
    InvalidConsumer,
    GuardAlreadyAttached,
    InvalidCredential,
    ConsumerMismatch,
    Unavailable,
}

impl fmt::Display for BaoLeasedProviderAuthError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for BaoLeasedProviderAuthError {}

impl BaoLeasedProviderAuth {
    pub fn new(consumer_id: String) -> Result<Self, BaoLeasedProviderAuthError> {
        if consumer_id.is_empty()
            || consumer_id.len() > 128
            || consumer_id == "."
            || consumer_id == ".."
            || !consumer_id
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:".contains(&byte))
        {
            return Err(BaoLeasedProviderAuthError::InvalidConsumer);
        }
        Ok(Self {
            consumer_id,
            state: Arc::new(RwLock::new(State::default())),
        })
    }

    pub fn consumer_id(&self) -> &str {
        &self.consumer_id
    }

    /// Attach the host's currentness guard exactly once. Credential delivery
    /// before this step is allowed only as transient state; request resolution
    /// remains fail-closed until the guard is present.
    pub fn attach_guard(
        &self,
        guard: BaoLeaseUseGuard,
    ) -> Result<(), BaoLeasedProviderAuthError> {
        let mut state = self
            .state
            .write()
            .map_err(|_| BaoLeasedProviderAuthError::Unavailable)?;
        if state.guard.is_some() {
            return Err(BaoLeasedProviderAuthError::GuardAlreadyAttached);
        }
        state.guard = Some(guard);
        Ok(())
    }

    /// Closed-registry consumer entry. Exact-KV delivery is deliberately
    /// rejected: product request auth must be backed by a provider-native
    /// dynamic lease with explicit expiry/revocation state.
    pub fn registered_consumer(
        &self,
    ) -> Result<RegisteredBaoConsumer, BaoFinalUseHostError> {
        let raw: BaoConsumerCallback = Arc::new(|_secret| Err(()));
        let owner = self.clone();
        let lease: BaoLeaseConsumerCallback = Arc::new(
            move |metadata, authority_epoch, grant_id, secret| {
                owner
                    .install_lease(metadata, authority_epoch, grant_id, secret)
                    .map_err(|_| ())
            },
        );
        RegisteredBaoConsumer::new_lease_aware(self.consumer_id.clone(), raw, lease)
    }

    pub fn shared_auth_provider(&self) -> SharedAuthProvider {
        Arc::new(self.clone())
    }

    fn install_lease(
        &self,
        metadata: &SecretLeaseMetadataV1,
        authority_epoch: u64,
        grant_id: &str,
        secret: &[u8],
    ) -> Result<(), BaoLeasedProviderAuthError> {
        if metadata.consumer_id != self.consumer_id || authority_epoch == 0 || grant_id.is_empty() {
            return Err(BaoLeasedProviderAuthError::ConsumerMismatch);
        }
        if secret.is_empty() || secret.len() > MAX_PRODUCT_CREDENTIAL_BYTES {
            return Err(BaoLeasedProviderAuthError::InvalidCredential);
        }
        let text =
            std::str::from_utf8(secret).map_err(|_| BaoLeasedProviderAuthError::InvalidCredential)?;
        if HeaderValue::from_str(text).is_err() {
            return Err(BaoLeasedProviderAuthError::InvalidCredential);
        }
        let witness = BaoLeaseUseWitness {
            lease_id: metadata.lease_id.clone(),
            consumer_id: metadata.consumer_id.clone(),
            rotation_generation: metadata.rotation_generation,
            authority_epoch,
            grant_id: grant_id.to_owned(),
        };
        let mut state = self
            .state
            .write()
            .map_err(|_| BaoLeasedProviderAuthError::Unavailable)?;
        state.credential = Some(InstalledCredential {
            secret: Zeroizing::new(text.to_owned()),
            witness,
        });
        Ok(())
    }

    async fn current_authorization_header(&self) -> Result<HeaderValue, AuthError> {
        let (guard, witness) = {
            let state = self
                .state
                .read()
                .map_err(|_| AuthError::Transient("HeptaBao auth state unavailable".into()))?;
            let guard = state
                .guard
                .clone()
                .ok_or_else(|| AuthError::Build("HeptaBao lease guard is not attached".into()))?;
            let witness = state
                .credential
                .as_ref()
                .map(|credential| credential.witness.clone())
                .ok_or_else(|| AuthError::Build("HeptaBao leased credential is unavailable".into()))?;
            (guard, witness)
        };

        guard
            .validate(&witness)
            .await
            .map_err(|_| AuthError::Build("HeptaBao leased credential is not current".into()))?;

        let state = self
            .state
            .read()
            .map_err(|_| AuthError::Transient("HeptaBao auth state unavailable".into()))?;
        let credential = state
            .credential
            .as_ref()
            .filter(|credential| credential.witness == witness)
            .ok_or_else(|| AuthError::Build("HeptaBao leased credential changed during validation".into()))?;
        let bearer = Zeroizing::new(format!("Bearer {}", credential.secret.as_str()));
        let mut value = HeaderValue::from_str(&bearer)
            .map_err(|_| AuthError::Build("HeptaBao credential is not a valid header value".into()))?;
        value.set_sensitive(true);
        Ok(value)
    }
}

impl AuthProvider for BaoLeasedProviderAuth {
    /// Telemetry must not materialize a possibly stale credential. The async
    /// request path below is the only path allowed to create the header.
    fn add_auth_headers(&self, _headers: &mut HeaderMap) {}

    fn resolve_auth_headers(&self) -> AuthHeadersFuture<'_> {
        Box::pin(async move {
            let mut headers = HeaderMap::new();
            headers.insert(AUTHORIZATION, self.current_authorization_header().await?);
            Ok(headers)
        })
    }
}
