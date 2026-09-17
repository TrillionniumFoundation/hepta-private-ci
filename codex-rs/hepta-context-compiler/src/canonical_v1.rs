//! Canonical cross-module `ContextCompilationReceiptV1` projection.
//!
//! V2 remains the richer owner-native compilation object. This module emits the
//! registered V1 protocol without weakening the V2 generation/model/tokenizer
//! checks or claiming that compilation proves provider delivery.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CompiledContextV2;
use crate::ContextCompilerV2Error;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextCompilationReceiptV1 {
    pub compilation_id: StableId,
    pub objective_digest: Digest32,
    pub portfolio_digest: Digest32,
    pub model_tuple_digest: Digest32,
    pub messages_digest: Digest32,
    pub token_upper_bound: u32,
    pub truncation_policy_digest: Digest32,
    pub untrusted_instruction_count: u32,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ContextCanonicalV1Error {
    Native(ContextCompilerV2Error),
    EmptyDigest(&'static str),
    TokenCountOverflow,
    UntrustedInstructionUpgrade,
    AuthorityGranted,
    ReceiptDigestMismatch,
}

impl fmt::Display for ContextCanonicalV1Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ContextCanonicalV1Error {}

impl From<ContextCompilerV2Error> for ContextCanonicalV1Error {
    fn from(value: ContextCompilerV2Error) -> Self {
        Self::Native(value)
    }
}

impl ContextCompilationReceiptV1 {
    pub fn from_compiled_v2(
        compiled: &CompiledContextV2,
        model_tuple_digest: Digest32,
    ) -> Result<Self, ContextCanonicalV1Error> {
        compiled.validate()?;
        ensure_digest("model_tuple", model_tuple_digest)?;
        let token_upper_bound = u32::try_from(compiled.receipt.token_upper_bound)
            .map_err(|_| ContextCanonicalV1Error::TokenCountOverflow)?;
        // V2 enforces role separation before compilation: untrusted evidence may
        // be present, but it cannot be upgraded into a trusted instruction. The
        // registered V1 field therefore records zero successful untrusted
        // instruction upgrades rather than counting evidence messages.
        let untrusted_instruction_count = 0;
        let mut receipt = Self {
            compilation_id: compiled.receipt.compilation_id.clone(),
            objective_digest: compiled.receipt.objective_digest,
            portfolio_digest: compiled.receipt.prompt_portfolio_digest,
            model_tuple_digest,
            messages_digest: compiled.receipt.context_digest,
            token_upper_bound,
            truncation_policy_digest: compiled.receipt.truncation_policy_digest,
            untrusted_instruction_count,
            receipt_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        receipt.receipt_digest = Digest32::of_bytes(&receipt.semantic_json_bytes());
        receipt.validate()?;
        Ok(receipt)
    }

    pub fn validate(&self) -> Result<(), ContextCanonicalV1Error> {
        for (name, digest) in [
            ("objective", self.objective_digest),
            ("portfolio", self.portfolio_digest),
            ("model_tuple", self.model_tuple_digest),
            ("messages", self.messages_digest),
            ("truncation_policy", self.truncation_policy_digest),
            ("receipt", self.receipt_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.token_upper_bound == 0 {
            return Err(ContextCanonicalV1Error::TokenCountOverflow);
        }
        if self.untrusted_instruction_count != 0 {
            return Err(ContextCanonicalV1Error::UntrustedInstructionUpgrade);
        }
        if self.authority.grants_any() {
            return Err(ContextCanonicalV1Error::AuthorityGranted);
        }
        if self.receipt_digest != Digest32::of_bytes(&self.semantic_json_bytes()) {
            return Err(ContextCanonicalV1Error::ReceiptDigestMismatch);
        }
        Ok(())
    }

    pub fn to_canonical_json(&self) -> Result<Vec<u8>, ContextCanonicalV1Error> {
        self.validate()?;
        Ok(self.semantic_json_bytes())
    }

    fn semantic_json_bytes(&self) -> Vec<u8> {
        format!(
            "{{\"compilationId\":\"{}\",\"objectiveDigest\":\"{}\",\"portfolioDigest\":\"{}\",\"modelTupleDigest\":\"{}\",\"messagesDigest\":\"{}\",\"tokenUpperBound\":{},\"truncationPolicyDigest\":\"{}\",\"untrustedInstructionCount\":{}}}",
            self.compilation_id,
            self.objective_digest,
            self.portfolio_digest,
            self.model_tuple_digest,
            self.messages_digest,
            self.token_upper_bound,
            self.truncation_policy_digest,
            self.untrusted_instruction_count,
        )
        .into_bytes()
    }
}

fn ensure_digest(
    name: &'static str,
    digest: Digest32,
) -> Result<(), ContextCanonicalV1Error> {
    if digest.is_zero() {
        return Err(ContextCanonicalV1Error::EmptyDigest(name));
    }
    Ok(())
}
