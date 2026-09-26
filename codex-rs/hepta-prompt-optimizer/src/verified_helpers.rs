fn stable_pair(left: &StableId, right: &StableId) -> (StableId, StableId) {
    if left <= right {
        (left.clone(), right.clone())
    } else {
        (right.clone(), left.clone())
    }
}

fn map_registry_error(error: PromptRegistryV2Error) -> VerifiedPromptError {
    match error {
        PromptRegistryV2Error::SnapshotStale
        | PromptRegistryV2Error::RequiredFactorUnavailable
        | PromptRegistryV2Error::InvalidExpiry => {
            VerifiedPromptError::Stale(PromptStaleReasonV2::RegistryRevisionOrRevocation)
        }
        PromptRegistryV2Error::ReadLimitExceeded
        | PromptRegistryV2Error::PayloadUnavailable => {
            VerifiedPromptError::Unavailable(format!("{error:?}"))
        }
        PromptRegistryV2Error::EmptyDigest(_)
        | PromptRegistryV2Error::DigestMismatch(_)
        | PromptRegistryV2Error::ZeroTokenCost
        | PromptRegistryV2Error::InvalidModelVersion
        | PromptRegistryV2Error::InvalidFrontier
        | PromptRegistryV2Error::DuplicateFactorFilter(_)
        | PromptRegistryV2Error::NonCanonicalRequiredFactors
        | PromptRegistryV2Error::NonCanonicalBindings
        | PromptRegistryV2Error::PayloadDigestMismatch
        | PromptRegistryV2Error::AuthorityGranted => {
            VerifiedPromptError::Corrupt(format!("{error:?}"))
        }
    }
}

fn scale_rate(rate: FixedQ32, units: u64) -> Result<FixedQ32, VerifiedPromptError> {
    if rate < FixedQ32::ZERO {
        return Err(VerifiedPromptError::InvalidPricing(
            "negative rate".to_owned(),
        ));
    }
    let product = i128::from(rate.raw())
        .checked_mul(i128::from(units))
        .ok_or(VerifiedPromptError::Arithmetic)?;
    let raw = i64::try_from(product).map_err(|_| VerifiedPromptError::Arithmetic)?;
    Ok(FixedQ32::from_raw(raw))
}

fn ensure_digest(name: &'static str, digest: Digest32) -> Result<(), VerifiedPromptError> {
    if digest.is_zero() {
        return Err(VerifiedPromptError::EmptyDigest(name));
    }
    Ok(())
}

fn push_ids(bytes: &mut Vec<u8>, values: &[StableId]) {
    push_len(bytes, values.len());
    for value in values {
        push_id(bytes, value);
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len());
    bytes.extend_from_slice(raw);
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    bytes.extend_from_slice(&u64::try_from(value).unwrap_or(u64::MAX).to_be_bytes());
}
