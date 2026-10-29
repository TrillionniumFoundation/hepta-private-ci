//! PQ installation reconstructs root authority, a protected clock and an
//! independent current-distribution floor before opening mutable history.
use super::*;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::authority_trust_unix::UnixPqAuthorityClock;
use codex_hepta_contracts::authority_trust_unix::UnixPqLearningTrustFrontier;
use codex_hepta_contracts::authority_trust_unix::UnixPqTrustEndpointConfig;
use codex_hepta_learning_ledger::LearningAuthenticationProfile;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningTrustDistributionV1;
use codex_hepta_learning_ledger::LearningTrustRootV1;
use codex_hepta_learning_ledger::SignedLearningTrustDistributionV1;
use codex_hepta_learning_ledger::activate_learning_trust;
use std::sync::Arc;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct PqLearningActivationV2 {
    root_id: Id,
    root_scope_digest: Digest,
    root_verifying_key: LearningKey,
    root_valid_from: u64,
    root_expires_at: u64,
    root_revoked_at: Option<u64>,
    distribution_id: Id,
    generation: u64,
    effective_at: u64,
    issued_at: u64,
    expires_at: u64,
    signature: LearningSignature,
    clock: UnixPqTrustEndpointConfig,
    frontier: UnixPqTrustEndpointConfig,
}

pub(super) struct LoadedTrust {
    pub verifier: LearningEvidenceVerifierV1,
    pub clock: Option<Arc<dyn AuthorityClock>>,
}

pub(super) fn load(
    trust: LearningEvidenceTrustV1,
    profile: LearningAuthenticationProfile,
    activation: Option<PqLearningActivationV2>,
    binding: Digest32,
    identity: &AgentdIdentity,
) -> Result<LoadedTrust, AgentdError> {
    match (profile, activation) {
        (LearningAuthenticationProfile::ClassicalV1, None) => {
            let verifier = LearningEvidenceVerifierV1::new(trust)
                .map_err(|error| invalid(&error.to_string()))?;
            if verifier.authentication_profile() != profile {
                return Err(invalid("learning authentication profile mismatch"));
            }
            Ok(LoadedTrust {
                verifier,
                clock: None,
            })
        }
        (LearningAuthenticationProfile::MlDsa65V2, Some(activation)) => {
            for path in [
                &activation.clock.socket_path,
                &activation.frontier.socket_path,
            ] {
                let canonical = path
                    .canonicalize()
                    .map_err(|error| invalid(&format!("PQ authority service path: {error}")))?;
                if &canonical != path {
                    return Err(invalid("PQ authority service path must be canonical"));
                }
                for owned in [&identity.home_root, &identity.run_root, &identity.workspace] {
                    let owned = match owned.canonicalize() {
                        Ok(canonical) => canonical,
                        Err(error) if error.kind() == std::io::ErrorKind::NotFound => owned.clone(),
                        Err(error) => return Err(invalid(&format!("Agentd owner path: {error}"))),
                    };
                    if canonical.starts_with(&owned) {
                        return Err(invalid(
                            "PQ authority services must be outside Agentd-owned paths",
                        ));
                    }
                }
            }
            let clock: Arc<dyn AuthorityClock> = Arc::new(
                UnixPqAuthorityClock::new(activation.clock)
                    .map_err(|error| invalid(&error.to_string()))?,
            );
            let frontier = Arc::new(
                UnixPqLearningTrustFrontier::new(activation.frontier)
                    .map_err(|error| invalid(&error.to_string()))?,
            );
            let root = LearningTrustRootV1 {
                root_id: activation.root_id.into(),
                scope_digest: activation.root_scope_digest.into(),
                verifying_key: activation.root_verifying_key.into(),
                valid_from: activation.root_valid_from,
                expires_at: activation.root_expires_at,
                revoked_at: activation.root_revoked_at,
            };
            let signed = SignedLearningTrustDistributionV1 {
                distribution: LearningTrustDistributionV1 {
                    distribution_id: activation.distribution_id.into(),
                    generation: activation.generation,
                    effective_at: activation.effective_at,
                    trust,
                },
                root_id: root.root_id.clone(),
                issued_at: activation.issued_at,
                expires_at: activation.expires_at,
                signature: activation.signature.into(),
            };
            let clock = Some(clock);
            let activated =
                activate_learning_trust(&root, signed, /*previous*/ None, now_micros(&clock)?)
                    .map_err(|error| invalid(&format!("PQ root distribution: {error}")))?
                    .with_trust_frontier(binding, frontier)
                    .map_err(|error| invalid(&format!("PQ learning frontier: {error}")))?;
            let authority_clock = clock
                .as_ref()
                .ok_or_else(|| invalid("PQ protected clock missing"))?
                .clone();
            let verifier = activated
                .verifier()
                .clone()
                .with_microsecond_authority_clock(authority_clock)
                .map_err(|error| invalid(&error.to_string()))?;
            if verifier.authentication_profile() != profile {
                return Err(invalid("PQ activation contains a classic learning role"));
            }
            Ok(LoadedTrust { verifier, clock })
        }
        (LearningAuthenticationProfile::ClassicalV1, Some(_))
        | (LearningAuthenticationProfile::MlDsa65V2, None) => Err(invalid(
            "PQ installation requires explicit root distribution, protected clock and independent frontier",
        )),
    }
}

pub(super) fn now_micros(clock: &Option<Arc<dyn AuthorityClock>>) -> Result<u64, AgentdError> {
    match clock {
        Some(clock) => clock
            .now_unix_ms()
            .map_err(|error| invalid(&error.to_string()))?
            .checked_mul(1_000)
            .ok_or_else(|| invalid("PQ protected clock overflow")),
        None => u64::try_from(
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map_err(|error| invalid(&error.to_string()))?
                .as_micros(),
        )
        .map_err(|error| invalid(&error.to_string())),
    }
}

#[cfg(all(test, target_os = "linux"))]
#[path = "cognitive_process_pq_trust_tests.rs"]
mod tests;
