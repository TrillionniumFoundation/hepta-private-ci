//! Test-only seeding through the existing authenticated production writer.
//! No legacy-write feature or production authority bypass is required.

// Test fixtures fail immediately when their setup assumptions are invalid.
#![allow(clippy::expect_used, clippy::unwrap_used)]

use std::fs::OpenOptions;
use std::path::Path;

use codex_hepta_learning_ledger as ledger;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

/// Seed a signed decision, retain its independent witness, then reopen the
/// read-only journal used by these plasticity owner/recovery fixtures.
pub fn seed_authenticated_decision(
    path: &Path,
    binding: Digest32,
    maximum_records: usize,
    decision: ledger::EpisodeDecision,
) -> ledger::DurableLedger {
    assert_eq!(
        decision.completeness,
        ledger::CandidateSetCompleteness::Complete
    );
    let scope = digest("plasticity-fixture-learning-scope");
    let key = SigningKey::from_bytes(&[28; 32]);
    let root_key = SigningKey::from_bytes(&[29; 32]);
    let root = ledger::LearningTrustRootV1 {
        root_id: id("plasticity-fixture-root"),
        scope_digest: scope,
        verifying_key: root_key.verifying_key().to_bytes(),
        valid_from: 1,
        expires_at: 200,
        revoked_at: None,
    };
    let generator = id("plasticity-fixture-generator");
    let mut distribution = ledger::SignedLearningTrustDistributionV1 {
        distribution: ledger::LearningTrustDistributionV1 {
            distribution_id: id("plasticity-fixture-trust"),
            generation: 1,
            effective_at: 20,
            trust: ledger::LearningEvidenceTrustV1 {
                scope_digest: scope,
                objective_digest: decision.objective_digest,
                authority_epoch: 7,
                signers: vec![ledger::TrustedLearningSignerV1 {
                    principal: ledger::AuthenticatedPrincipalV1 {
                        principal_id: generator.clone(),
                        credential_chain_digest: digest("plasticity-fixture-credential"),
                        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                        scope_digest: scope,
                        authority_epoch: 7,
                        authenticated_at: 10,
                        expires_at: 100,
                    },
                    controller_id: id("plasticity-fixture-controller"),
                    verifying_key: key.verifying_key().to_bytes(),
                    roles: vec![ledger::LearningEvidenceRoleV1::Generator],
                    revoked_at: None,
                }],
            },
        },
        root_id: root.root_id.clone(),
        issued_at: 15,
        expires_at: 90,
        signature: [0; 64],
    };
    distribution.signature = root_key
        .sign(&distribution.signing_bytes().unwrap())
        .to_bytes();
    let trust = ledger::activate_learning_trust(
        &root,
        distribution,
        /*previous*/ None,
        /*now*/ 50,
    )
    .unwrap();
    let create = |path: &Path| {
        OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(path)
            .unwrap()
    };
    let durable = ledger::DurableLedger::create(create(path), binding, maximum_records).unwrap();
    let witness =
        ledger::LedgerWitnessStore::create(create(&path.with_extension("witness")), binding)
            .unwrap();
    let mut directory_options = OpenOptions::new();
    directory_options.read(true);
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        const FILE_FLAG_BACKUP_SEMANTICS: u32 = 0x0200_0000;
        directory_options.custom_flags(FILE_FLAG_BACKUP_SEMANTICS);
    }
    let directory = directory_options.open(path.parent().unwrap()).unwrap();
    let mut writer =
        ledger::LedgerWriter::from_durable(durable, witness, trust, &directory, &directory)
            .unwrap();
    let request = ledger::ProductionDecisionV2 {
        record_id: decision.record_id,
        episode_id: decision.episode_id,
        run_snapshot_digest: digest("plasticity-fixture-run-snapshot"),
        objective_digest: decision.objective_digest,
        policy_digest: Digest32::of_bytes(decision.policy_id.as_str().as_bytes()),
        candidate_ids: decision.candidate_ids.clone(),
        selected_candidate_id: decision.selected_candidate_id,
        selected_propensity: decision.selected_propensity,
        completeness: ledger::CandidateSetCompletenessReceiptV1 {
            set_id: id("plasticity-fixture-candidate-set"),
            state_digest: digest("plasticity-fixture-state"),
            generator_id: generator.clone(),
            generator_code_digest: digest("plasticity-fixture-generator-code"),
            grammar_digest: digest("plasticity-fixture-grammar"),
            hard_filter_digest: digest("plasticity-fixture-hard-filter"),
            truncation_digest: digest("plasticity-fixture-truncation"),
            candidates_digest: ledger::candidate_ids_digest_v2(&decision.candidate_ids),
            candidate_count: u32::try_from(decision.candidate_ids.len()).unwrap(),
            omitted_count_bound: 0,
            canonical_order_digest: ledger::candidate_order_digest_v2(&decision.candidate_ids),
            complete_for_generator: true,
        },
        support_digest: decision.support_digest,
    };
    let mut evidence = ledger::SignedLearningEvidenceV1 {
        evidence_id: id("plasticity-fixture-decision-evidence"),
        principal_id: generator,
        role: ledger::LearningEvidenceRoleV1::Generator,
        trust_digest: writer.verifier().trust_digest(),
        scope_digest: scope,
        objective_digest: request.objective_digest,
        authority_epoch: 7,
        issued_at: 20,
        expires_at: 90,
        payload_digest: Digest32::of_bytes(&ledger::decision_signing_payload_v2(&request).unwrap()),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    writer
        .append_decision(Digest32::ZERO, request, &evidence, /*now*/ 50)
        .unwrap();
    let anchor = writer.witness_frontier().unwrap().anchor;
    drop(writer);
    ledger::DurableLedger::recover(
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(path)
            .unwrap(),
        binding,
        maximum_records,
        ledger::LedgerRecovery::Acknowledged(anchor),
    )
    .unwrap()
}
