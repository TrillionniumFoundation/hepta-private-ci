//! Explicit profile dispatch; V1 bytes/signatures never become V2 cycle evidence.
use crate::CalibrationPreflightError;
use crate::SignedCalibrationPreflightDecisionV1;
use crate::SignedCalibrationPreflightRequestV1;
use codex_hepta_learning_ledger::CalibrationCycleScopeV2;
use codex_hepta_learning_ledger::FixedCalibrationPublicationV1;
use codex_hepta_learning_ledger::FixedCalibrationPublicationV2;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_types::FixedQ32;
type HostResult<T> = Result<T, Box<dyn std::error::Error>>;
pub(crate) fn profile_matches(config: &str, cycle: Option<bool>) -> bool {
    match config {
        "hepta.fixed-calibration-evaluator-config.v1" => cycle.is_none_or(|c| !c),
        "hepta.fixed-calibration-evaluator-config.v2" => cycle.is_none_or(|c| c),
        _ => false,
    }
}
pub(crate) fn result_schema(cycle: bool) -> &'static str {
    if cycle {
        "hepta.fixed-independent-calibration-evaluation.v2"
    } else {
        "hepta.fixed-independent-calibration-evaluation.v1"
    }
}
pub(crate) fn read_publication(
    bytes: &[u8],
) -> HostResult<(
    FixedCalibrationPublicationV1,
    Option<CalibrationCycleScopeV2>,
)> {
    let value: serde_json::Value = serde_json::from_slice(bytes)?;
    if value.get("schema").is_some() {
        let publication: FixedCalibrationPublicationV2 = serde_json::from_slice(bytes)?;
        publication.signing_payload()?;
        let scope = publication.cycle.native()?;
        Ok((publication.into_original_fields(), Some(scope)))
    } else {
        Ok((serde_json::from_slice(bytes)?, None))
    }
}
pub(crate) fn preflight_payload(
    cut: &[u8],
    margin: FixedQ32,
    cycle: bool,
) -> Result<Vec<u8>, CalibrationPreflightError> {
    if cycle {
        crate::calibration_cycle_preflight_signing_payload_v2(cut, margin)
    } else {
        crate::calibration_preflight_signing_payload_v1(cut, margin)
    }
}
pub(crate) fn decide_profile(
    request: SignedCalibrationPreflightRequestV1<'_>,
    cycle: Option<&CalibrationCycleScopeV2>,
    verifier: &LearningEvidenceVerifierV1,
    now: u64,
) -> Result<SignedCalibrationPreflightDecisionV1, CalibrationPreflightError> {
    if let Some(scope) = cycle {
        crate::decide_with_signed_calibration_cycle_v2(request, scope, verifier, now)
    } else {
        crate::decide_with_signed_calibration_preflight_v1(request, verifier, now)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn versioned_calibration_does_not_reinterpret_original_signatures_or_configuration() {
        assert!(profile_matches(
            "hepta.fixed-calibration-evaluator-config.v1",
            Some(false)
        ));
        assert!(profile_matches(
            "hepta.fixed-calibration-evaluator-config.v2",
            Some(true)
        ));
        assert!(!profile_matches(
            "hepta.fixed-calibration-evaluator-config.v1",
            Some(true)
        ));
        assert!(!profile_matches(
            "hepta.fixed-calibration-evaluator-config.v2",
            Some(false)
        ));
        assert!(!profile_matches("unknown", None));
        assert_ne!(
            preflight_payload(b"same-original-preimage", FixedQ32::ZERO, false).unwrap(),
            preflight_payload(b"same-original-preimage", FixedQ32::ZERO, true).unwrap()
        );
    }
}
pub(crate) fn verify_actual_reviewer(
    signer: &codex_hepta_learning_ledger::TrustedLearningSignerV1,
    program: codex_hepta_types::Digest32,
    root_key: &[u8; 32],
    uid: u32,
    gid: u32,
    cycle: Option<&CalibrationCycleScopeV2>,
) -> HostResult<()> {
    let launcher = codex_hepta_types::Digest32::of_bytes(
        &codex_hepta_learning_ledger::read_root_review_input(
            std::path::Path::new("/usr/bin/setpriv"),
            16 * 1024 * 1024,
        )?,
    );
    let manager = codex_hepta_types::Digest32::of_bytes(
        &codex_hepta_learning_ledger::read_root_review_input(
            std::path::Path::new("/usr/bin/systemd-run"),
            16 * 1024 * 1024,
        )?,
    );
    let approval = cycle.map(|c| c.current_program_approval_digest);
    verify_reviewer_binding(
        signer,
        &reviewer_controller(program, uid, gid, launcher, manager, approval),
        root_key,
    )
}
fn reviewer_controller(
    program: codex_hepta_types::Digest32,
    uid: u32,
    gid: u32,
    launcher: codex_hepta_types::Digest32,
    manager: codex_hepta_types::Digest32,
    approval: Option<codex_hepta_types::Digest32>,
) -> String {
    format!("fixed-no-custody-reviewer.{}",codex_hepta_types::Digest32::of_bytes(&[program.as_array().as_slice(),approval.as_ref().map_or(&[][..],|v|v.as_array().as_slice()),uid.to_be_bytes().as_slice(),gid.to_be_bytes().as_slice(),launcher.as_array(),manager.as_array(),b"no-sudo;no-caps;no-groups;no-new-privileges;read-only-anchored-cut;denied-gold-and-other-keys"].concat()))
}
fn verify_reviewer_binding(
    signer: &codex_hepta_learning_ledger::TrustedLearningSignerV1,
    controller: &str,
    root_key: &[u8; 32],
) -> HostResult<()> {
    let credential = codex_hepta_types::Digest32::of_bytes(
        &[
            root_key.as_slice(),
            signer.verifying_key.as_slice(),
            controller.as_bytes(),
        ]
        .concat(),
    );
    if signer.controller_id.as_str() != controller
        || signer.principal.credential_chain_digest != credential
        || signer.principal.signing_key_digest
            != codex_hepta_types::Digest32::of_bytes(&signer.verifying_key)
        || signer.roles != [codex_hepta_learning_ledger::LearningEvidenceRoleV1::Evaluator]
    {
        return Err("admitted reviewer controller/credential is not actual approved immutable program/UID/key".into());
    }
    Ok(())
}
#[cfg(test)]
mod program_binding_tests {
    use super::*;
    use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
    use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
    use codex_hepta_learning_ledger::TrustedLearningSignerV1;
    use codex_hepta_types::Digest32;
    use codex_hepta_types::StableId;
    fn digest(s: &str) -> Digest32 {
        Digest32::of_bytes(s.as_bytes())
    }
    #[test]
    fn actual_program_approval_changes_controller_and_credential_even_with_same_uid_key_and_role() {
        let original = reviewer_controller(
            digest("old-code"),
            994,
            978,
            digest("fixed-setpriv"),
            digest("fixed-systemd"),
            None,
        );
        let successor = reviewer_controller(
            digest("new-code"),
            994,
            978,
            digest("fixed-setpriv"),
            digest("fixed-systemd"),
            Some(digest("actual-frozen-approval")),
        );
        assert_ne!(original, successor);
        let root = [40; 32];
        let public = [41; 32];
        let mut signer = TrustedLearningSignerV1 {
            principal: AuthenticatedPrincipalV1 {
                principal_id: StableId::new("fixed-no-custody-reviewer").unwrap(),
                credential_chain_digest: Digest32::of_bytes(
                    &[root.as_slice(), public.as_slice(), original.as_bytes()].concat(),
                ),
                signing_key_digest: Digest32::of_bytes(&public),
                scope_digest: digest("fixed-scope"),
                authority_epoch: 1,
                authenticated_at: 1,
                expires_at: 100,
            },
            controller_id: StableId::new(&original).unwrap(),
            verifying_key: public,
            roles: vec![LearningEvidenceRoleV1::Evaluator],
            revoked_at: None,
        };
        assert!(verify_reviewer_binding(&signer, &original, &root).is_ok());
        assert!(verify_reviewer_binding(&signer, &successor, &root).is_err());
        signer.controller_id = StableId::new(&successor).unwrap();
        assert!(verify_reviewer_binding(&signer, &successor, &root).is_err());
        signer.principal.credential_chain_digest = Digest32::of_bytes(
            &[root.as_slice(), public.as_slice(), successor.as_bytes()].concat(),
        );
        assert!(verify_reviewer_binding(&signer, &successor, &root).is_ok());
        assert!(
            verify_reviewer_binding(
                &signer,
                &reviewer_controller(
                    digest("new-code"),
                    994,
                    978,
                    digest("fixed-setpriv"),
                    digest("fixed-systemd"),
                    Some(digest("different-approval"))
                ),
                &root
            )
            .is_err()
        );
    }
}
