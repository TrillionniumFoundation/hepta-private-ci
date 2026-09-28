//! One-time attachment point for external context.compiler security capabilities.
//!
//! Agentd may start before a protected environment attaches these capabilities,
//! but the V3 physical-send path fails closed until the complete set is present.
//! There is no process-local production fallback.

use std::fmt;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::sync::OnceLock;

use codex_hepta_prompt_registry::PromptContextAuthoritySnapshotV3;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ContextAttemptJournalV3;
use crate::ContextAttemptLeaseAuthorityV3;
use crate::ContextMonotonicGenerationAnchorV3;
use crate::ImmutableTokenizerExecutorV3;
use crate::IndependentProviderTerminalAttestationV3;
use crate::ProviderTerminalAttestationVerifierV3;

pub type ExternalContextAuthorityFuture<'a> = Pin<
    Box<
        dyn Future<
                Output = Result<
                    PromptContextAuthoritySnapshotV3,
                    ExternalContextSecurityErrorV3,
                >,
            > + Send
            + 'a,
    >,
>;

pub trait ExternalContextAuthorityProviderV3: Send + Sync {
    fn provider_digest(&self) -> Digest32;

    fn verify_snapshot<'a>(
        &'a self,
        snapshot: PromptContextAuthoritySnapshotV3,
        predecessor_snapshot_digest: Option<Digest32>,
        observed_unix_ms: u64,
    ) -> ExternalContextAuthorityFuture<'a>;
}

pub type ProviderTerminalAttestationFuture<'a> = Pin<
    Box<
        dyn Future<
                Output = Result<
                    IndependentProviderTerminalAttestationV3,
                    ExternalContextSecurityErrorV3,
                >,
            > + Send
            + 'a,
    >,
>;

pub trait ProviderTerminalAttestationSourceV3: Send + Sync {
    fn source_digest(&self) -> Digest32;

    fn attestation_for<'a>(
        &'a self,
        attempt_id: &'a StableId,
        exact_body_digest: Digest32,
        provider_receipt_digest: Digest32,
        terminal_observation_digest: Digest32,
        observed_unix_ms: u64,
    ) -> ProviderTerminalAttestationFuture<'a>;
}

pub struct ContextSecurityCapabilitiesV3 {
    pub authority_provider: Arc<dyn ExternalContextAuthorityProviderV3>,
    pub tokenizer_executor: Arc<dyn ImmutableTokenizerExecutorV3>,
    pub attempt_lease_authority: Arc<dyn ContextAttemptLeaseAuthorityV3>,
    pub attempt_journal: Arc<dyn ContextAttemptJournalV3>,
    pub generation_anchor: Arc<dyn ContextMonotonicGenerationAnchorV3>,
    pub terminal_attestation_source: Arc<dyn ProviderTerminalAttestationSourceV3>,
    pub terminal_attestation_verifier: Arc<dyn ProviderTerminalAttestationVerifierV3>,
}

impl ContextSecurityCapabilitiesV3 {
    pub fn validate(&self) -> Result<(), ExternalContextSecurityErrorV3> {
        for digest in [
            self.authority_provider.provider_digest(),
            self.tokenizer_executor.executor_digest(),
            self.attempt_lease_authority.authority_digest(),
            self.attempt_journal.journal_digest(),
            self.generation_anchor.anchor_digest(),
            self.terminal_attestation_source.source_digest(),
            self.terminal_attestation_verifier.verifier_digest(),
        ] {
            if digest.is_zero() {
                return Err(ExternalContextSecurityErrorV3::InvalidCapability);
            }
        }
        Ok(())
    }
}

impl fmt::Debug for ContextSecurityCapabilitiesV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ContextSecurityCapabilitiesV3")
            .field(
                "authority_provider_digest",
                &self.authority_provider.provider_digest(),
            )
            .field(
                "tokenizer_executor_digest",
                &self.tokenizer_executor.executor_digest(),
            )
            .field(
                "attempt_lease_authority_digest",
                &self.attempt_lease_authority.authority_digest(),
            )
            .field("attempt_journal_digest", &self.attempt_journal.journal_digest())
            .field("generation_anchor_digest", &self.generation_anchor.anchor_digest())
            .field(
                "terminal_attestation_source_digest",
                &self.terminal_attestation_source.source_digest(),
            )
            .field(
                "terminal_attestation_verifier_digest",
                &self.terminal_attestation_verifier.verifier_digest(),
            )
            .finish()
    }
}

#[derive(Default)]
pub struct ContextSecurityRuntimeV3 {
    capabilities: OnceLock<Arc<ContextSecurityCapabilitiesV3>>,
}

impl ContextSecurityRuntimeV3 {
    #[must_use]
    pub const fn new() -> Self {
        Self {
            capabilities: OnceLock::new(),
        }
    }

    pub fn attach(
        &self,
        capabilities: Arc<ContextSecurityCapabilitiesV3>,
    ) -> Result<(), ExternalContextSecurityErrorV3> {
        capabilities.validate()?;
        self.capabilities
            .set(capabilities)
            .map_err(|_| ExternalContextSecurityErrorV3::AlreadyAttached)
    }

    pub fn capabilities(
        &self,
    ) -> Result<Arc<ContextSecurityCapabilitiesV3>, ExternalContextSecurityErrorV3> {
        self.capabilities
            .get()
            .cloned()
            .ok_or(ExternalContextSecurityErrorV3::NotAttached)
    }

    #[must_use]
    pub fn is_attached(&self) -> bool {
        self.capabilities.get().is_some()
    }
}

impl fmt::Debug for ContextSecurityRuntimeV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ContextSecurityRuntimeV3")
            .field("attached", &self.is_attached())
            .finish()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ExternalContextSecurityErrorV3 {
    InvalidCapability,
    NotAttached,
    AlreadyAttached,
    AuthorityRejected,
    TokenizerRejected,
    LeaseRejected,
    JournalRejected,
    GenerationRejected,
    TerminalAttestationRejected,
}

impl ExternalContextSecurityErrorV3 {
    #[must_use]
    pub const fn code(self) -> &'static str {
        match self {
            Self::InvalidCapability => "context_security_invalid_capability",
            Self::NotAttached => "context_security_not_attached",
            Self::AlreadyAttached => "context_security_already_attached",
            Self::AuthorityRejected => "context_security_authority_rejected",
            Self::TokenizerRejected => "context_security_tokenizer_rejected",
            Self::LeaseRejected => "context_security_lease_rejected",
            Self::JournalRejected => "context_security_journal_rejected",
            Self::GenerationRejected => "context_security_generation_rejected",
            Self::TerminalAttestationRejected => {
                "context_security_terminal_attestation_rejected"
            }
        }
    }
}

impl fmt::Display for ExternalContextSecurityErrorV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.code())
    }
}

impl std::error::Error for ExternalContextSecurityErrorV3 {}
