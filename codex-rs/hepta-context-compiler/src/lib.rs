//! Source-aware context compiler.
//!
//! Trusted instructions and untrusted evidence remain separate sections. The
//! compiler accepts digests, never raw secrets, and cannot call a model.

#![forbid(unsafe_code)]

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const MAX_ITEMS: usize = 4_096;
const MAX_TOKENS: u64 = 1_000_000;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum ContextRole {
    TrustedInstruction,
    UntrustedEvidence,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextItem {
    pub item_id: StableId,
    pub role: ContextRole,
    pub content_digest: Digest32,
    pub source_digest: Digest32,
    pub token_count: u64,
    pub contains_secret: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompilationRequest {
    pub compilation_id: StableId,
    pub run_snapshot_digest: Digest32,
    pub objective_digest: Digest32,
    pub token_budget: u64,
    pub items: Vec<ContextItem>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextCompilationReceipt {
    pub compilation_id: StableId,
    pub trusted_instruction_ids: Vec<StableId>,
    pub untrusted_evidence_ids: Vec<StableId>,
    pub omitted_ids: Vec<StableId>,
    pub used_tokens: u64,
    pub context_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    ItemLimitExceeded,
    InvalidTokenBudget,
    EmptyDigest(&'static str),
    DuplicateItem(String),
    ZeroTokenItem(String),
    SecretRejected(String),
    Arithmetic,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

pub fn compile(mut request: CompilationRequest) -> Result<ContextCompilationReceipt, Error> {
    if request.items.len() > MAX_ITEMS {
        return Err(Error::ItemLimitExceeded);
    }
    if request.token_budget == 0 || request.token_budget > MAX_TOKENS {
        return Err(Error::InvalidTokenBudget);
    }
    if request.run_snapshot_digest.is_zero() {
        return Err(Error::EmptyDigest("run snapshot"));
    }
    if request.objective_digest.is_zero() {
        return Err(Error::EmptyDigest("objective"));
    }
    request.items.sort_by(|left, right| {
        left.role
            .cmp(&right.role)
            .then_with(|| left.item_id.cmp(&right.item_id))
    });
    let mut seen = BTreeSet::new();
    let mut trusted = Vec::new();
    let mut evidence = Vec::new();
    let mut omitted = Vec::new();
    let mut used_tokens = 0_u64;
    let mut included = Vec::new();

    for item in request.items {
        if !seen.insert(item.item_id.clone()) {
            return Err(Error::DuplicateItem(item.item_id.to_string()));
        }
        if item.content_digest.is_zero() || item.source_digest.is_zero() {
            return Err(Error::EmptyDigest("context item"));
        }
        if item.token_count == 0 {
            return Err(Error::ZeroTokenItem(item.item_id.to_string()));
        }
        if item.contains_secret {
            return Err(Error::SecretRejected(item.item_id.to_string()));
        }
        let Some(next_total) = used_tokens.checked_add(item.token_count) else {
            return Err(Error::Arithmetic);
        };
        if next_total > request.token_budget {
            omitted.push(item.item_id);
            continue;
        }
        used_tokens = next_total;
        match item.role {
            ContextRole::TrustedInstruction => trusted.push(item.item_id.clone()),
            ContextRole::UntrustedEvidence => evidence.push(item.item_id.clone()),
        }
        included.push(item);
    }

    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.context.compilation.v1");
    push_id(&mut bytes, &request.compilation_id);
    bytes.extend_from_slice(request.run_snapshot_digest.as_array());
    bytes.extend_from_slice(request.objective_digest.as_array());
    bytes.extend_from_slice(&request.token_budget.to_be_bytes());
    for item in included {
        bytes.push(match item.role {
            ContextRole::TrustedInstruction => 0,
            ContextRole::UntrustedEvidence => 1,
        });
        push_id(&mut bytes, &item.item_id);
        bytes.extend_from_slice(item.content_digest.as_array());
        bytes.extend_from_slice(item.source_digest.as_array());
        bytes.extend_from_slice(&item.token_count.to_be_bytes());
    }

    Ok(ContextCompilationReceipt {
        compilation_id: request.compilation_id,
        trusted_instruction_ids: trusted,
        untrusted_evidence_ids: evidence,
        omitted_ids: omitted,
        used_tokens,
        context_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;
