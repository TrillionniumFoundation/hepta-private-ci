//! Root-administered original files. Only the ordinary Root loader registers
//! them; this fixture opens no output owner and creates no completion receipt.
#![cfg(test)]

use std::path::Path;
use std::path::PathBuf;

use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use codex_hepta_neuron::CellGenerationConfigV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde::Serialize;

use super::super::post_a_plan::OriginalPostAPlan;
use super::super::post_a_plan::OriginalPostAResources;
use super::super::post_a_trust::B_EVALUATOR;
use super::super::post_a_trust::TRAINER;
use super::business;
use super::data::BaselineBytes;
use super::protocol::OriginalProtocol;
use crate::root_initial_learning_trust_data::LearningTrustPayloadV1;
use crate::root_initial_learning_trust_data::LearningTrustRoleSelectionV1;

const OUTPUTS: [&str; 19] = [
    "original-source.data",
    "original-candidate.data",
    "original-observer.statement",
    "original-policy.statement",
    "original-realized-plan.statement",
    "candidate.journal",
    "candidate.witness",
    "fixed-expert.journal",
    "fixed-expert.witness",
    "holdout",
    "executions",
    "execution-signature.journal",
    "execution-signature.witness",
    "qualification-signature.journal",
    "qualification-signature.witness",
    "publication.journal",
    "publication.witness",
    "receipt.journal",
    "receipt.witness",
];

pub(super) struct OriginalFiles {
    pub(super) directory: PathBuf,
    deployment: PathBuf,
    model: ModelData,
    fixed: CellData,
    original_inputs: Vec<PathBuf>,
}

impl OriginalFiles {
    pub(super) fn reserve(
        resources: &OriginalPostAResources,
        protocol: &OriginalProtocol,
        baseline: &BaselineBytes,
        input: &[u8],
        mut config: CellGenerationConfigV2,
        directory: PathBuf,
    ) -> anyhow::Result<Self> {
        let mut original_inputs = Vec::new();
        for name in OUTPUTS {
            business::write_once(&directory.join(name), &[])?;
        }
        let mut write = |name: &str, bytes: &[u8]| -> anyhow::Result<PathBuf> {
            let path = directory.join(name);
            business::write_once(&path, bytes)?;
            original_inputs.push(path.clone());
            Ok(path)
        };
        write("protocol.json", &protocol.bytes)?;
        write(
            "trust.json",
            &serde_json::to_vec(&TrustData {
                schema: 1,
                purpose: "runtime.learning.independent-b-trust.v1",
                original: &resources.trust.payload,
                evaluator: LearningTrustRoleSelectionV1 {
                    principal_id: B_EVALUATOR.into(),
                    controller_id: format!("{B_EVALUATOR}-controller"),
                },
            })?,
        )?;
        let now = business::now()?;
        let (trust, generator, _) = resources.trust.payload.activate_pinned_genesis(now)?;
        let key = SigningKey::from_bytes(
            &std::fs::read(resources.trust.key(TRAINER)?)?
                .try_into()
                .map_err(|_| anyhow::anyhow!("original Generator key length"))?,
        );
        anyhow::ensure!(
            key.verifying_key().to_bytes() == generator.verifying_key,
            "original fixed protocol Generator key"
        );
        let mut signed = SignedLearningEvidenceV1 {
            evidence_id: StableId::new("ordinary-independent-b-original-protocol")?,
            principal_id: generator.principal.principal_id.clone(),
            role: LearningEvidenceRoleV1::Generator,
            trust_digest: trust.verifier().trust_digest(),
            scope_digest: trust.verifier().scope_digest(),
            objective_digest: trust.verifier().objective_digest(),
            authority_epoch: generator.principal.authority_epoch,
            issued_at: now,
            expires_at: now
                .checked_add(240)
                .ok_or_else(|| anyhow::anyhow!("protocol expiry overflow"))?
                .min(generator.principal.expires_at),
            payload_digest: Digest32::of_bytes(protocol.digest.as_array()),
            signature: [0; 64],
        };
        signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
        trust.verifier().verify(
            LearningEvidenceRoleV1::Generator,
            &signed,
            protocol.digest.as_array(),
            now,
        )?;
        write(
            "protocol.statement",
            &crate::learning_owner_evidence::encode(protocol.digest.as_array(), &signed)?,
        )?;
        let model = ModelData {
            base: write("base", &baseline.base)?,
            organ_adapter: None,
            cell_adapter: None,
            encoder: write("encoder", &baseline.encoder)?,
            heads: write("heads", &baseline.heads)?,
            benchmark_input: write("benchmark.input", input)?,
            updated_head: HeadData::Drive { index: 0 },
        };
        config.initial.scope.run_id = "ordinary-independent-b-native-benchmark".into();
        config.task_digest = Digest32::of_parts(&[
            b"hepta.root.b.benchmark-task.v1\0",
            protocol.digest.as_array(),
            Digest32::of_bytes(input).as_array(),
        ])
        .into_array();
        // A fresh unpublished B component declares sufficient journal capacity
        // before registration. No existing A, frame or service bound changes.
        config.manifest.max_step_cost_entries = 32;
        config.manifest.max_ack_cost_entries = 16;
        config.initial.manifest_digest = config.manifest.digest()?;
        let journal_records = 128;
        let binding =
            codex_hepta_neuron::CellGenerationOwnerBindingV1::new(&config, journal_records)?;
        let fixed = CellData {
            journal: directory.join("fixed-expert.journal"),
            witness: directory.join("fixed-expert.witness"),
            witness_scope: binding.digest()?,
            witness_objective: config.task_digest,
            original: config,
            journal_records,
            witness_generation: 1,
            witness_records: 128,
        };
        Ok(Self {
            deployment: resources
                .original
                .plan
                .protected
                .path()
                .join("post-a-independent-b.json"),
            directory,
            model,
            fixed,
            original_inputs,
        })
    }

    pub(super) fn write_deployment(
        &self,
        plan: &OriginalPostAPlan,
        source_peer: CognitiveCheckpointPeerLifetime,
    ) -> anyhow::Result<PathBuf> {
        anyhow::ensure!(
            source_peer.uid == 60002
                && source_peer.pid != 0
                && source_peer.process_start_ticks != 0
                && !source_peer.boot_id.is_empty(),
            "actual original independent Source lifetime required"
        );
        anyhow::ensure!(
            plan.root.independent_b == self.deployment
                && plan.root.independent_b
                    == plan
                        .resources
                        .original
                        .plan
                        .protected
                        .path()
                        .join("post-a-independent-b.json"),
            "original Root independent B deployment path differs"
        );
        for name in OUTPUTS {
            anyhow::ensure!(
                std::fs::metadata(self.directory.join(name))?.len() == 0,
                "B outputs must all be empty before first Root registration"
            );
        }
        let journal = |name: &str| JournalData {
            journal: self.directory.join(format!("{name}.journal")),
            witness: self.directory.join(format!("{name}.witness")),
        };
        let data = DeploymentData {
            schema: 1,
            purpose: "runtime.learning.independent-b-deployment.v1",
            protocol: self.directory.join("protocol.json"),
            trust: self.directory.join("trust.json"),
            protocol_statement: self.directory.join("protocol.statement"),
            source: self.directory.join("original-source.data"),
            source_peer,
            candidate_data: self.directory.join("original-candidate.data"),
            observed_statement: self.directory.join("original-observer.statement"),
            policy_statement: self.directory.join("original-policy.statement"),
            realized_plan_statement: self.directory.join("original-realized-plan.statement"),
            evaluator_key: plan.resources.trust.key(B_EVALUATOR)?.to_owned(),
            candidate: journal("candidate"),
            model: &self.model,
            fixed_expert: &self.fixed,
            holdout: self.directory.join("holdout"),
            executions: self.directory.join("executions"),
            execution_signature: journal("execution-signature"),
            qualification_signature: journal("qualification-signature"),
            publication: journal("publication"),
            receipt: journal("receipt"),
            maximum_signature_lifetime_seconds: 240,
        };
        business::write_once(&plan.root.independent_b, &serde_json::to_vec(&data)?)?;
        Ok(plan.root.independent_b.clone())
    }

    pub(super) fn business_files(&self) -> Vec<PathBuf> {
        let mut paths = self.original_inputs.clone();
        paths.push(self.deployment.clone());
        paths.extend(OUTPUTS.map(|name| self.directory.join(name)));
        paths.extend(
            [
                "original-fixed-control.data",
                "original-preregistered-protocol.json",
                "original-retained-training.data",
                "original-retention-observation.data",
                "original-removal-observation.data",
                "ordinary-b-calibration-fold.forecast",
                "ordinary-b-final-fold.forecast",
            ]
            .map(|name| self.directory.join(name)),
        );
        paths
    }
}

#[derive(Serialize)]
struct TrustData<'a> {
    schema: u8,
    purpose: &'static str,
    original: &'a LearningTrustPayloadV1,
    evaluator: LearningTrustRoleSelectionV1,
}
#[derive(Serialize)]
struct JournalData {
    journal: PathBuf,
    witness: PathBuf,
}
#[derive(Serialize)]
struct CellData {
    journal: PathBuf,
    witness: PathBuf,
    original: CellGenerationConfigV2,
    journal_records: u64,
    witness_scope: [u8; 32],
    witness_objective: [u8; 32],
    witness_generation: u64,
    witness_records: usize,
}
#[derive(Serialize)]
struct ModelData {
    base: PathBuf,
    organ_adapter: Option<PathBuf>,
    cell_adapter: Option<PathBuf>,
    encoder: PathBuf,
    heads: PathBuf,
    benchmark_input: PathBuf,
    updated_head: HeadData,
}
#[derive(Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum HeadData {
    Drive { index: u16 },
}
#[derive(Serialize)]
struct DeploymentData<'a> {
    schema: u8,
    purpose: &'static str,
    protocol: PathBuf,
    trust: PathBuf,
    protocol_statement: PathBuf,
    source: PathBuf,
    source_peer: CognitiveCheckpointPeerLifetime,
    candidate_data: PathBuf,
    observed_statement: PathBuf,
    policy_statement: PathBuf,
    realized_plan_statement: PathBuf,
    evaluator_key: PathBuf,
    candidate: JournalData,
    model: &'a ModelData,
    fixed_expert: &'a CellData,
    holdout: PathBuf,
    executions: PathBuf,
    execution_signature: JournalData,
    qualification_signature: JournalData,
    publication: JournalData,
    receipt: JournalData,
    maximum_signature_lifetime_seconds: u64,
}

pub(super) fn read_original_key(path: &Path) -> anyhow::Result<[u8; 32]> {
    super::super::observer::read_private(path, 32)?
        .try_into()
        .map_err(|_| anyhow::anyhow!("original fixed key length"))
}
