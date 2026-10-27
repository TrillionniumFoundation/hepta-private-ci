//! Real durable ledger/witness with explicit, separate test signing principals.

use std::fs::File;
use std::fs::OpenOptions;

use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::AuthenticatedOutcomeV1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningTrustDistributionV1;
use codex_hepta_learning_ledger::LearningTrustRootV1;
use codex_hepta_learning_ledger::LedgerRecovery;
use codex_hepta_learning_ledger::LedgerWitnessStore;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::OutcomeTerminalityV1;
use codex_hepta_learning_ledger::OutcomeWatermarkV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::SignedLearningTrustDistributionV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_learning_ledger::activate_learning_trust;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::MemoryCellLearningDecisionV1;
use super::MemoryCellLearningSinkV1;
use super::MemoryCellTrainingDecisionContextV1;

pub(crate) fn digest(label: &str) -> Digest32 { Digest32::of_bytes(label.as_bytes()) }
pub(crate) fn id(label: &str) -> StableId { StableId::new(label).unwrap() }

pub(crate) struct LedgerFixture {
    root: tempfile::TempDir,
    pub sink: MemoryCellLearningSinkV1,
    trust_digest: Digest32,
}

impl LedgerFixture {
    pub(crate) fn new() -> Self {
        let root = tempfile::tempdir().unwrap();
        let file = |name| OpenOptions::new().create_new(true).read(true).write(true).open(root.path().join(name)).unwrap();
        let ledger = DurableLedger::create(file("ledger"), digest("memory-training-ledger"), /*max_records*/ 64).unwrap();
        let witness = LedgerWitnessStore::create(file("witness"), digest("memory-training-ledger")).unwrap();
        let writer = LedgerWriter::from_durable(ledger, witness, activated(), &directory(root.path()), &directory(root.path())).unwrap();
        let trust_digest = writer.verifier().trust_digest();
        Self { root, sink: MemoryCellLearningSinkV1::new(writer), trust_digest }
    }

    pub(crate) fn context(&self, label: &str) -> MemoryCellTrainingDecisionContextV1 {
        MemoryCellTrainingDecisionContextV1 { record_id: id(&format!("memory-training-record:{label}")),
            episode_id: id(&format!("memory-training-episode:{label}")), objective_digest: digest("memory-objective"), generator_id: id("generator") }
    }

    pub(crate) fn sign(&self, principal: &str, role: LearningEvidenceRoleV1, payload: &[u8]) -> SignedLearningEvidenceV1 {
        let mut signed = SignedLearningEvidenceV1 {
            evidence_id: id(&format!("memory-evidence:{principal}:{}", Digest32::of_bytes(payload))),
            principal_id: id(principal), role, trust_digest: self.trust_digest,
            scope_digest: digest("memory-learning-scope"), objective_digest: digest("memory-objective"), authority_epoch: 1,
            issued_at: 20, expires_at: 90, payload_digest: Digest32::of_bytes(payload), signature: [0; 64],
        };
        signed.signature = key(principal).sign(&signed.signing_bytes()).to_bytes();
        signed
    }

    pub(crate) fn outcome(&self, prepared: &MemoryCellLearningDecisionV1, principal: &str, observation: Digest32) -> AuthenticatedOutcomeV1 {
        AuthenticatedOutcomeV1 {
            record_id: id("memory-observed-record"), outcome_id: id("memory-observed-outcome"),
            episode_id: prepared.decision().episode_id.clone(), observer: trusted(principal).principal,
            observed_at: Some(40), value: Some(FixedQ32::from_raw(1_i64 << 32)),
            unit_profile_digest: digest("independent-test-observation-units"), support_digest: prepared.outcome_support_digest(observation).unwrap(),
            watermark: OutcomeWatermarkV1 { latest_observable_at: 45, expected_delay_profile_digest: digest("observer-delay"),
                terminality: OutcomeTerminalityV1::Terminal, censoring_reason: None, correction_predecessor: None, finalized_at: Some(46) },
        }
    }

    pub(crate) fn reopen(self) -> Self {
        let expected = self.sink.witness_frontier().unwrap();
        let Self { root, sink, trust_digest } = self;
        drop(sink);
        let file = |name| OpenOptions::new().read(true).write(true).open(root.path().join(name)).unwrap();
        let witness = LedgerWitnessStore::recover(file("witness"), digest("memory-training-ledger")).unwrap();
        assert_eq!(witness.frontier().unwrap(), expected);
        let ledger = DurableLedger::recover(file("ledger"), digest("memory-training-ledger"), /*max_records*/ 64, LedgerRecovery::Acknowledged(expected.anchor)).unwrap();
        let writer = LedgerWriter::from_durable(ledger, witness, activated(), &directory(root.path()), &directory(root.path())).unwrap();
        Self { root, sink: MemoryCellLearningSinkV1::new(writer), trust_digest }
    }
}

fn directory(path: &std::path::Path) -> File {
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        OpenOptions::new().read(true).write(true).custom_flags(0x0200_0000).open(path).unwrap()
    }
    #[cfg(not(windows))]
    File::open(path).unwrap()
}

fn key(name: &str) -> SigningKey {
    SigningKey::from_bytes(&[match name { "generator" => 51, "observer" => 52, "same-controller" => 53, _ => panic!("unknown test principal") }; 32])
}

fn trusted(name: &str) -> TrustedLearningSignerV1 {
    let key = key(name);
    TrustedLearningSignerV1 {
        principal: AuthenticatedPrincipalV1 { principal_id: id(name), credential_chain_digest: digest(&format!("{name}:credential")),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()), scope_digest: digest("memory-learning-scope"),
            authority_epoch: 1, authenticated_at: 10, expires_at: 100 },
        controller_id: id(if name == "observer" { "independent-observer-controller" } else { "training-controller" }),
        verifying_key: key.verifying_key().to_bytes(),
        // Even a dual-role credential must not observe its own generated fit.
        roles: if name == "generator" { vec![LearningEvidenceRoleV1::Generator, LearningEvidenceRoleV1::Observer] } else { vec![LearningEvidenceRoleV1::Observer] },
        revoked_at: None,
    }
}

fn activated() -> ActivatedLearningTrustV1 {
    let key = SigningKey::from_bytes(&[71; 32]);
    let root = LearningTrustRootV1 { root_id: id("memory-learning-root"), scope_digest: digest("memory-learning-scope"),
        verifying_key: key.verifying_key().to_bytes(), valid_from: 1, expires_at: 200, revoked_at: None };
    let mut signed = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 { distribution_id: id("memory-learning-trust"), generation: 1, effective_at: 20,
            trust: LearningEvidenceTrustV1 { scope_digest: digest("memory-learning-scope"), objective_digest: digest("memory-objective"), authority_epoch: 1,
                signers: vec![trusted("generator"), trusted("observer"), trusted("same-controller")] } },
        root_id: root.root_id.clone(), issued_at: 15, expires_at: 90, signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes().unwrap()).to_bytes();
    activate_learning_trust(&root, signed, /*previous*/ None, /*now*/ 50).unwrap()
}
