//! Administrator DATA observation of the actual Root B publication files.
//! B keeps its exclusive writers. This observer uses separate O_RDONLY file
//! descriptions, stable pread images and the original codecs; it takes no lock,
//! repairs nothing and cannot construct a B or Artifact authority.

use std::fs::File;
use std::fs::OpenOptions;
use std::os::unix::fs::FileExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;

use codex_hepta_intelligence_eval::ProductEvaluationExecutionAnchorV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStateV1;
use codex_hepta_intelligence_eval::decode_original_product_evaluation_execution_image_v1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::observe_original_file_anchor_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::post_a_file::OriginalFileData;
use super::post_a_plan::OriginalPostAPlan;
use crate::OriginalRootBPublicationDataV2;
use crate::cell_q24_publication_driver::validation::Decision;

struct OriginalReadFile {
    file: File,
    pin: OriginalFileData,
}

#[derive(Eq, PartialEq)]
struct OriginalImage {
    bytes: Vec<u8>,
    stamp: (u64, i64, i64, i64, i64),
}

pub(super) struct OriginalBPublicationObserver {
    journal: OriginalReadFile,
    witness: OriginalReadFile,
    plan_id: StableId,
    initial: Digest32,
    objective: Digest32,
    trust: Digest32,
    generation: Generation,
    observed: Option<(Digest32, Digest32)>,
    refused: bool,
}

impl OriginalBPublicationObserver {
    /// Called after the original deployment is written and before Root exec.
    /// Both original output files must still be empty at this point.
    pub(super) fn capture_original_reservation(plan: &OriginalPostAPlan) -> anyhow::Result<Self> {
        let deployment: serde_json::Value = serde_json::from_slice(
            &super::observer::read_private(&plan.root.independent_b, 65_536)?,
        )?;
        anyhow::ensure!(
            deployment["schema"] == 1
                && deployment["purpose"] == "runtime.learning.independent-b-deployment.v1",
            "original B deployment data differs"
        );
        let original_path = |value: &serde_json::Value| -> anyhow::Result<std::path::PathBuf> {
            Ok(value
                .as_str()
                .ok_or_else(|| anyhow::anyhow!("original B file path absent"))?
                .into())
        };
        let initial = plan.profile.original_initial_data()?;
        let protocol =
            super::observer::read_private(&original_path(&deployment["protocol"])?, 65_536)?;
        anyhow::ensure!(
            Digest32::of_parts(&[b"hepta.root.independent-b.protocol.v1\0", &protocol])
                == initial.request.evaluation_profile,
            "original B protocol bytes changed"
        );
        let protocol: serde_json::Value = serde_json::from_slice(&protocol)?;
        let plan_id = StableId::new(
            protocol["plan_id"]
                .as_str()
                .ok_or_else(|| anyhow::anyhow!("original B plan id absent"))?,
        )?;
        let evaluator = plan
            .resources
            .trust
            .payload
            .distribution
            .signers
            .iter()
            .find(|value| value.principal_id == initial.owners.evaluator.as_str())
            .ok_or_else(|| anyhow::anyhow!("original B Evaluator registration absent"))?;
        let journal = OriginalReadFile::capture_empty(&original_path(
            &deployment["publication"]["journal"],
        )?)?;
        let witness = OriginalReadFile::capture_empty(&original_path(
            &deployment["publication"]["witness"],
        )?)?;
        let left = journal.file.metadata()?;
        let right = witness.file.metadata()?;
        anyhow::ensure!(
            (left.dev(), left.ino()) != (right.dev(), right.ino()),
            "original B publication and witness alias"
        );
        Ok(Self {
            journal,
            witness,
            plan_id,
            initial: initial.head_digest,
            objective: initial.request.envelope.objective_digest,
            trust: initial.owners.evidence_trust_digest,
            generation: Generation::new(evaluator.authority_epoch)?,
            observed: None,
            refused: false,
        })
    }

    pub(super) fn read_original_after_decision(
        &mut self,
        plan: &OriginalPostAPlan,
        decision: &Decision,
    ) -> anyhow::Result<OriginalRootBPublicationDataV2> {
        anyhow::ensure!(!self.refused, "original B data observer is refused");
        self.refused = true;
        let initial = plan.profile.original_initial_data()?;
        anyhow::ensure!(
            std::time::Instant::now() < plan.resources.end
                && initial.head_digest == self.initial
                && decision.snapshot.request == initial.request
                && decision.snapshot.owners == initial.owners
                && decision.snapshot.receipts.iter().any(|receipt| matches!(
                    receipt.observation,
                    LearningIterationObservationV1::Evaluation { .. }
                )),
            "actual original post-B decision data required"
        );
        let trained = decision
            .snapshot
            .receipts
            .iter()
            .find_map(|receipt| {
                if let LearningIterationObservationV1::Training { candidate, .. } =
                    &receipt.observation
                {
                    Some(candidate.as_ref())
                } else {
                    None
                }
            })
            .ok_or_else(|| {
                anyhow::anyhow!("actual trained candidate required; TrainingNoUpdate is not B")
            })?;
        let journal = self.journal.image()?;
        let witness = self.witness.image()?;
        anyhow::ensure!(
            journal.bytes.len() >= 72 && &journal.bytes[..8] == b"HEPTEX01",
            "original journal header"
        );
        // Reading this binding identifies DATA only. Authenticity still comes
        // from the actual Root-held, pre-pinned files and product B readback.
        let binding = Digest32::from_array(journal.bytes[8..40].try_into()?);
        let scope = JournalScope {
            scope_digest: binding,
            objective_digest: self.objective,
        };
        let anchor =
            observe_original_file_anchor_v1(&self.witness.file, scope, self.generation, 128)?
                .ok_or_else(|| anyhow::anyhow!("original B publication witness absent"))?;
        anyhow::ensure!(
            anchor.sequence == 3,
            "exact one original publication completion required"
        );
        let state = decode_original_product_evaluation_execution_image_v1(
            &journal.bytes,
            binding,
            ProductEvaluationExecutionAnchorV1 {
                sequence: anchor.sequence - 1,
                history_digest: anchor.checkpoint_digest,
            },
            &ProductEvaluationExecutionKeyV1 {
                plan_id: self.plan_id.clone(),
                binding_digest: binding,
            },
        )?;
        let ProductEvaluationExecutionStateV1::Completed(bytes) = state else {
            anyhow::bail!("original B publication is pending");
        };
        let data = OriginalRootBPublicationDataV2::decode(&bytes)?;
        anyhow::ensure!(
            data.trust_digest() == self.trust,
            "original B publication trust differs"
        );
        crate::cell_composed_q24::validate_manifest(trained, data.manifest())?;
        anyhow::ensure!(
            self.journal.image()? == journal
                && self.witness.image()? == witness
                && observe_original_file_anchor_v1(
                    &self.witness.file,
                    scope,
                    self.generation,
                    128
                )? == Some(anchor)
                && std::time::Instant::now() < plan.resources.end,
            "original B publication changed during physical data read"
        );
        let observed = (
            Digest32::of_bytes(&journal.bytes),
            Digest32::of_bytes(&witness.bytes),
        );
        anyhow::ensure!(
            self.observed.is_none_or(|old| old == observed),
            "original B data cut changed"
        );
        self.observed = Some(observed);
        self.refused = false;
        Ok(data)
    }
}

impl OriginalReadFile {
    fn capture_empty(path: &Path) -> anyhow::Result<Self> {
        let pin = OriginalFileData::capture(path)?;
        let file = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
            .open(path)?;
        pin.require_file(&file)?;
        let metadata = file.metadata()?;
        anyhow::ensure!(
            metadata.uid() == 0 && metadata.gid() == 0 && metadata.len() == 0,
            "original empty Root B output reservation required"
        );
        Ok(Self { file, pin })
    }

    fn image(&self) -> anyhow::Result<OriginalImage> {
        self.pin.require_file(&self.file)?;
        let before = self.file.metadata()?;
        anyhow::ensure!(
            (1..=131_072).contains(&before.len()),
            "original B output image bound"
        );
        let mut bytes = vec![0; before.len() as usize];
        self.file.read_exact_at(&mut bytes, 0)?;
        let after = self.file.metadata()?;
        self.pin.require_file(&self.file)?;
        let stamp = |m: &std::fs::Metadata| {
            (
                m.len(),
                m.mtime(),
                m.mtime_nsec(),
                m.ctime(),
                m.ctime_nsec(),
            )
        };
        anyhow::ensure!(
            stamp(&before) == stamp(&after),
            "original B output changed during pread"
        );
        Ok(OriginalImage {
            bytes,
            stamp: stamp(&after),
        })
    }
}
