//! Admit independently signed bytes through the private original Root owner.
//! Hashing a physical image here does not decode labels or consume a holdout.
//! Only the later original provider can decode and release that exact image.

use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;

use super::super::admission::OriginalBAuthorities;
use super::super::provider::OriginalBReleasedSource;
use super::super::source_peer::OriginalBSourcePeer;
use super::*;
use crate::root_independent_b_protocol::digest;
use crate::root_independent_b_source_protocol::*;

impl OriginalRootIndependentBEvaluationFilesV1 {
    pub(in super::super) fn retain_original_signed_source(
        &self,
        service: &HostAuthorityService,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        owner: &OwnedFd,
        source_peer: &OriginalBSourcePeer,
        frame_end: Instant,
        request: &SourceRequest,
    ) -> io::Result<Vec<u8>> {
        let end = self.end.min(frame_end);
        OriginalBRecord::inspect(&self.record, end, |enrollment| {
            if request.schema != 1
                || request.purpose != PURPOSE
                || request.binding != self.original_binding().to_string()
            {
                return Err(io::Error::other("original B source purpose differs"));
            }
            let state = self
                .state
                .try_lock()
                .map_err(|_| io::Error::other("B custody busy"))?;
            let files = &state.files;
            let response = service.with_learning_profile(
                config,
                registration,
                owner,
                &self.profile,
                |actual, _| {
                    owner_alive(owner, end)?;
                    source_peer.require_live()?;
                    if actual != self.initial || source_peer.lifetime != files.source_peer {
                        return Err(io::Error::other("original B ingress context differs"));
                    }
                    let now = service.original_learning_unix_seconds()?;
                    require_files(files, enrollment, now)?;
                    let (_, authorities) = files.admitted_protocol(&actual, now)?;
                    let before = self
                        .backend
                        .restore(&actual.request)
                        .map_err(io::Error::other)?;
                    let scope = self.profile.require_cell_scope(&actual)?;
                    let current = before
                        .as_ref()
                        .ok_or_else(|| io::Error::other("original B Training checkpoint absent"))?;
                    scope.validate_snapshot(current).map_err(io::Error::other)?;
                    if current.training_no_update_v2().is_some()
                        || training_prefix(current)? != *current
                        || enrollment.realized_training_head
                            != Some(current.head_digest.into_array())
                        || enrollment.realized_plan.is_none()
                        || enrollment.cell_images.is_none()
                    {
                        return Err(io::Error::other(
                            "B source admission requires the actual prepared Training candidate",
                        ));
                    }
                    drop(files.source.original_readonly()?);
                    let source = files.source.read_stable(SOURCE_BOUND)?;
                    let source_digest = Digest32::of_bytes(&source);
                    if digest(&request.source_digest)? != source_digest {
                        return Err(io::Error::other("original B source digest differs"));
                    }
                    let observed_payload = [OBSERVATION_DOMAIN, source_digest.as_array()].concat();
                    let observed = require_statement_bytes(
                        &authorities,
                        &authorities.observer,
                        LearningEvidenceRoleV1::Observer,
                        &request.observed_statement,
                        Some(&observed_payload),
                        now,
                    )?;
                    let policy = require_statement_bytes(
                        &authorities,
                        &authorities.generator,
                        LearningEvidenceRoleV1::Generator,
                        &request.policy_statement,
                        None,
                        now,
                    )?;
                    if policy.issued_at < enrollment.registered_at_seconds
                        || observed.issued_at <= policy.issued_at
                        || observed.issued_at > now
                    {
                        return Err(io::Error::other(
                            "B source statements precede original registration",
                        ));
                    }
                    let observed_digest = Digest32::of_bytes(&request.observed_statement);
                    let policy_digest = Digest32::of_bytes(&request.policy_statement);
                    let cut = OriginalBReleasedSource::from_original_digests(
                        source_digest,
                        observed_digest,
                        policy_digest,
                    );
                    if let Some(previous) = &enrollment.admitted_source {
                        if previous != &cut {
                            return Err(io::Error::other("original B source admission changed"));
                        }
                        previous.require_original(files)?;
                    } else {
                        if enrollment.released_source.is_some()
                            || enrollment.completed_receipt.is_some()
                        {
                            return Err(io::Error::other(
                                "B source cannot be admitted after release",
                            ));
                        }
                        files
                            .observed_statement
                            .write_original_signed_input_once(&request.observed_statement)?;
                        files
                            .policy_statement
                            .write_original_signed_input_once(&request.policy_statement)?;
                        cut.require_original(files)?;
                        enrollment.admitted_source = Some(cut);
                    }
                    if files.source.read_stable(SOURCE_BOUND)? != source
                        || self
                            .backend
                            .restore(&actual.request)
                            .map_err(io::Error::other)?
                            != before
                    {
                        return Err(io::Error::other(
                            "B source or current checkpoint changed during admission",
                        ));
                    }
                    source_peer.require_live()?;
                    owner_alive(owner, end)?;
                    let response = SourceAcknowledgement {
                        schema: 1,
                        purpose: PURPOSE.into(),
                        binding: self.original_binding().to_string(),
                        source_digest: source_digest.to_string(),
                        observed_digest: observed_digest.to_string(),
                        policy_digest: policy_digest.to_string(),
                    };
                    let bytes = serde_json::to_vec(&response).map_err(io::Error::other)?;
                    if bytes.len() > FRAME_BOUND {
                        return Err(io::Error::other("B source acknowledgement oversized"));
                    }
                    Ok(bytes)
                },
            )?;
            // These checks follow the complete original Root context. Ready
            // means input retention, never reply delivery or B completion.
            owner_alive(owner, end)?;
            source_peer.require_live()?;
            require_files(files, enrollment, service.original_learning_unix_seconds()?)?;
            enrollment
                .admitted_source
                .as_ref()
                .ok_or_else(|| io::Error::other("B source admission absent"))?
                .require_original(files)?;
            Ok(response)
        })
    }
}

fn require_statement_bytes(
    authorities: &OriginalBAuthorities,
    signer: &TrustedLearningSignerV1,
    role: LearningEvidenceRoleV1,
    bytes: &[u8],
    expected: Option<&[u8]>,
    now: u64,
) -> io::Result<SignedLearningEvidenceV1> {
    if bytes.is_empty() || bytes.len() > FRAME_BOUND {
        return Err(io::Error::other("bounded original B statement required"));
    }
    let (payload, signed) =
        crate::learning_owner_evidence::decode(bytes).map_err(io::Error::other)?;
    if crate::learning_owner_evidence::encode(&payload, &signed).map_err(io::Error::other)? != bytes
        || expected.is_some_and(|expected| expected != payload)
        || (expected.is_none()
            && (payload.len() != POLICY_DOMAIN.len() + 32 || !payload.starts_with(POLICY_DOMAIN)))
    {
        return Err(io::Error::other("canonical original B statement differs"));
    }
    let verified = authorities
        .verifier
        .verify(role, &signed, &payload, now)
        .map_err(io::Error::other)?;
    if verified.principal() != &signer.principal
        || verified.controller_id() != &signer.controller_id
    {
        return Err(io::Error::other(
            "B source signer differs from the fixed original role",
        ));
    }
    Ok(signed)
}
