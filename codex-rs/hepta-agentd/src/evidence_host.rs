//! Agentd-owned product composition for kernel.evidence.
//!
//! A production process retains the issuer digest admitted by its signed
//! external frontier. Replacing the owner registry never silently re-enrolls it.

use std::path::PathBuf;
use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_agent_protocol::KernelEvidenceAppendIngress;
use codex_hepta_agent_protocol::KernelEvidenceCandidateV1;
use codex_hepta_agent_protocol::KernelEvidenceQueryV1;
use codex_hepta_agent_protocol::KernelEvidenceResult;
use codex_hepta_agent_protocol::KernelEvidenceVerifyV1;
use codex_hepta_agent_protocol::MAX_KERNEL_EVIDENCE_ENVELOPE_BYTES;
use codex_hepta_authbus::SignedMessage;
use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_evidence::EvidenceCandidateV1;
use codex_hepta_evidence::EvidenceClaimClassV1;
use codex_hepta_evidence::EvidenceIssuerRoleV1;
use codex_hepta_evidence::EvidenceVerificationProfileV1;
use codex_hepta_evidence::EvidenceVerificationSummaryV1;
use codex_hepta_evidence::HeptaEvidenceStore;
use codex_hepta_evidence::ProfiledVerifyChainRequestV1;
use codex_hepta_evidence::QualificationEvidenceEnvelopeV1;
use codex_hepta_evidence::VerifiedEvidenceTrustSnapshot;
use codex_hepta_evidence::qualification_append_scope_digest;
use codex_hepta_evidence::qualification_envelope_bytes;
use codex_hepta_evidence::qualification_subject;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdState;
use crate::authbus_trust::hex_bytes;

pub(crate) enum EvidenceRuntimeProfile {
    Development {
        recovery_frontier: Option<(PathBuf, PathBuf)>,
    },
    Production {
        descriptor: PathBuf,
        signer_trust_file: PathBuf,
    },
}

/// These modes have intentionally different trust-refresh semantics.
enum EvidenceTrustMode {
    Development,
    Production {
        admitted_registry_sha256: Sha256Digest,
    },
}

pub(crate) struct EvidenceHost {
    pub(crate) store: HeptaEvidenceStore,
    trust_file: PathBuf,
    trust_mode: EvidenceTrustMode,
}

impl EvidenceHost {
    pub(crate) async fn open(
        identity: &AgentdIdentity,
        trust_file: PathBuf,
        profile: EvidenceRuntimeProfile,
    ) -> Result<Self, AgentdError> {
        let production_profile = matches!(profile, EvidenceRuntimeProfile::Production { .. });
        let home = AbsolutePathBuf::from_absolute_path(&identity.home_root)?;
        let sqlite = SqliteConfig::from_sqlite_home(home);
        let preflight_snapshot = if production_profile {
            let preflight = HeptaEvidenceStore::open_existing_read_only(&sqlite)
                .await
                .map_err(evidence_error)?;
            let snapshot = preflight
                .authenticated_recovery_snapshot()
                .await
                .map_err(evidence_error)?;
            preflight.close().await;
            Some(snapshot)
        } else {
            None
        };
        let store = if production_profile {
            HeptaEvidenceStore::open_existing_runtime(&sqlite)
                .await
                .map_err(evidence_error)?
        } else {
            HeptaEvidenceStore::open(&sqlite)
                .await
                .map_err(evidence_error)?
        };
        if let Some(expected) = preflight_snapshot {
            let actual = store
                .authenticated_recovery_snapshot()
                .await
                .map_err(evidence_error)?;
            if actual != expected {
                store.close().await;
                return Err(invalid(
                    "production evidence database changed between read-only migration preflight and restricted runtime open",
                ));
            }
        }
        let trust_mode = match profile {
            EvidenceRuntimeProfile::Production {
                descriptor,
                signer_trust_file,
            } => {
                let admitted_registry_sha256 =
                    crate::evidence_production::verify_production_evidence_frontier(
                        identity,
                        &store,
                        &trust_file,
                        &descriptor,
                        &signer_trust_file,
                    )
                    .await?;
                VerifiedEvidenceTrustSnapshot::load_owner_registry(
                    &store,
                    &trust_file,
                    identity.agent_id.as_str(),
                    Some(&admitted_registry_sha256),
                )
                .map_err(evidence_error)?;
                EvidenceTrustMode::Production {
                    admitted_registry_sha256,
                }
            }
            EvidenceRuntimeProfile::Development {
                recovery_frontier: Some((frontier, signer_trust_file)),
            } => {
                crate::evidence_frontier::verify_evidence_recovery_frontier(
                    identity,
                    &store,
                    &frontier,
                    &signer_trust_file,
                )
                .await?;
                VerifiedEvidenceTrustSnapshot::load_owner_registry(
                    &store,
                    &trust_file,
                    identity.agent_id.as_str(),
                    None,
                )
                .map_err(evidence_error)?;
                EvidenceTrustMode::Development
            }
            EvidenceRuntimeProfile::Development {
                recovery_frontier: None,
            } => {
                VerifiedEvidenceTrustSnapshot::load_owner_registry(
                    &store,
                    &trust_file,
                    identity.agent_id.as_str(),
                    None,
                )
                .map_err(evidence_error)?;
                EvidenceTrustMode::Development
            }
        };
        Ok(Self {
            store,
            trust_file,
            trust_mode,
        })
    }

    fn trust(&self, state: &AgentdState) -> Result<VerifiedEvidenceTrustSnapshot, AgentdError> {
        let pin = match &self.trust_mode {
            EvidenceTrustMode::Development => None,
            EvidenceTrustMode::Production {
                admitted_registry_sha256,
            } => Some(admitted_registry_sha256),
        };
        VerifiedEvidenceTrustSnapshot::load_owner_registry(
            &self.store,
            &self.trust_file,
            state.identity().agent_id.as_str(),
            pin,
        )
        .map_err(evidence_error)
    }
}

/// Claims an external producer signs. Creates no key or independent authority.
pub fn kernel_evidence_claims(
    issuer_id: &str,
    key_epoch: u64,
    message_id: &str,
    sequence: u64,
    expires_at_ms: u64,
    envelope: &QualificationEvidenceEnvelopeV1,
) -> Result<SignedMessageClaims, AgentdError> {
    let envelope_bytes = qualification_envelope_bytes(envelope).map_err(evidence_error)?;
    if envelope_bytes.len() > MAX_KERNEL_EVIDENCE_ENVELOPE_BYTES {
        return Err(invalid(
            "Agentd evidence envelope exceeds the 48 KiB product-wire ceiling",
        ));
    }
    Ok(SignedMessageClaims {
        issuer_id: StableId::new(issuer_id.to_string())
            .map_err(|error| invalid(&error.to_string()))?,
        key_epoch: Generation::new(key_epoch).map_err(|error| invalid(&error.to_string()))?,
        message_id: StableId::new(message_id.to_string())
            .map_err(|error| invalid(&error.to_string()))?,
        subject_id: qualification_subject(&envelope.candidate, envelope.issuer_role)
            .map_err(evidence_error)?,
        scope_digest: qualification_append_scope_digest(),
        payload_digest: Digest32::of_bytes(&envelope_bytes),
        sequence,
        expires_at_ms,
    })
}

pub(crate) async fn append(
    state: &AgentdState,
    request: KernelEvidenceAppendIngress,
) -> Result<KernelEvidenceResult, AgentdError> {
    require_ready(state)?;
    let host = attached(state)?;
    if request.envelope_json.len() > MAX_KERNEL_EVIDENCE_ENVELOPE_BYTES {
        return Err(invalid("evidence envelope exceeds product-wire ceiling"));
    }
    let envelope: QualificationEvidenceEnvelopeV1 = serde_json::from_str(&request.envelope_json)
        .map_err(|error| invalid(&format!("invalid evidence envelope: {error}")))?;
    let canonical = qualification_envelope_bytes(&envelope).map_err(evidence_error)?;
    if canonical.as_slice() != request.envelope_json.as_bytes() {
        return Err(invalid("evidence envelope must use canonical JSON"));
    }
    let claims = kernel_evidence_claims(
        &request.issuer_id,
        request.key_epoch,
        &request.message_id,
        request.sequence,
        request.expires_at_ms,
        &envelope,
    )?;
    let trust = host.trust(state)?;
    let issuer = trust
        .issuer_for(&request.issuer_id, request.key_epoch, envelope.issuer_role)
        .map_err(evidence_error)?;
    let message = SignedMessage {
        claims,
        signature: hex_bytes(&request.signature_hex)?,
    };
    let evidence_id = host
        .store
        .qualification()
        .append_receipt(&issuer, &message, &envelope)
        .await
        .map_err(evidence_error)?;
    require_ready(state)?;
    result(&evidence_id)
}

pub(crate) async fn query(
    state: &AgentdState,
    request: KernelEvidenceQueryV1,
) -> Result<KernelEvidenceResult, AgentdError> {
    require_ready(state)?;
    let host = attached(state)?;
    let page_selector = request
        .page_selector()
        .map_err(|error| invalid(&error))?
        .map(|(claim, after_seq, limit)| (claim.to_string(), after_seq, limit));
    let candidate = candidate(request.candidate)?;
    if let Some((claim, after_seq, limit)) = page_selector {
        let claim_class = EvidenceClaimClassV1::parse(&claim).map_err(|error| invalid(&error))?;
        let page = host
            .store
            .query_qualification_claim_page(&candidate, claim_class, after_seq, usize::from(limit))
            .await
            .map_err(evidence_error)?;
        require_ready(state)?;
        return result(&page);
    }
    let claim_class =
        EvidenceClaimClassV1::parse(&request.claim_class).map_err(|error| invalid(&error))?;
    let references = host
        .store
        .qualification()
        .query_claim(&candidate, claim_class)
        .await
        .map_err(evidence_error)?;
    require_ready(state)?;
    result(&references)
}

pub(crate) async fn verify(
    state: &AgentdState,
    request: KernelEvidenceVerifyV1,
) -> Result<KernelEvidenceResult, AgentdError> {
    require_ready(state)?;
    let host = attached(state)?;
    let profile_name = request
        .profile_name()
        .map_err(|error| invalid(&error))?
        .map(str::to_string);
    let candidate = candidate(request.candidate)?;
    let profile = if let Some(profile_name) = profile_name.as_deref() {
        EvidenceVerificationProfileV1::parse(profile_name).map_err(|error| invalid(&error))?
    } else {
        let claim_class =
            EvidenceClaimClassV1::parse(&request.claim_class).map_err(|error| invalid(&error))?;
        if request.required_roles.len()
            > codex_hepta_agent_protocol::MAX_KERNEL_EVIDENCE_REQUIRED_ROLES
        {
            return Err(invalid("too many required evidence roles"));
        }
        let roles = request
            .required_roles
            .iter()
            .map(|role| EvidenceIssuerRoleV1::parse(role).map_err(|error| invalid(&error)))
            .collect::<Result<Vec<_>, _>>()?;
        EvidenceVerificationProfileV1::from_legacy_roles(claim_class, &roles)
            .map_err(evidence_error)?
    };
    let profiled_request =
        ProfiledVerifyChainRequestV1::new(candidate, profile, current_time_millis()?)
            .map_err(evidence_error)?;
    let current_trust = host.trust(state)?;
    let disposition = host
        .store
        .qualification()
        .verify_chain(&profiled_request, &current_trust)
        .await
        .map_err(evidence_error)?;
    require_ready(state)?;
    if profile_name.is_some() {
        let summary = EvidenceVerificationSummaryV1::from_disposition(profile, &disposition)
            .map_err(evidence_error)?;
        result(&summary)
    } else {
        result(&disposition)
    }
}

fn candidate(candidate: KernelEvidenceCandidateV1) -> Result<EvidenceCandidateV1, AgentdError> {
    let candidate = EvidenceCandidateV1 {
        candidate_id: candidate.candidate_id,
        source_commit: candidate.source_commit,
        source_tree: candidate.source_tree,
    };
    candidate.validate().map_err(|error| invalid(&error))?;
    Ok(candidate)
}

fn result<T: serde::Serialize>(value: &T) -> Result<KernelEvidenceResult, AgentdError> {
    let json = serde_json::to_string(value)?;
    if json.len() > MAX_KERNEL_EVIDENCE_ENVELOPE_BYTES {
        return Err(invalid(
            "kernel evidence result exceeds the bounded Agentd response profile",
        ));
    }
    Ok(KernelEvidenceResult { json })
}

fn attached(state: &AgentdState) -> Result<Arc<EvidenceHost>, AgentdError> {
    state
        .evidence
        .get()
        .cloned()
        .ok_or_else(|| invalid("no explicit evidence trust configuration"))
}

fn require_ready(state: &AgentdState) -> Result<(), AgentdError> {
    if !state.automation_admission_ready()? {
        return Err(invalid(
            "Agent generation is not ready for kernel evidence operations",
        ));
    }
    Ok(())
}

fn current_time_millis() -> Result<u64, AgentdError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| invalid(&format!("system clock is before Unix epoch: {error}")))?
        .as_millis();
    u64::try_from(millis).map_err(|error| invalid(&format!("system clock overflow: {error}")))
}

fn evidence_error(error: codex_hepta_evidence::EvidenceError) -> AgentdError {
    invalid(&error.to_string())
}

fn invalid(message: &str) -> AgentdError {
    AgentdError::Invalid(format!("kernel.evidence: {message}"))
}
