//! Additive binding for the entire caller-supplied context candidate set.
//!
//! This owner-local, native Rust surface is not a registered cross-module port
//! or wire-protocol version and does not assert that the caller supplied every
//! eligible item. It preserves the existing compilation result and adds an
//! integrity binding for exactly the bounded items the caller did supply,
//! including items omitted by packing.

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::CompilationRequest;
use crate::CompilationRequirementsV1;
use crate::ContextCompilationReceipt;
use crate::ContextItem;
use crate::ContextRole;
use crate::Error;
use crate::compile;
use crate::compile_with_requirements;
use crate::push_id;

/// An owner-local, crate-native, caller-relative candidate-set binding.
///
/// `caller_candidate_set_digest` proves only byte-level consistency with the
/// items admitted to this function. It is not a completeness, freshness,
/// source-authentication, revocation, delivery, or selection receipt.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CandidateBoundContextCompilationReceipt {
    pub compilation: ContextCompilationReceipt,
    pub caller_candidate_count: usize,
    pub caller_candidate_set_digest: Digest32,
    pub binding_digest: Digest32,
    pub authority: AuthorityPosture,
}

/// Preserve `compile` semantics while binding every caller-supplied item.
pub fn compile_candidate_bound(
    request: CompilationRequest,
) -> Result<CandidateBoundContextCompilationReceipt, Error> {
    let compilation = compile(request.clone())?;
    Ok(bind_candidate_set(request, compilation))
}

/// Preserve `compile_with_requirements` semantics while binding every
/// caller-supplied item. The legacy context digest continues to bind the exact
/// mandatory-group semantics.
pub fn compile_candidate_bound_with_requirements(
    request: CompilationRequest,
    requirements: CompilationRequirementsV1,
) -> Result<CandidateBoundContextCompilationReceipt, Error> {
    let compilation = compile_with_requirements(request.clone(), requirements)?;
    Ok(bind_candidate_set(request, compilation))
}

fn bind_candidate_set(
    mut request: CompilationRequest,
    compilation: ContextCompilationReceipt,
) -> CandidateBoundContextCompilationReceipt {
    request.items.sort_by(|left, right| {
        left.role
            .cmp(&right.role)
            .then_with(|| left.item_id.cmp(&right.item_id))
    });
    let caller_candidate_count = request.items.len();
    let caller_candidate_set_digest = digest_items(&request.items);

    let mut bytes = b"hepta.context.candidate-bound-receipt.v1".to_vec();
    push_id(&mut bytes, &request.compilation_id);
    bytes.extend_from_slice(request.run_snapshot_digest.as_array());
    bytes.extend_from_slice(request.objective_digest.as_array());
    bytes.extend_from_slice(&request.token_budget.to_be_bytes());
    push_len(&mut bytes, caller_candidate_count);
    bytes.extend_from_slice(caller_candidate_set_digest.as_array());
    bytes.extend_from_slice(compilation.context_digest.as_array());
    bytes.extend_from_slice(&compilation.used_tokens.to_be_bytes());
    push_ids(&mut bytes, &compilation.trusted_instruction_ids);
    push_ids(&mut bytes, &compilation.untrusted_evidence_ids);
    push_ids(&mut bytes, &compilation.omitted_ids);

    CandidateBoundContextCompilationReceipt {
        compilation,
        caller_candidate_count,
        caller_candidate_set_digest,
        binding_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    }
}

fn digest_items(items: &[ContextItem]) -> Digest32 {
    let mut bytes = b"hepta.context.caller-candidate-set.v1".to_vec();
    push_len(&mut bytes, items.len());
    for item in items {
        bytes.push(match item.role {
            ContextRole::TrustedInstruction => 0,
            ContextRole::UntrustedEvidence => 1,
        });
        push_id(&mut bytes, &item.item_id);
        bytes.extend_from_slice(item.content_digest.as_array());
        bytes.extend_from_slice(item.source_digest.as_array());
        bytes.extend_from_slice(&item.token_count.to_be_bytes());
        bytes.push(u8::from(item.contains_secret));
    }
    Digest32::of_bytes(&bytes)
}

fn push_ids(bytes: &mut Vec<u8>, values: &[codex_hepta_types::StableId]) {
    push_len(bytes, values.len());
    for value in values {
        push_id(bytes, value);
    }
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    bytes.extend_from_slice(&u64::try_from(value).unwrap_or(u64::MAX).to_be_bytes());
}

#[cfg(test)]
#[path = "candidate_bound_tests.rs"]
mod tests;
