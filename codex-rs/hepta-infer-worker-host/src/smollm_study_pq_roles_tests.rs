//! Native study authentication and ledger replay; no model or efficacy claim.
use super::super::cognitive_process_evidence::LearningEvidenceTrustV1Raw;
use super::super::cognitive_process_evidence::SignedLearningEvidenceV1Raw;
use super::*;
use pretty_assertions::assert_eq;

#[test]
fn pq_study_role_wire_verifies_signatures_without_installation_activation() -> TestResult<()> {
    // Exercise the original study signer and process codecs without claiming
    // current authorization: this isolated fixture has no external activation.
    let mut roles = ControlledRoles::with_profile(
        hash("study-role-wire"),
        [id("yes"), id("no")],
        id("yes"),
        LearningAuthenticationProfile::MlDsa65V2,
    );
    let wire = serde_json::to_vec(&LearningEvidenceTrustV1Raw::from(roles.trust.clone()))?;
    let decoded: LearningEvidenceTrustV1Raw = serde_json::from_slice(&wire)?;
    let verifier = ledger::LearningEvidenceVerifierV1::new(decoded.into())?;
    assert_eq!(verifier.trust_digest(), roles.verifier.trust_digest());
    assert!(roles.pq_activation().is_err());
    let classic =
        FixtureSigningKey::new(LearningAuthenticationProfile::ClassicalV1, /*seed*/ 31)?;
    for index in 0..4 {
        let payload = format!("study-role-{index}");
        let signed = roles.sign(index, payload.as_bytes());
        let wire = serde_json::to_vec(&SignedLearningEvidenceV1Raw::from(signed))?;
        let decoded: SignedLearningEvidenceV1Raw = serde_json::from_slice(&wire)?;
        let evidence: ledger::SignedLearningEvidenceV1 = decoded.into();
        verifier.verify(evidence.role, &evidence, payload.as_bytes(), micros())?;
        let wrong_role = roles.trust.signers[(index + 1) % 4].roles[0];
        assert!(
            verifier
                .verify(wrong_role, &evidence, payload.as_bytes(), micros())
                .is_err()
        );
        let mut downgrade = evidence;
        downgrade.signature = classic.signature_template();
        downgrade.signature = classic.sign(&downgrade.signing_bytes())?;
        classic
            .verifying_key()
            .verify(&downgrade.signing_bytes(), &downgrade.signature)?;
        assert!(
            verifier
                .verify(downgrade.role, &downgrade, payload.as_bytes(), micros())
                .is_err()
        );
    }
    Ok(())
}

#[test]
fn ordinary_study_pq_roles_authenticate_and_reopen_the_original_training_ledger() -> TestResult<()>
{
    let directory = tempfile::tempdir()?;
    let profile = super::super::StudyProfile::BinaryDiverse60V3;
    let binding = profile.training_ledger_binding();
    let mut roles = ControlledRoles::new_pq(
        hash(super::super::diverse::OBJECTIVE),
        [id("yes"), id("no")],
        id("yes"),
        &directory.path().join("authority"),
        binding,
    )?;
    let payload = b"ordinary study generator evidence";
    let evidence = roles.sign(/*index*/ 0, payload);
    roles.verifier.verify(
        ledger::LearningEvidenceRoleV1::Generator,
        &evidence,
        payload,
        roles.authority_micros(),
    )?;
    let mut classic = evidence.clone();
    classic.signature = [0; 64].into();
    assert!(
        roles
            .verifier
            .verify(
                ledger::LearningEvidenceRoleV1::Generator,
                &classic,
                payload,
                roles.authority_micros(),
            )
            .is_err()
    );
    assert!(
        roles
            .verifier
            .verify(
                ledger::LearningEvidenceRoleV1::Selector,
                &evidence,
                payload,
                roles.authority_micros(),
            )
            .is_err()
    );
    let rows = super::super::diverse::training_rows()?;
    let owner = directory.path().join("training");
    let (dataset, snapshot) = roles.dataset(profile, &owner, &rows);
    let last = snapshot
        .records()
        .last()
        .ok_or("training ledger is empty")?;
    let reopened = ledger::DurableLedger::recover_with_authentication_profile(
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(owner.join("ledger"))?,
        binding,
        /*max_records*/ 512,
        ledger::LedgerRecovery::Acknowledged(ledger::LedgerAnchor {
            sequence: last.sequence.get(),
            chain_digest: last.chain_digest,
        }),
        LearningAuthenticationProfile::MlDsa65V2,
    )?;
    let recovered = reopened.snapshot()?;
    assert_eq!(
        recovered.authentication_profile(),
        LearningAuthenticationProfile::MlDsa65V2
    );
    assert_eq!(recovered.head_digest, snapshot.head_digest);
    ledger::verify_dataset_snapshot_receipt_against_ledger_v3(
        &dataset,
        &recovered,
        roles.authority_micros(),
    )?;
    Ok(())
}
