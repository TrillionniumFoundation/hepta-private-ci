//! Actual journal/Fleet/ledger owners with a bounded file-backed test worker.
//! Deterministic keys and quality values are fixtures, never adoption evidence.

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_intelligence::FrozenGenerationEpisodeInputV1;
use codex_hepta_intelligence::FrozenGenerationEpisodeV1;
use codex_hepta_intelligence::ObservedOutcomeRequestV2;
use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::AppendReceipt;
use codex_hepta_learning_ledger::AuthenticatedOutcomeV1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;
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
use codex_hepta_learning_ledger::ProductionDecisionV2;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::SignedLearningTrustDistributionV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_learning_ledger::activate_learning_trust;
use codex_hepta_learning_ledger::candidate_ids_digest_v2;
use codex_hepta_learning_ledger::candidate_order_digest_v2;
use codex_hepta_learning_ledger::decision_signing_payload_v2;
use codex_hepta_learning_ledger::outcome_signing_payload_v2;
use codex_hepta_neuron::CellBackendManifestV2;
use codex_hepta_neuron::CellCostAccountingV2;
use codex_hepta_neuron::CellCostEntryV2;
use codex_hepta_neuron::CellCostMetricsV2;
use codex_hepta_neuron::CellCostOutcomeV2;
use codex_hepta_neuron::CellCostStageV2;
use codex_hepta_neuron::CellGenerationControlPortV2;
use codex_hepta_neuron::CellGenerationDispositionV2;
use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_neuron::CellGenerationObservationV1;
use codex_hepta_neuron::CellGenerationProposalV2;
use codex_hepta_neuron::CellGenerationRequestV2;
use codex_hepta_neuron::CellTaskCostIdentityV2;
use codex_hepta_neuron::CellTaskCostV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::host;
use host::checked;

pub(super) fn id(value: &str) -> StableId {
    checked(StableId::new(value))
}

pub(super) fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

pub(super) fn freeze(fixture: &mut host::Fixture) -> FrozenGenerationEpisodeV1 {
    let frozen = checked(FrozenGenerationEpisodeV1::new(
        FrozenGenerationEpisodeInputV1 {
            episode_id: id("actor-episode"),
            run_id: id(&fixture.config.initial.scope.run_id),
            decision_id: id("actor-decision"),
            objective_digest: digest("objective"),
            policy_digest: digest("policy"),
            evaluation_profile_digest: digest("quality-unit"),
            sampler_digest: digest("sampler"),
            source_frontier: Digest32::from_array(fixture.config.source_frontier),
            initial: fixture.config.initial.clone(),
        },
    ));
    fixture.config.task_digest = frozen.task_digest().into_array();
    frozen
}

pub(super) fn request(fixture: &host::Fixture) -> CellGenerationRequestV2 {
    CellGenerationRequestV2 {
        operation_id: "episode-stop".into(),
        task_digest: fixture.config.task_digest,
        source_frontier: fixture.config.source_frontier,
        predecessor: fixture.config.initial.clone(),
        input: b"bounded fixture task".to_vec(),
        admitted_at_micros: 10,
        deadline_micros: 10_000,
    }
}

#[derive(Clone)]
pub(super) struct TerminalControl {
    path: PathBuf,
    pub calls: Arc<AtomicUsize>,
}

impl TerminalControl {
    pub(super) fn new(root: &Path) -> Self {
        Self {
            path: root.join("terminal-control-result"),
            calls: Arc::new(AtomicUsize::new(0)),
        }
    }
}

impl CellGenerationControlPortV2 for TerminalControl {
    fn execute_generation(
        &mut self,
        manifest: &CellBackendManifestV2,
        request: &CellGenerationRequestV2,
    ) -> Result<CellGenerationProposalV2, CellGenerationErrorV2> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        let identity = CellTaskCostIdentityV2 {
            task_digest: request.task_digest,
            source_digest: manifest.source_digest,
        };
        let mut cost = checked(CellTaskCostV2::new(identity));
        checked(cost.record(CellCostEntryV2 {
            event_id: request.digest()?,
            identity,
            stage: CellCostStageV2::Inference,
            outcome: CellCostOutcomeV2::Succeeded,
            accounting: CellCostAccountingV2::Exclusive,
            metrics: CellCostMetricsV2 {
                wall_micros: Some(9),
                cpu_micros: Some(7),
                ..CellCostMetricsV2::default()
            },
        }));
        let proposal = CellGenerationProposalV2 {
            request_digest: request.digest()?,
            bundle_digest: manifest.bundle_digest,
            runtime_digest: manifest.runtime_digest,
            device_digest: manifest.device_digest,
            successor_state: b"settled".to_vec(),
            output_delta: b"episode output".to_vec(),
            disposition: CellGenerationDispositionV2::Stopped,
            cost,
        };
        let mut file = checked(
            OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&self.path),
        );
        checked(file.write_all(&checked(serde_json::to_vec(&proposal))));
        checked(file.sync_all());
        Ok(proposal)
    }

    fn read_generation(
        &mut self,
        request: &CellGenerationRequestV2,
    ) -> Result<Option<CellGenerationProposalV2>, CellGenerationErrorV2> {
        let bytes = match fs::read(&self.path) {
            Ok(bytes) => bytes,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(_) => return Err(CellGenerationErrorV2::Unavailable),
        };
        let proposal: CellGenerationProposalV2 = checked(serde_json::from_slice(&bytes));
        if proposal.request_digest != request.digest()? {
            return Err(CellGenerationErrorV2::Conflict);
        }
        Ok(Some(proposal))
    }

    fn cancel_generation(
        &mut self,
        _request: &CellGenerationRequestV2,
    ) -> Result<(), CellGenerationErrorV2> {
        Ok(())
    }
}

fn trusted(name: &str, seed: u8, role: LearningEvidenceRoleV1) -> TrustedLearningSignerV1 {
    let key = SigningKey::from_bytes(&[seed; 32]);
    TrustedLearningSignerV1 {
        principal: AuthenticatedPrincipalV1 {
            principal_id: id(name),
            credential_chain_digest: digest(&format!("{name}-credential")),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            scope_digest: digest("scope"),
            authority_epoch: 7,
            authenticated_at: 10,
            expires_at: 100,
        },
        controller_id: id(&format!("{name}-controller")),
        verifying_key: key.verifying_key().to_bytes(),
        roles: vec![role],
        revoked_at: None,
    }
}

fn activated_trust() -> ActivatedLearningTrustV1 {
    let key = SigningKey::from_bytes(&[99; 32]);
    let root = LearningTrustRootV1 {
        root_id: id("learning-root"),
        scope_digest: digest("scope"),
        verifying_key: key.verifying_key().to_bytes(),
        valid_from: 1,
        expires_at: 200,
        revoked_at: None,
    };
    let mut signed = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: id("episode-trust"),
            generation: 1,
            effective_at: 20,
            trust: LearningEvidenceTrustV1 {
                scope_digest: digest("scope"),
                objective_digest: digest("objective"),
                authority_epoch: 7,
                signers: vec![
                    trusted("generator", 1, LearningEvidenceRoleV1::Generator),
                    trusted("observer", 2, LearningEvidenceRoleV1::Observer),
                ],
            },
        },
        root_id: root.root_id.clone(),
        issued_at: 15,
        expires_at: 90,
        signature: [0; 64],
    };
    signed.signature = key.sign(&checked(signed.signing_bytes())).to_bytes();
    checked(activate_learning_trust(&root, signed, None, 50))
}

fn sign(
    writer: &LedgerWriter,
    name: &str,
    role: LearningEvidenceRoleV1,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let seed = match name {
        "generator" => 1,
        "observer" => 2,
        _ => panic!("fixture signer"),
    };
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(&format!("evidence-{name}-{}", Digest32::of_bytes(payload))),
        principal_id: id(name),
        role,
        trust_digest: writer.verifier().trust_digest(),
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        authority_epoch: 7,
        issued_at: 20,
        expires_at: 90,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = SigningKey::from_bytes(&[seed; 32])
        .sign(&evidence.signing_bytes())
        .to_bytes();
    evidence
}

pub(super) struct LedgerFixture {
    directory: tempfile::TempDir,
}

impl LedgerFixture {
    pub(super) fn new() -> Self {
        let directory = checked(tempfile::tempdir());
        for name in ["ledger", "witness"] {
            checked(
                OpenOptions::new()
                    .write(true)
                    .create_new(true)
                    .open(directory.path().join(name)),
            );
        }
        Self { directory }
    }

    fn file(&self, name: &str) -> File {
        checked(
            OpenOptions::new()
                .read(true)
                .write(true)
                .open(self.directory.path().join(name)),
        )
    }

    fn directory(&self) -> File {
        #[cfg(windows)]
        {
            use std::os::windows::fs::OpenOptionsExt;
            checked(
                OpenOptions::new()
                    .read(true)
                    .write(true)
                    .custom_flags(0x0200_0000 | 0x0020_0000)
                    .open(self.directory.path()),
            )
        }
        #[cfg(not(windows))]
        {
            checked(File::open(self.directory.path()))
        }
    }

    pub(super) fn writer(&self, reopen: bool) -> LedgerWriter {
        let binding = digest("episode-ledger-binding");
        let (ledger, witness) = if reopen {
            let witness = checked(LedgerWitnessStore::recover(self.file("witness"), binding));
            let anchor = checked(witness.frontier()).anchor;
            (
                checked(DurableLedger::recover(
                    self.file("ledger"),
                    binding,
                    32,
                    LedgerRecovery::Acknowledged(anchor),
                )),
                witness,
            )
        } else {
            (
                checked(DurableLedger::create(self.file("ledger"), binding, 32)),
                checked(LedgerWitnessStore::create(self.file("witness"), binding)),
            )
        };
        checked(LedgerWriter::from_durable(
            ledger,
            witness,
            activated_trust(),
            &self.directory(),
            &self.directory(),
        ))
    }

    pub(super) fn bytes(&self) -> [Vec<u8>; 2] {
        [
            checked(fs::read(self.directory.path().join("ledger"))),
            checked(fs::read(self.directory.path().join("witness"))),
        ]
    }
}

pub(super) fn append_decision(
    writer: &mut LedgerWriter,
    frozen: &FrozenGenerationEpisodeV1,
) -> AppendReceipt {
    let candidates = vec![id("action"), id("abstain")];
    let request = ProductionDecisionV2 {
        record_id: frozen.input().decision_id.clone(),
        episode_id: frozen.input().episode_id.clone(),
        run_snapshot_digest: frozen.contract_digest(),
        objective_digest: frozen.input().objective_digest,
        policy_digest: frozen.input().policy_digest,
        candidate_ids: candidates.clone(),
        selected_candidate_id: id("action"),
        selected_propensity: ProbabilityQ32::ONE,
        completeness: CandidateSetCompletenessReceiptV1 {
            set_id: id("candidate-set"),
            state_digest: digest("state"),
            generator_id: id("generator"),
            generator_code_digest: digest("generator-code"),
            grammar_digest: digest("grammar"),
            hard_filter_digest: digest("hard-filter"),
            truncation_digest: digest("truncation"),
            candidates_digest: candidate_ids_digest_v2(&candidates),
            candidate_count: 2,
            omitted_count_bound: 0,
            canonical_order_digest: candidate_order_digest_v2(&candidates),
            complete_for_generator: true,
        },
        support_digest: frozen.decision_support_digest(),
    };
    let evidence = sign(
        writer,
        "generator",
        LearningEvidenceRoleV1::Generator,
        &checked(decision_signing_payload_v2(&request)),
    );
    checked(writer.append_decision(Digest32::ZERO, request, &evidence, 50))
}

pub(super) fn signed_request(
    writer: &LedgerWriter,
    frozen: &FrozenGenerationEpisodeV1,
    observation: Option<&CellGenerationObservationV1>,
    expected: Digest32,
) -> ObservedOutcomeRequestV2 {
    let support_digest = observation.map_or_else(
        || digest("not-terminal"),
        |value| checked(frozen.outcome_evidence(value)).support_digest(),
    );
    let outcome = AuthenticatedOutcomeV1 {
        record_id: id("observed-episode"),
        outcome_id: id("episode-quality"),
        episode_id: frozen.input().episode_id.clone(),
        observer: trusted("observer", 2, LearningEvidenceRoleV1::Observer).principal,
        observed_at: Some(40),
        value: Some(FixedQ32::from_raw(100)),
        unit_profile_digest: frozen.input().evaluation_profile_digest,
        support_digest,
        watermark: OutcomeWatermarkV1 {
            latest_observable_at: 45,
            expected_delay_profile_digest: digest("delay"),
            terminality: OutcomeTerminalityV1::Terminal,
            censoring_reason: None,
            correction_predecessor: None,
            finalized_at: Some(46),
        },
    };
    let evidence = sign(
        writer,
        "observer",
        LearningEvidenceRoleV1::Observer,
        &outcome_signing_payload_v2(&outcome),
    );
    ObservedOutcomeRequestV2 {
        run_id: frozen.input().decision_id.clone(),
        expected_ledger_head: expected,
        outcome,
        evidence,
    }
}
