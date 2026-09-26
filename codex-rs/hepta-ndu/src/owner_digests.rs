use super::*;

pub(super) fn validate_context(context: &NduOwnerContextV1) -> Result<(), NduOwnerError> {
    if context.host_generation == 0 {
        return Err(NduOwnerError::InvalidContext("host generation"));
    }
    for (name, digest) in [
        ("principal scope", context.principal_scope_digest),
        ("fence", context.fence_digest),
        ("revocation frontier", context.revocation_frontier_digest),
    ] {
        if digest.is_zero() {
            return Err(NduOwnerError::InvalidContext(name));
        }
    }
    Ok(())
}

pub(super) fn production_policy_digest(
    policy: &NduProductionPolicyV1,
) -> Result<Digest32, NduOwnerError> {
    let utility = canonical_utility_profile_digest(&policy.utility_profile)?;
    let evaluation =
        canonical_evaluation_policy_digest(&policy.utility_profile, &policy.evaluation_policy)?;
    let scalarization = policy
        .scalarization
        .clone()
        .map(|profile| {
            crate::ValidatedScalarizationProfileV1::try_new(&policy.utility_profile, profile)
                .map(|validated| validated.scalarization_digest())
        })
        .transpose()?;

    let mut bytes = b"hepta.ndu.production-policy.v1\0".to_vec();
    bytes.extend_from_slice(utility.as_array());
    bytes.extend_from_slice(evaluation.as_array());
    match scalarization {
        Some(digest) => {
            bytes.push(1);
            bytes.extend_from_slice(digest.as_array());
        }
        None => bytes.push(0),
    }
    Ok(Digest32::of_bytes(&bytes))
}

pub(super) fn evaluation_source_context_digest(
    context: &NduOwnerContextV1,
    production_policy_digest: Digest32,
    objective_digest: Digest32,
    generation: Generation,
) -> Digest32 {
    let mut bytes = b"hepta.ndu.authenticated-evaluation-context.v1\0".to_vec();
    push_id(&mut bytes, &context.principal_id);
    push_id(&mut bytes, &context.owner_id);
    bytes.extend_from_slice(&context.host_generation.to_be_bytes());
    bytes.extend_from_slice(context.principal_scope_digest.as_array());
    bytes.extend_from_slice(context.fence_digest.as_array());
    bytes.extend_from_slice(context.revocation_frontier_digest.as_array());
    bytes.extend_from_slice(production_policy_digest.as_array());
    bytes.extend_from_slice(objective_digest.as_array());
    bytes.extend_from_slice(&generation.get().to_be_bytes());
    Digest32::of_bytes(&bytes)
}

pub(super) fn authenticated_evaluation_receipt_digest(
    source_context_digest: Digest32,
    evaluation: &NduEvaluationReceiptV2,
) -> Digest32 {
    let mut bytes = b"hepta.ndu.authenticated-evaluation-receipt.v1\0".to_vec();
    bytes.extend_from_slice(source_context_digest.as_array());
    bytes.extend_from_slice(evaluation.evaluation_policy_digest.as_array());
    bytes.extend_from_slice(evaluation.evaluation_digest_v2.as_array());
    Digest32::of_bytes(&bytes)
}

pub(super) fn owner_scope_digest(
    context: &NduOwnerContextV1,
    production_policy_digest: Digest32,
    objective_digest: Digest32,
    subject_digest: Digest32,
    mutation_tag: u8,
) -> Digest32 {
    let mut bytes = b"hepta.ndu.authenticated-owner-scope.v1\0".to_vec();
    push_id(&mut bytes, &context.principal_id);
    push_id(&mut bytes, &context.owner_id);
    bytes.extend_from_slice(&context.host_generation.to_be_bytes());
    bytes.extend_from_slice(context.principal_scope_digest.as_array());
    bytes.extend_from_slice(context.fence_digest.as_array());
    bytes.extend_from_slice(context.revocation_frontier_digest.as_array());
    bytes.extend_from_slice(production_policy_digest.as_array());
    bytes.extend_from_slice(objective_digest.as_array());
    bytes.extend_from_slice(subject_digest.as_array());
    bytes.push(mutation_tag);
    Digest32::of_bytes(&bytes)
}

pub(super) fn mutation_payload_digest(
    mutation: &NduOwnerMutationV1,
    production_policy_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.ndu.authenticated-owner-mutation.v1\0".to_vec();
    bytes.push(mutation.tag());
    if let NduOwnerMutationV1::AppendProjection { kind, .. } = mutation {
        bytes.push(match kind {
            NduProjectionKindV1::Preference => 0,
            NduProjectionKindV1::Utility => 1,
            NduProjectionKindV1::SelectedProjection => 2,
            NduProjectionKindV1::Revocation => 3,
        });
    }
    bytes.extend_from_slice(mutation.identity_digest().as_array());
    bytes.extend_from_slice(mutation.objective_digest().as_array());
    bytes.extend_from_slice(mutation.subject_digest().as_array());
    match mutation.expected_predecessor() {
        Some(expected_predecessor) => {
            bytes.push(1);
            bytes.extend_from_slice(expected_predecessor.as_array());
        }
        None => bytes.push(0),
    }
    bytes.extend_from_slice(mutation.projection_digest().as_array());
    bytes.extend_from_slice(production_policy_digest.as_array());
    Digest32::of_bytes(&bytes)
}

pub(super) fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}
