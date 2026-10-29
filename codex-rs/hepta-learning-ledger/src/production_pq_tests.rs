//! Actual product writer, separate witness and external distribution frontier.
use super::*;
use crate::LearningAuthenticationProfile;
use crate::LearningSignature;
use crate::LearningVerificationKey;
use crate::LedgerSegmentLimits;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::sync::Mutex;

#[path = "production_pq_clock_tests.rs"]
mod clock;

const PQ: LearningAuthenticationProfile = LearningAuthenticationProfile::MlDsa65V2;

fn key(seed: u8) -> PqNativeSigningKey {
    let spki = PqNativeSigningKey::public_spki_from_seed(&[seed; 32].into());
    PqNativeSigningKey::from_owned_seed(
        [seed; 32].into(),
        ml_dsa_65_key_id_from_spki(&spki).unwrap(),
    )
    .unwrap()
}
fn sign_pq(key: &PqNativeSigningKey, bytes: &[u8]) -> LearningSignature {
    LearningSignature::MlDsa65V2(key.sign_exact_message(bytes).unwrap().to_vec())
}
fn pq_trust() -> LearningEvidenceTrustV1 {
    let mut trust = trust();
    for signer in &mut trust.signers {
        let key = key(seed(signer.principal.principal_id.as_str()) + 40);
        signer.verifying_key = LearningVerificationKey::MlDsa65V2(key.public_spki().to_vec());
        signer.principal.signing_key_digest = Digest32::of_bytes(key.public_spki());
    }
    trust
}
fn pq_principal(name: &str) -> AuthenticatedPrincipalV1 {
    pq_trust()
        .signers
        .into_iter()
        .find(|signer| signer.principal.principal_id == id(name))
        .unwrap()
        .principal
}
fn distribution(generation: u64) -> (LearningTrustRootV1, SignedLearningTrustDistributionV1) {
    let key = key(/*seed*/ 99);
    let root = LearningTrustRootV1 {
        root_id: id("learning-root"),
        scope_digest: digest("scope"),
        verifying_key: LearningVerificationKey::MlDsa65V2(key.public_spki().to_vec()),
        valid_from: 1,
        expires_at: 200,
        revoked_at: None,
    };
    let mut signed = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: id("pq-distribution"),
            generation,
            effective_at: 20,
            trust: pq_trust(),
        },
        root_id: root.root_id.clone(),
        issued_at: 15,
        expires_at: 90,
        signature: LearningSignature::MlDsa65V2(Vec::new()),
    };
    signed.signature = sign_pq(&key, &signed.signing_bytes().unwrap());
    (root, signed)
}
fn activated() -> ActivatedLearningTrustV1 {
    let (root, signed) = distribution(/*generation*/ 1);
    activate_learning_trust(&root, signed, /*previous*/ None, /*now*/ 50).unwrap()
}
fn evidence(
    verifier: &LearningEvidenceVerifierV1,
    name: &str,
    role: LearningEvidenceRoleV1,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let mut signed = sign(verifier, name, role, payload);
    signed.signature = LearningSignature::MlDsa65V2(Vec::new());
    signed.signature = sign_pq(&key(seed(name) + 40), &signed.signing_bytes());
    signed
}
struct MemoryFrontier(Mutex<LearningTrustFrontier>);
impl AuthorityFrontierStore<LearningTrustFrontier> for MemoryFrontier {
    fn load(&self, owner_id: &str) -> Result<LearningTrustFrontier, AuthorityTrustError> {
        if owner_id != format!("hepta-learning-trust:{}", binding()) {
            return Err(AuthorityTrustError::Invalid);
        }
        self.0
            .lock()
            .map(|value| *value)
            .map_err(|_| AuthorityTrustError::Unavailable)
    }
    fn compare_and_set(
        &self,
        owner_id: &str,
        expected: &LearningTrustFrontier,
        next: &LearningTrustFrontier,
    ) -> Result<(), AuthorityTrustError> {
        if owner_id != format!("hepta-learning-trust:{}", binding()) {
            return Err(AuthorityTrustError::Invalid);
        }
        let mut value = self
            .0
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        if *value != *expected || next.generation != expected.generation + 1 {
            return Err(AuthorityTrustError::Conflict);
        }
        *value = *next;
        Ok(())
    }
}
fn frontier(trust: &ActivatedLearningTrustV1) -> Arc<MemoryFrontier> {
    Arc::new(MemoryFrontier(Mutex::new(crate::learning_trust_frontier(
        trust,
    ))))
}

#[test]
fn pq_product_writer_authenticates_real_rows_freeze_rotation_and_cold_restart() {
    let fixture = Fixture::new();
    let trust = activated();
    let frontier = frontier(&trust);
    let ledger = DurableLedger::create_with_authentication_profile(
        fixture.file("ledger"),
        binding(),
        /*max_records*/ 64,
        PQ,
    )
    .unwrap();
    let witness = LedgerWitnessStore::create_with_authentication_profile(
        fixture.file("witness"),
        binding(),
        PQ,
    )
    .unwrap();
    let mut writer = LedgerWriter::from_durable_with_trust_frontier(
        ledger,
        witness,
        trust.clone(),
        &fixture.directory(),
        &fixture.directory(),
        frontier.clone(),
    )
    .unwrap();
    let request = decision();
    let signed = evidence(
        writer.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        &decision_signing_payload_v2(&request).unwrap(),
    );
    let receipt = writer
        .append_decision(Digest32::ZERO, request.clone(), &signed, /*now*/ 50)
        .unwrap();
    assert_eq!(
        writer
            .append_decision(Digest32::ZERO, request.clone(), &signed, /*now*/ 50)
            .unwrap()
            .disposition,
        AppendDisposition::IdempotentReplay
    );
    let mut forged = signed.clone();
    forged.signature[0] ^= 1;
    assert!(
        writer
            .append_decision(Digest32::ZERO, request.clone(), &forged, /*now*/ 50)
            .is_err()
    );
    forged.signature = [0; 64].into();
    assert!(
        writer
            .append_decision(Digest32::ZERO, request, &forged, /*now*/ 50)
            .is_err()
    );
    let mut observed = outcome(
        "pq-outcome-record",
        "pq-outcome",
        /*predecessor*/ None,
        /*value*/ 100,
    );
    observed.observer = pq_principal("observer");
    let signed_outcome = evidence(
        writer.verifier(),
        "observer",
        LearningEvidenceRoleV1::Observer,
        &outcome_signing_payload_v2(&observed),
    );
    let final_receipt = writer
        .append_outcome(
            receipt.chain_digest,
            observed,
            &signed_outcome,
            /*now*/ 50,
        )
        .unwrap();
    let snapshot = writer.snapshot().unwrap();
    assert_eq!(snapshot.authentication_profile(), PQ);
    let plan = DatasetFreezePlanV2 {
        snapshot_id: id("pq-dataset"),
        objective_digest: digest("objective"),
        inclusion_policy_digest: digest("include"),
    };
    let freeze = evidence(
        writer.verifier(),
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        &dataset_freeze_signing_payload_v2(&snapshot, &plan).unwrap(),
    );
    let dataset = writer.freeze_dataset(plan, &freeze, /*now*/ 50).unwrap();
    writer
        .revalidate_dataset_snapshot(&dataset, /*now*/ 89)
        .unwrap();
    assert!(
        writer
            .revalidate_dataset_snapshot(&dataset, /*now*/ 90)
            .is_err()
    );
    let (root, successor) = distribution(/*generation*/ 2);
    writer
        .rotate_trust(&root, successor.clone(), /*now*/ 51)
        .unwrap();
    let current_trust =
        activate_learning_trust(&root, successor, Some(&trust), /*now*/ 51).unwrap();
    assert_eq!(frontier.0.lock().unwrap().generation, 2);
    drop(writer);
    let anchor = LedgerRecovery::Acknowledged(LedgerAnchor {
        sequence: final_receipt.sequence.get(),
        chain_digest: final_receipt.chain_digest,
    });
    let ledger = DurableLedger::recover_with_authentication_profile(
        fixture.file("ledger"),
        binding(),
        /*max_records*/ 64,
        anchor,
        PQ,
    )
    .unwrap();
    let witness = LedgerWitnessStore::recover_with_authentication_profile(
        fixture.file("witness"),
        binding(),
        PQ,
    )
    .unwrap();
    assert!(matches!(
        LedgerWriter::from_durable_with_trust_frontier(
            ledger,
            witness,
            trust,
            &fixture.directory(),
            &fixture.directory(),
            frontier.clone()
        ),
        Err(ProductionLedgerError::TrustFrontier(
            AuthorityTrustError::Conflict
        ))
    ));
    let ledger = DurableLedger::recover_with_authentication_profile(
        fixture.file("ledger"),
        binding(),
        /*max_records*/ 64,
        anchor,
        PQ,
    )
    .unwrap();
    let witness = LedgerWitnessStore::recover_with_authentication_profile(
        fixture.file("witness"),
        binding(),
        PQ,
    )
    .unwrap();
    let writer = LedgerWriter::from_durable_with_trust_frontier(
        ledger,
        witness,
        current_trust,
        &fixture.directory(),
        &fixture.directory(),
        frontier.clone(),
    )
    .unwrap();
    assert_eq!(writer.snapshot().unwrap(), snapshot);
    frontier.0.lock().unwrap().generation += 1;
    assert!(writer.snapshot().is_err());
}

#[test]
fn pq_history_header_relabel_and_missing_independent_frontier_are_rejected() {
    let fixture = Fixture::new();
    let mut classic = fixture.writer();
    let request = decision();
    let signed = sign(
        classic.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        &decision_signing_payload_v2(&request).unwrap(),
    );
    classic
        .append_decision(Digest32::ZERO, request, &signed, /*now*/ 50)
        .unwrap();
    drop(classic);
    let mut old = fs::read(fixture.root.join("ledger")).unwrap();
    old[..8].copy_from_slice(b"HEPTLP02");
    let checksum = Digest32::of_bytes(&old[..40]);
    old[40..72].copy_from_slice(checksum.as_array());
    fs::write(fixture.root.join("ledger"), &old).unwrap();
    assert!(matches!(
        DurableLedger::recover_with_authentication_profile(
            fixture.file("ledger"),
            binding(),
            /*max_records*/ 64,
            LedgerRecovery::Unacknowledged,
            PQ
        ),
        Err(DurableLedgerError::Corrupt)
    ));
    assert_eq!(fs::read(fixture.root.join("ledger")).unwrap(), old);
    let fresh = Fixture::new();
    let ledger = DurableLedger::create_with_authentication_profile(
        fresh.file("ledger"),
        binding(),
        /*max_records*/ 64,
        PQ,
    )
    .unwrap();
    let witness = LedgerWitnessStore::create_with_authentication_profile(
        fresh.file("witness"),
        binding(),
        PQ,
    )
    .unwrap();
    assert!(matches!(
        LedgerWriter::from_durable(
            ledger,
            witness,
            activated(),
            &fresh.directory(),
            &fresh.directory()
        ),
        Err(ProductionLedgerError::TrustFrontier(
            AuthorityTrustError::Unavailable
        ))
    ));
}

#[test]
fn pq_segment_rotation_and_witness_replay_preserve_the_new_history_domain() {
    let fixture = Fixture::new();
    File::create(fixture.root.join("owner")).unwrap();
    File::create(fixture.root.join("next")).unwrap();
    let limits = LedgerSegmentLimits {
        records: 1,
        bytes: 8192,
    };
    let trust = activated();
    let frontier = frontier(&trust);
    let ledger = SegmentedLedger::create_with_authentication_profile(
        fixture.file("owner"),
        fixture.file("ledger"),
        binding(),
        limits,
        PQ,
    )
    .unwrap();
    let witness = LedgerWitnessStore::create_with_authentication_profile(
        fixture.file("witness"),
        binding(),
        PQ,
    )
    .unwrap();
    let mut writer = LedgerWriter::from_segmented_with_trust_frontier(
        ledger,
        witness,
        trust.clone(),
        &fixture.directory(),
        &fixture.directory(),
        frontier.clone(),
    )
    .unwrap();
    let first = decision();
    let signed = evidence(
        writer.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        &decision_signing_payload_v2(&first).unwrap(),
    );
    let receipt = writer
        .append_decision(Digest32::ZERO, first, &signed, /*now*/ 50)
        .unwrap();
    writer
        .rotate_segment(
            fixture.file("next"),
            LedgerAnchor {
                sequence: 1,
                chain_digest: receipt.chain_digest,
            },
            &fixture.directory(),
        )
        .unwrap();
    let mut next = decision();
    next.record_id = id("pq-next-record");
    next.episode_id = id("pq-next-episode");
    let signed = evidence(
        writer.verifier(),
        "generator",
        LearningEvidenceRoleV1::Generator,
        &decision_signing_payload_v2(&next).unwrap(),
    );
    writer
        .append_decision(receipt.chain_digest, next, &signed, /*now*/ 50)
        .unwrap();
    let expected = writer.snapshot().unwrap();
    let checkpoint = writer.segmented_checkpoint().unwrap().unwrap();
    drop(writer);
    assert!(
        SegmentedLedger::recover(
            fixture.file("owner"),
            vec![fixture.file("ledger"), fixture.file("next")],
            binding(),
            limits,
            checkpoint
        )
        .is_err()
    );
    let ledger = SegmentedLedger::recover_with_authentication_profile(
        fixture.file("owner"),
        vec![fixture.file("ledger"), fixture.file("next")],
        binding(),
        limits,
        checkpoint,
        PQ,
    )
    .unwrap();
    let witness = LedgerWitnessStore::recover_with_authentication_profile(
        fixture.file("witness"),
        binding(),
        PQ,
    )
    .unwrap();
    let writer = LedgerWriter::from_segmented_with_trust_frontier(
        ledger,
        witness,
        trust,
        &fixture.directory(),
        &fixture.directory(),
        frontier,
    )
    .unwrap();
    assert_eq!(writer.snapshot().unwrap(), expected);
}
