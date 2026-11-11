//! Real native source/ledger I/O with explicitly synthetic keys and outcomes.

use std::fs::File;
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;

use codex_hepta_learning_ledger::*;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::*;
use crate::AgentdCircuitTaskInvocationProviderV1;
use crate::DurableCircuitTaskSourceV1;
use crate::circuit_cell::tests::support as cell;
use crate::circuit_task::original_source_test_support as original;

pub(crate) use cell::d;
pub(crate) use cell::id;
pub(crate) const Q: i64 = 1 << 24;
type Source = DurableCircuitTaskSourceV1<FileAnchorWitnessStore>;

pub(crate) struct Fixture {
    pub(crate) directory: tempfile::TempDir,
    pub(crate) identity: AgentdIdentity,
    pub(crate) source: Source,
    pub(crate) writer: LedgerWriter,
    pub(crate) profile: CellQ24DatasetProfileV1,
    pub(crate) calls: Arc<AtomicUsize>,
    pub(crate) at: u64,
    publication: CircuitTaskSourcePublicationV1,
}

pub(crate) fn signer(role: LearningEvidenceRoleV1, at: u64) -> TrustedLearningSignerV1 {
    let (name, seed) = key(role);
    let signing = SigningKey::from_bytes(&[seed; 32]);
    TrustedLearningSignerV1 {
        principal: AuthenticatedPrincipalV1 {
            principal_id: id(name),
            credential_chain_digest: d(&format!("{name}-chain")),
            signing_key_digest: Digest32::of_bytes(&signing.verifying_key().to_bytes()),
            scope_digest: d("scope"),
            authority_epoch: 1,
            authenticated_at: at - 10,
            expires_at: at + 3600,
        },
        controller_id: id(&format!("{name}-controller")),
        verifying_key: signing.verifying_key().to_bytes(),
        roles: vec![role],
        revoked_at: None,
    }
}
fn key(role: LearningEvidenceRoleV1) -> (&'static str, u8) {
    match role {
        LearningEvidenceRoleV1::Generator => ("generator", 1),
        LearningEvidenceRoleV1::Observer => ("observer", 2),
        LearningEvidenceRoleV1::Evaluator => ("evaluator", 3),
        _ => panic!("unsupported fixture role"),
    }
}
pub(crate) fn sign(
    writer: &LedgerWriter,
    role: LearningEvidenceRoleV1,
    at: u64,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let (name, seed) = key(role);
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(&format!("{name}:{}", Digest32::of_bytes(payload))),
        principal_id: id(name),
        role,
        trust_digest: writer.verifier().trust_digest(),
        scope_digest: d("scope"),
        objective_digest: writer.verifier().objective_digest(),
        authority_epoch: 1,
        issued_at: at - 1,
        expires_at: at + 600,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = SigningKey::from_bytes(&[seed; 32])
        .sign(&evidence.signing_bytes())
        .to_bytes();
    evidence
}
pub(crate) fn ledger(root: &Path, at: u64, objective: Digest32) -> anyhow::Result<LedgerWriter> {
    let key = SigningKey::from_bytes(&[99; 32]);
    let trust_root = LearningTrustRootV1 {
        root_id: id("root"),
        scope_digest: d("scope"),
        verifying_key: key.verifying_key().to_bytes(),
        valid_from: at - 10,
        expires_at: at + 3600,
        revoked_at: None,
    };
    let mut signed = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: id("q24-dataset-test-trust"),
            generation: 1,
            effective_at: at - 1,
            trust: LearningEvidenceTrustV1 {
                scope_digest: d("scope"),
                objective_digest: objective,
                authority_epoch: 1,
                signers: [
                    LearningEvidenceRoleV1::Generator,
                    LearningEvidenceRoleV1::Observer,
                    LearningEvidenceRoleV1::Evaluator,
                ]
                .into_iter()
                .map(|role| signer(role, at))
                .collect(),
            },
        },
        root_id: trust_root.root_id.clone(),
        issued_at: at - 1,
        expires_at: at + 600,
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()?).to_bytes();
    let trust = activate_learning_trust(&trust_root, signed, /*previous*/ None, at)?;
    let directory = File::open(root)?;
    Ok(LedgerWriter::from_durable(
        DurableLedger::create(original::opened(root, "ledger")?, d("q24-ledger"), 64)?,
        LedgerWitnessStore::create(original::opened(root, "ledger-witness")?, d("q24-ledger"))?,
        trust,
        &directory,
        &directory,
    )?)
}
impl Fixture {
    pub(crate) async fn new(second_input: i64) -> anyhow::Result<Self> {
        let directory = tempfile::tempdir()?;
        let root = directory.path();
        let at = now()?;
        let mut writer = ledger(root, at, d("objective"))?;
        let identity = original::identity(root)?;
        let run = circuit_learning_run_id_v1(&writer, &identity.agent_id, &id("train-A"))?;
        let input = cell::input(run.as_str());
        let mut observation = b"HQ24I001".to_vec();
        observation.extend_from_slice(&2_u16.to_le_bytes());
        for value in [Q, second_input] {
            observation.extend_from_slice(&value.to_le_bytes());
        }
        let source_input = original::source(run.as_str(), &observation);
        let fence = original::fence(&identity)?;
        let registry = original::registry()?;
        let source = Source::create(
            original::opened(root, "source-journal")?,
            original::witness(root, "source-witness")?,
            &identity,
            &fence,
            &registry,
            vec![source_input.clone()],
        )?;
        let request = source.build(&identity, &original::record(run.as_str()))?;
        let cells = original::cell_owner(root, std::slice::from_ref(&source_input))?;
        let (receipt, calls) = original::drive_dataset_fixture(
            &identity,
            source.clone(),
            &request,
            fence,
            registry,
            cells,
        )
        .await?;
        source.publish_result(&identity, &original::record(run.as_str()), &receipt)?;
        let publication = source.read_run_publication(&identity, &run)?;
        let candidates: Vec<_> = source_input
            .candidates
            .iter()
            .filter(|v| v.allowed)
            .map(|v| v.candidate_id.clone())
            .collect();
        let decision = ProductionDecisionV2 {
            record_id: run,
            episode_id: id("train-A"),
            run_snapshot_digest: d("original-signed-snapshot"),
            objective_digest: d("objective"),
            policy_digest: publication.bundle_digest(),
            candidate_ids: candidates.clone(),
            selected_candidate_id: id("a"),
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
                candidate_count: candidates.len() as u32,
                omitted_count_bound: 0,
                canonical_order_digest: candidate_order_digest_v2(&candidates),
                complete_for_generator: true,
            },
            support_digest: d("original-decision-support"),
        };
        let evidence = sign(
            &writer,
            LearningEvidenceRoleV1::Generator,
            at,
            &decision_signing_payload_v2(&decision)?,
        );
        writer.append_decision(Digest32::ZERO, decision, &evidence, at)?;
        let profile = CellQ24DatasetProfileV1 {
            principal_id: id("principal"),
            agent_id: identity.agent_id.clone(),
            cell_id: input.scope.cell_id,
            principal_digest: input.scope.principal_digest,
            ledger_binding: writer.binding_digest(),
            evidence_trust_digest: writer.verifier().trust_digest(),
            objective_digest: d("objective"),
            selected_bundle: publication.bundle_digest(),
            outcome_unit_profile: d("terminal-unit"),
            input_width: 2,
            training_episodes: vec![CellQ24DatasetEpisodeV1 {
                episode_id: id("train-A"),
                run_snapshot_digest: d("original-signed-snapshot"),
                decision_support_digest: d("original-decision-support"),
            }],
            excluded_episodes: vec![id("independent-B-unread")],
        };
        Ok(Self {
            directory,
            identity,
            source,
            writer,
            profile,
            calls,
            at,
            publication,
        })
    }

    pub(crate) fn append_outcome(
        &mut self,
        raw: Option<i64>,
        terminality: OutcomeTerminalityV1,
        correction: Option<StableId>,
        unit: Digest32,
        support: Digest32,
    ) -> anyhow::Result<()> {
        let outcome = AuthenticatedOutcomeV1 {
            record_id: id(if correction.is_some() {
                "corrected-outcome"
            } else {
                "outcome-record"
            }),
            outcome_id: id(if correction.is_some() {
                "corrected"
            } else {
                "outcome"
            }),
            episode_id: id("train-A"),
            observer: signer(LearningEvidenceRoleV1::Observer, self.at).principal,
            observed_at: raw.map(|_| self.at - 1),
            value: raw.map(FixedQ32::from_raw),
            unit_profile_digest: unit,
            support_digest: support,
            watermark: OutcomeWatermarkV1 {
                latest_observable_at: self.at,
                expected_delay_profile_digest: d("delay"),
                terminality,
                censoring_reason: (terminality == OutcomeTerminalityV1::Censored)
                    .then(|| id("censored")),
                correction_predecessor: correction,
                finalized_at: (terminality != OutcomeTerminalityV1::Pending).then_some(self.at),
            },
        };
        let evidence = sign(
            &self.writer,
            LearningEvidenceRoleV1::Observer,
            self.at,
            &outcome_signing_payload_v2(&outcome),
        );
        self.writer.append_outcome(
            self.writer.snapshot()?.head_digest,
            outcome,
            &evidence,
            self.at,
        )?;
        Ok(())
    }
    pub(crate) fn terminal(&mut self, raw: i64) -> anyhow::Result<()> {
        self.append_outcome(
            Some(raw),
            OutcomeTerminalityV1::Terminal,
            None,
            d("terminal-unit"),
            self.publication.publication_digest(),
        )
    }
    pub(crate) fn correct(&mut self, raw: i64) -> anyhow::Result<()> {
        self.append_outcome(
            Some(raw),
            OutcomeTerminalityV1::Terminal,
            Some(id("outcome")),
            d("terminal-unit"),
            self.publication.publication_digest(),
        )
    }
    pub(crate) fn freeze(&self) -> Result<OriginalCellQ24DatasetV1, anyhow::Error> {
        let plan = DatasetFreezePlanV2 {
            snapshot_id: id("original-q24-dataset"),
            objective_digest: d("objective"),
            inclusion_policy_digest: self.profile.digest()?,
        };
        let payload = dataset_freeze_signing_payload_v2(&self.writer.snapshot()?, &plan)?;
        let evidence = sign(
            &self.writer,
            LearningEvidenceRoleV1::Evaluator,
            self.at,
            &payload,
        );
        Ok(OriginalCellQ24DatasetV1::freeze(
            &self.writer,
            &self.source.readback(),
            &self.identity,
            self.profile.clone(),
            plan,
            evidence,
        )?)
    }
    pub(crate) fn bytes(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        [
            "ledger",
            "ledger-witness",
            "source-journal",
            "source-witness",
            "cell-journal",
            "cell-witness",
        ]
        .iter()
        .map(|name| Ok(std::fs::read(self.directory.path().join(name))?))
        .collect()
    }
}
