//! Deterministic test keys and rewards; never production trust or evidence.

use std::fs::File;
use std::fs::OpenOptions;

use codex_hepta_intelligence::ObservedOutcomeRequestV2;
use codex_hepta_intelligence::OutcomeCreditClosureRequestV2;
use codex_hepta_learning_ledger::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::checked;
use super::d;
use super::id;
use crate::circuit_credit::CircuitCreditSupportV1;

fn identity(role: LearningEvidenceRoleV1) -> (&'static str, u8) {
    match role {
        LearningEvidenceRoleV1::Generator => ("generator", 1),
        LearningEvidenceRoleV1::Observer => ("observer", 2),
        LearningEvidenceRoleV1::CreditAllocator => ("allocator", 3),
        LearningEvidenceRoleV1::Evaluator
        | LearningEvidenceRoleV1::UnlearningAuthority
        | LearningEvidenceRoleV1::Selector => panic!("unused fixture role"),
    }
}

fn trusted(role: LearningEvidenceRoleV1) -> TrustedLearningSignerV1 {
    let (name, seed) = identity(role);
    let key = SigningKey::from_bytes(&[seed; 32]);
    TrustedLearningSignerV1 {
        principal: AuthenticatedPrincipalV1 {
            principal_id: id(name),
            credential_chain_digest: d(&format!("{name}-chain")),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            scope_digest: d("scope"),
            authority_epoch: 1,
            authenticated_at: 0,
            expires_at: 100,
        },
        controller_id: id(&format!("{name}-controller")),
        verifying_key: key.verifying_key().to_bytes(),
        roles: vec![role],
        revoked_at: None,
    }
}

fn sign(
    writer: &LedgerWriter,
    role: LearningEvidenceRoleV1,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let (name, seed) = identity(role);
    let mut signed = SignedLearningEvidenceV1 {
        evidence_id: id(&format!("{name}:{}", Digest32::of_bytes(payload))),
        principal_id: id(name),
        role,
        trust_digest: writer.verifier().trust_digest(),
        scope_digest: d("scope"),
        objective_digest: d("objective"),
        authority_epoch: 1,
        issued_at: 20,
        expires_at: 90,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    signed.signature = SigningKey::from_bytes(&[seed; 32])
        .sign(&signed.signing_bytes())
        .to_bytes();
    signed
}

pub(super) struct LedgerFixture {
    pub(super) writer: LedgerWriter,
    _directory: tempfile::TempDir,
}

impl LedgerFixture {
    pub(super) fn new(domain: &str) -> Self {
        let directory = checked(tempfile::tempdir());
        let file = |name| {
            checked(
                OpenOptions::new()
                    .read(true)
                    .write(true)
                    .create_new(true)
                    .open(directory.path().join(name)),
            )
        };
        let ledger = checked(DurableLedger::create(
            file("ledger"),
            d(domain),
            /*max_records*/ 32,
        ));
        let witness = checked(LedgerWitnessStore::create(file("witness"), d(domain)));
        let key = SigningKey::from_bytes(&[99; 32]);
        let root = LearningTrustRootV1 {
            root_id: id("root"),
            scope_digest: d("scope"),
            verifying_key: key.verifying_key().to_bytes(),
            valid_from: 0,
            expires_at: 100,
            revoked_at: None,
        };
        let mut signed = SignedLearningTrustDistributionV1 {
            distribution: LearningTrustDistributionV1 {
                distribution_id: id("test-trust"),
                generation: 1,
                effective_at: 20,
                trust: LearningEvidenceTrustV1 {
                    scope_digest: d("scope"),
                    objective_digest: d("objective"),
                    authority_epoch: 1,
                    signers: [
                        LearningEvidenceRoleV1::Generator,
                        LearningEvidenceRoleV1::Observer,
                        LearningEvidenceRoleV1::CreditAllocator,
                    ]
                    .into_iter()
                    .map(trusted)
                    .collect(),
                },
            },
            root_id: root.root_id.clone(),
            issued_at: 15,
            expires_at: 90,
            signature: [0; 64],
        };
        signed.signature = key.sign(&checked(signed.signing_bytes())).to_bytes();
        let trust = checked(activate_learning_trust(
            &root, signed, /*previous*/ None, /*now*/ 50,
        ));
        let mut options = OpenOptions::new();
        options.read(true);
        #[cfg(windows)]
        {
            use std::os::windows::fs::OpenOptionsExt;
            options.custom_flags(0x0200_0000 | 0x0020_0000);
        }
        let directory_handle: File = checked(options.open(directory.path()));
        let writer = checked(LedgerWriter::from_durable(
            ledger,
            witness,
            trust,
            &directory_handle,
            &directory_handle,
        ));
        Self {
            writer,
            _directory: directory,
        }
    }

    pub(super) fn state(&self) -> (LedgerSnapshot, LedgerWitnessFrontier) {
        (
            checked(self.writer.snapshot()),
            checked(self.writer.witness_frontier()),
        )
    }
}

pub(super) fn append_decision(writer: &mut LedgerWriter, run: &StableId, episode: &StableId) {
    let candidates = vec![id("action"), id("abstain")];
    let request = ProductionDecisionV2 {
        record_id: run.clone(),
        episode_id: episode.clone(),
        run_snapshot_digest: d("snapshot"),
        objective_digest: d("objective"),
        policy_digest: d("policy"),
        candidate_ids: candidates.clone(),
        selected_candidate_id: id("action"),
        selected_propensity: ProbabilityQ32::ONE,
        completeness: CandidateSetCompletenessReceiptV1 {
            set_id: id("set"),
            state_digest: d("state"),
            generator_id: id("generator"),
            generator_code_digest: d("code"),
            grammar_digest: d("grammar"),
            hard_filter_digest: d("filter"),
            truncation_digest: d("truncation"),
            candidates_digest: candidate_ids_digest_v2(&candidates),
            candidate_count: 2,
            omitted_count_bound: 0,
            canonical_order_digest: candidate_order_digest_v2(&candidates),
            complete_for_generator: true,
        },
        support_digest: d("decision-support"),
    };
    let evidence = sign(
        writer,
        LearningEvidenceRoleV1::Generator,
        &checked(decision_signing_payload_v2(&request)),
    );
    checked(writer.append_decision(Digest32::ZERO, request, &evidence, /*now*/ 50));
}

pub(super) fn closure(
    writer: &LedgerWriter,
    run: &StableId,
    episode: &StableId,
    support: &CircuitCreditSupportV1,
) -> OutcomeCreditClosureRequestV2 {
    let outcome = AuthenticatedOutcomeV1 {
        record_id: id("outcome-record"),
        outcome_id: id("outcome"),
        episode_id: episode.clone(),
        observer: trusted(LearningEvidenceRoleV1::Observer).principal,
        observed_at: Some(40),
        value: Some(FixedQ32::ONE),
        unit_profile_digest: d("reward-unit"),
        support_digest: support.digest(),
        watermark: OutcomeWatermarkV1 {
            latest_observable_at: 45,
            expected_delay_profile_digest: d("delay"),
            terminality: OutcomeTerminalityV1::Terminal,
            censoring_reason: None,
            correction_predecessor: None,
            finalized_at: Some(46),
        },
    };
    let credit = CreditAllocationBatchV1 {
        batch_id: id("credit"),
        episode_id: episode.clone(),
        outcome_id: outcome.outcome_id.clone(),
        allocator: trusted(LearningEvidenceRoleV1::CreditAllocator).principal,
        terminal_outcome: FixedQ32::ONE,
        allocations: vec![CreditAllocationV1 {
            target_id: support.targets()[0].target_id.clone(),
            credit: FixedQ32::ONE,
        }],
        conservation_residual: FixedQ32::ZERO,
        support_digest: support.digest(),
        finalized: true,
    };
    let evidence = sign(
        writer,
        LearningEvidenceRoleV1::Observer,
        &outcome_signing_payload_v2(&outcome),
    );
    let finalized = checked(finalize_credit_batch(credit.clone(), /*now*/ 50));
    let credit_evidence = sign(
        writer,
        LearningEvidenceRoleV1::CreditAllocator,
        &credit_batch_signing_payload_v2(&credit, finalized.batch_digest),
    );
    OutcomeCreditClosureRequestV2 {
        outcome: ObservedOutcomeRequestV2 {
            run_id: run.clone(),
            expected_ledger_head: checked(writer.snapshot()).head_digest,
            outcome,
            evidence,
        },
        credit,
        credit_evidence,
    }
}
