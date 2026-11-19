//! Single-operation external-artifact research owner. Compiled only for tests on
//! Unix. Its receipt is not Parameter V3, Product OPE, or production authority.
//! The sibling anchor detects rollback of the record directory while that anchor
//! is retained. Coordinated rollback of both directories is outside this profile.

use std::fmt;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;

use anyhow::Context;
use anyhow::ensure;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::LearningProposalDispositionV1;
use codex_hepta_types::Digest32;
use serde_json::Value;
use serde_json::json;

use crate::LearningIterationRuntimeErrorV1;
use crate::learning_iteration_research_external_material as material;

const DOMAIN: &[u8] = b"hepta.research.external-trained-artifact.receipt.v1\0";
const SCOPE: &str = "actual-local-training-frozen-four-prompt-comparison-only";

struct OwnerInner {
    root: material::Directory,
    anchor: material::Directory,
    model: PathBuf,
    evidence: PathBuf,
    initial: LearningIterationSnapshotV1,
    bootstrap: Value,
    serial: Mutex<()>,
}

/// A concrete owner, not a caller-supplied digest or callback.
#[derive(Clone)]
pub(crate) struct ResearchExternalTrainedArtifactOwnerV1(Arc<OwnerInner>);

impl fmt::Debug for ResearchExternalTrainedArtifactOwnerV1 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("ResearchExternalTrainedArtifactOwnerV1")
            .field("genesis", &self.0.initial.head_digest)
            .finish_non_exhaustive()
    }
}

/// Public only because the existing public test payload enum contains it.
/// Neither its fields nor a receipt/composition constructor are public.
#[derive(Clone, Debug)]
pub struct ResearchExternalTrainedArtifactProposalV1 {
    owner: ResearchExternalTrainedArtifactOwnerV1,
    predecessor: Digest32,
    material: Value,
}

#[derive(Debug)]
pub(crate) struct ResearchExternalTrainedArtifactReceiptV1 {
    composition_digest: Digest32,
}

impl ResearchExternalTrainedArtifactReceiptV1 {
    pub(crate) fn composition_digest(&self) -> Digest32 {
        self.composition_digest
    }
}

fn unavailable(error: impl fmt::Display) -> LearningIterationRuntimeErrorV1 {
    eprintln!("external trained artifact research owner refused: {error}");
    LearningIterationRuntimeErrorV1::OwnerUnavailable("research-external-trained-artifact-v1")
}

fn digest_record(value: &Value) -> anyhow::Result<Digest32> {
    Ok(Digest32::of_parts(&[DOMAIN, &material::canonical(value)?]))
}

fn verify_record_policy(
    record: &Value,
    prefix: &LearningIterationSnapshotV1,
) -> anyhow::Result<u64> {
    ensure!(
        record.as_object().context("research receipt object")?.len() == 9
            && record["schema"] == "hepta.research.external-trained-artifact.receipt.v1"
            && record["scope"] == SCOPE
            && record["qualification"] == "HOLD_NO_GO"
            && record["parameter_v3_qualified"] == false
            && record["product_ope_qualified"] == false
            && record["production_qualified"] == false,
        "closed research-only receipt policy"
    );
    let committed_at = record["committed_unix_seconds"]
        .as_u64()
        .context("commit time")?;
    ensure!(
        committed_at < prefix.request.envelope.expiry_unix_seconds
            && prefix
                .receipts
                .last()
                .is_some_and(|r| committed_at >= r.observed_unix_seconds),
        "original research commit time outside authenticated evaluation window"
    );
    Ok(committed_at)
}

impl ResearchExternalTrainedArtifactOwnerV1 {
    pub(crate) fn create(
        root: PathBuf,
        model_root: PathBuf,
        evidence_root: PathBuf,
        initial: &LearningIterationSnapshotV1,
    ) -> Result<Self, LearningIterationRuntimeErrorV1> {
        (|| -> anyhow::Result<Self> {
            let canonical = LearningIterationCoordinatorV1::new(
                initial.request.clone(),
                initial.owners.clone(),
            )?;
            ensure!(
                canonical.snapshot() == initial,
                "owner requires the exact initial snapshot"
            );
            ensure!(
                initial.owners.proposal.to_string()
                    == format!(
                        "{}-research-external-artifact-v1",
                        initial.request.operation_id
                    ),
                "wrong research proposal owner"
            );
            let frozen = material::freeze(&model_root, &evidence_root, initial)?;
            let name = root
                .file_name()
                .and_then(|s| s.to_str())
                .context("owner root name")?;
            let anchor_path = root.with_file_name(format!("{name}-anchor"));
            let root = material::Directory::create(root)?;
            let anchor = material::Directory::create(anchor_path)?;
            let mut bootstrap = json!({
                "schema":"hepta.research.external-trained-artifact.bootstrap.v1",
                "scope":SCOPE,"qualification":"HOLD_NO_GO",
                "genesis":initial.head_digest.to_string(),
                "operation":initial.request.operation_id.to_string(),
                "owner":initial.owners.proposal.to_string(),
                "model_root":model_root,"evidence_root":evidence_root,"frozen":frozen,
                "parameter_v3_qualified":false,"product_ope_qualified":false,
                "production_qualified":false
            });
            match (
                root.optional("bootstrap.json")?,
                anchor.optional("bootstrap.json")?,
            ) {
                (None, None) => {
                    material::require_unstarted(&model_root)?;
                    let created = u64::try_from(
                        std::time::SystemTime::now()
                            .duration_since(std::time::UNIX_EPOCH)?
                            .as_nanos(),
                    )?;
                    bootstrap["created_unix_ns"] = created.into();
                    let bytes = material::canonical(&bootstrap)?;
                    // Both are create-only. A crash or competing initializer is
                    // an uncertain initialization, never permission to repair.
                    root.publish("bootstrap.json", &bytes)?;
                    anchor.publish("bootstrap.json", &bytes)?;
                }
                (Some(a), Some(b)) => {
                    let original = material::parse(&a)?;
                    let created = original["created_unix_ns"]
                        .as_u64()
                        .context("original owner creation time")?;
                    bootstrap["created_unix_ns"] = created.into();
                    ensure!(
                        a == material::canonical(&bootstrap)? && b == a,
                        "owner bootstrap changed"
                    );
                }
                _ => anyhow::bail!("partial owner bootstrap; explicit recovery required"),
            }
            root.require_linked()?;
            anchor.require_linked()?;
            Ok(Self(Arc::new(OwnerInner {
                root,
                anchor,
                model: model_root,
                evidence: evidence_root,
                initial: initial.clone(),
                bootstrap,
                serial: Mutex::new(()),
            })))
        })()
        .map_err(unavailable)
    }

    fn verify_context(&self, snapshot: &LearningIterationSnapshotV1) -> anyhow::Result<()> {
        ensure!(
            snapshot.request == self.0.initial.request && snapshot.owners == self.0.initial.owners,
            "operation/request/owner substitution"
        );
        LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;
        let bytes = material::canonical(&self.0.bootstrap)?;
        ensure!(
            self.0.root.read("bootstrap.json")? == bytes
                && self.0.anchor.read("bootstrap.json")? == bytes,
            "bootstrap/anchor drift"
        );
        self.0.root.require_linked()?;
        self.0.anchor.require_linked()?;
        ensure!(
            material::freeze(&self.0.model, &self.0.evidence, &self.0.initial)?
                == self.0.bootstrap["frozen"],
            "frozen inputs changed"
        );
        Ok(())
    }

    fn materials(&self, snapshot: &LearningIterationSnapshotV1) -> anyhow::Result<Value> {
        self.verify_context(snapshot)?;
        material::verify(
            &self.0.model,
            &self.0.evidence,
            snapshot,
            self.0.initial.head_digest,
            &self.0.bootstrap["frozen"],
            self.0.bootstrap["created_unix_ns"]
                .as_u64()
                .context("owner creation time")?,
        )
    }

    pub(crate) fn prepare(
        &self,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<ResearchExternalTrainedArtifactProposalV1, LearningIterationRuntimeErrorV1> {
        let material = self.materials(snapshot).map_err(unavailable)?;
        Ok(ResearchExternalTrainedArtifactProposalV1 {
            owner: self.clone(),
            predecessor: snapshot.head_digest,
            material,
        })
    }

    fn committed(&self) -> anyhow::Result<Option<Value>> {
        match (
            self.0.root.optional("receipt.json")?,
            self.0.anchor.optional("receipt.json")?,
        ) {
            (None, None) => {
                ensure!(
                    self.0.root.optional("reservation.json")?.is_none(),
                    "uncertain reserved proposal; no replay of work"
                );
                Ok(None)
            }
            (Some(raw), Some(anchor)) => {
                let value = material::parse(&raw)?;
                ensure!(
                    material::canonical(&value)? == raw,
                    "noncanonical owner receipt"
                );
                let reservation = self.0.root.read("reservation.json")?;
                let expected = json!({"schema":"hepta.research.external-trained-artifact.anchor.v1",
                    "genesis":self.0.initial.head_digest.to_string(),
                    "operation":self.0.initial.request.operation_id.to_string(),
                    "receipt_sha256":Digest32::of_bytes(&raw).to_string(),
                    "composition_digest":digest_record(&value)?.to_string(),
                    "reservation_sha256":Digest32::of_bytes(&reservation).to_string()});
                ensure!(
                    material::canonical(&expected)? == anchor,
                    "receipt/anchor mismatch"
                );
                ensure!(
                    material::parse(&reservation)? == value["reservation"],
                    "reservation changed"
                );
                self.0.root.require_linked()?;
                self.0.anchor.require_linked()?;
                Ok(Some(value))
            }
            _ => anyhow::bail!("partial owner commit; no synthetic receipt"),
        }
    }

    pub(crate) fn verify_restored(
        &self,
        snapshot: &LearningIterationSnapshotV1,
    ) -> Result<(), LearningIterationRuntimeErrorV1> {
        (|| -> anyhow::Result<()> {
            self.verify_context(snapshot)?;
            let mut prefix = LearningIterationCoordinatorV1::new(
                snapshot.request.clone(), snapshot.owners.clone())?;
            let proposal = snapshot.receipts.iter().find(|r|
                r.observation.stage() == LearningIterationStageV1::Proposal);
            for receipt in &snapshot.receipts {
                if receipt.observation.stage() == LearningIterationStageV1::Proposal { break; }
                // The full snapshot replay above rejects malformed or duplicate
                // stages. Replay uses original times, so expired readback works.
                prefix.record(receipt.clone(), receipt.observed_unix_seconds)?;
            }
            let stored = self.committed()?;
            if proposal.is_none() && stored.is_none() { return Ok(()); }
            let stored = stored.context("proposal exists without durable research owner")?;
            let expected_material = self.materials(prefix.snapshot())?;
            let expected_reservation = json!({"schema":"hepta.research.external-trained-artifact.reservation.v1",
                "genesis":self.0.initial.head_digest.to_string(),
                "operation":snapshot.request.operation_id.to_string(),
                "owner":snapshot.owners.proposal.to_string(),
                "predecessor":prefix.snapshot().head_digest.to_string(),
                "material_sha256":Digest32::of_bytes(&material::canonical(&expected_material)?).to_string()});
            ensure!(stored["material"] == expected_material
                && stored["reservation"] == expected_reservation
                && stored["reservation"]["predecessor"] == prefix.snapshot().head_digest.to_string()
                && stored["reservation"]["genesis"] == self.0.initial.head_digest.to_string()
                && stored["reservation"]["operation"] == snapshot.request.operation_id.to_string()
                && stored["reservation"]["owner"] == snapshot.owners.proposal.to_string()
                && stored["schema"] == "hepta.research.external-trained-artifact.receipt.v1"
                && stored["scope"] == SCOPE && stored["qualification"] == "HOLD_NO_GO"
                && stored["parameter_v3_qualified"] == false && stored["product_ope_qualified"] == false
                && stored["production_qualified"] == false, "durable research receipt context");
            let committed_at = verify_record_policy(&stored, prefix.snapshot())?;
            if let Some(proposal) = proposal {
                let composition = digest_record(&stored)?;
                ensure!(proposal.evidence_digest == composition
                    && proposal.actor_id == snapshot.owners.proposal
                    && proposal.observed_unix_seconds >= committed_at, "proposal receipt owner binding");
                ensure!(proposal.observation == LearningIterationObservationV1::Proposal {
                    candidate_bundle:material::digest(&expected_material["candidate_bundle"])?,
                    proposal_id:snapshot.request.operation_id.clone(), composition_digest:composition,
                    disposition:LearningProposalDispositionV1::UpdateCandidates,
                }, "restored proposal differs from durable research receipt");
            }
            Ok(())
        })().map_err(unavailable)
    }
}

impl ResearchExternalTrainedArtifactProposalV1 {
    pub(crate) fn commit_for(
        &self,
        snapshot: &LearningIterationSnapshotV1,
        now: u64,
    ) -> Result<ResearchExternalTrainedArtifactReceiptV1, LearningIterationRuntimeErrorV1> {
        let _serial = self
            .owner
            .0
            .serial
            .lock()
            .map_err(|_| unavailable("owner lock poisoned"))?;
        if now >= snapshot.request.envelope.expiry_unix_seconds {
            return Err(LearningIterationRuntimeErrorV1::DeadlineExceeded);
        }
        if snapshot
            .receipts
            .last()
            .is_none_or(|receipt| now < receipt.observed_unix_seconds)
        {
            return Err(unavailable(
                "proposal clock precedes authenticated evaluation",
            ));
        }
        let current = self.owner.materials(snapshot).map_err(unavailable)?;
        if snapshot.head_digest != self.predecessor || current != self.material {
            return Err(unavailable("prepared material or predecessor changed"));
        }
        let reservation = json!({"schema":"hepta.research.external-trained-artifact.reservation.v1",
            "genesis":self.owner.0.initial.head_digest.to_string(),
            "operation":snapshot.request.operation_id.to_string(),
            "owner":snapshot.owners.proposal.to_string(),"predecessor":self.predecessor.to_string(),
            "material_sha256":Digest32::of_bytes(&material::canonical(&current).map_err(unavailable)?).to_string()});
        let stored = self.owner.committed().map_err(|error| {
            eprintln!("research owner commit readback uncertain: {error}");
            LearningIterationRuntimeErrorV1::CommitUncertain
        })?;
        let record = if let Some(stored) = stored {
            if stored["reservation"] != reservation || stored["material"] != current {
                return Err(unavailable(
                    "operation already committed to different material",
                ));
            }
            stored
        } else {
            let value = json!({"schema":"hepta.research.external-trained-artifact.receipt.v1",
                "scope":SCOPE,"qualification":"HOLD_NO_GO", "reservation":reservation,
                "material":current,"committed_unix_seconds":now,
                "parameter_v3_qualified":false,"product_ope_qualified":false,"production_qualified":false});
            (|| -> anyhow::Result<()> {
                let reservation = material::canonical(&reservation)?;
                // O_EXCL is the cross-process CAS. Any partial result remains
                // uncertain, rather than being deleted or silently completed.
                self.owner
                    .0
                    .root
                    .publish("reservation.json", &reservation)?;
                let bytes = material::canonical(&value)?;
                self.owner.0.root.publish("receipt.json", &bytes)?;
                let anchor = json!({"schema":"hepta.research.external-trained-artifact.anchor.v1",
                    "genesis":self.owner.0.initial.head_digest.to_string(),
                    "operation":snapshot.request.operation_id.to_string(),
                    "receipt_sha256":Digest32::of_bytes(&bytes).to_string(),
                    "composition_digest":digest_record(&value)?.to_string(),
                    "reservation_sha256":Digest32::of_bytes(&reservation).to_string()});
                self.owner
                    .0
                    .anchor
                    .publish("receipt.json", &material::canonical(&anchor)?)?;
                ensure!(
                    self.owner.committed()? == Some(value.clone()),
                    "commit readback changed"
                );
                Ok(())
            })()
            .map_err(|error| {
                eprintln!("research owner commit uncertain: {error}");
                LearningIterationRuntimeErrorV1::CommitUncertain
            })?;
            value
        };
        // Exact replay has the same authority and original-time requirements
        // as cold readback; matching material alone cannot promote a receipt.
        verify_record_policy(&record, snapshot).map_err(unavailable)?;
        // A changed external file after the initial read cannot advance the
        // native Proposal. Preserve any durable record for explicit recovery.
        if self.owner.materials(snapshot).map_err(unavailable)? != self.material {
            return Err(LearningIterationRuntimeErrorV1::CommitUncertain);
        }
        Ok(ResearchExternalTrainedArtifactReceiptV1 {
            composition_digest: digest_record(&record).map_err(unavailable)?,
        })
    }
}
