//! Test-only, bounded canonical receipt decoding. This is not a production
//! checkpoint format, owner enrollment, trust bootstrap, or custody adapter.
use std::io::Read;

use serde::Deserialize;
use serde::Serialize;

use super::*;

const LIMIT: u64 = 65_536;
const OBSERVATION: &[u8] = b"hepta.learning.iteration-observation.v1\0";
const ATTESTATION: &[u8] = b"hepta.learning-ledger.signed-evidence.v1";

#[derive(Serialize, Deserialize)]
pub(super) struct DiskCheckpoint {
    pub(super) initial: [u8; 32],
    pub(super) head: [u8; 32],
    candidate: Bundle,
    pub(super) payloads: Vec<Vec<u8>>,
    pub(super) attestations: Vec<(Vec<u8>, Vec<u8>)>,
}

#[derive(Serialize, Deserialize)]
struct Bundle {
    artifact: String,
    generation: u64,
    components: [[u8; 32]; 11],
    optional: [Option<[u8; 32]>; 3],
    lineage: [[u8; 32]; 4],
}

impl DiskCheckpoint {
    pub(super) async fn capture(
        snapshot: &LearningIterationSnapshotV1,
        ports: &IterationPorts,
    ) -> anyhow::Result<Self> {
        let LearningIterationObservationV1::Training { candidate, .. } =
            &snapshot.receipts[2].observation
        else {
            anyhow::bail!("training fixture missing")
        };
        let c = &candidate.components;
        let l = candidate
            .training_lineage
            .as_ref()
            .ok_or_else(|| anyhow::anyhow!("training lineage missing"))?;
        let mut attestations = Vec::new();
        for receipt in &snapshot.receipts {
            let signed = ports
                .receipt_attestation(snapshot, receipt, /*_now*/ 50)
                .await?;
            attestations.push((signed.signing_bytes(), signed.signature.to_vec()));
        }
        Ok(Self {
            initial: LearningIterationCoordinatorV1::new(
                snapshot.request.clone(),
                snapshot.owners.clone(),
            )?
            .snapshot()
            .head_digest
            .into_array(),
            head: snapshot.head_digest.into_array(),
            candidate: Bundle {
                artifact: candidate.artifact_id.to_string(),
                generation: candidate.generation.get(),
                components: [
                    c.base,
                    c.heads,
                    c.composition,
                    c.encoder,
                    c.tokenizer,
                    c.normalizer,
                    c.calibration,
                    c.numeric_profile,
                    c.output_schema,
                    c.state_schema,
                    c.state_semantics,
                ]
                .map(Digest32::into_array),
                optional: [
                    c.organ_adapter,
                    c.cell_adapter,
                    candidate.rollback_predecessor,
                ]
                .map(|item| item.map(Digest32::into_array)),
                lineage: [
                    l.source_bundle,
                    l.dataset,
                    l.update_rule,
                    l.evaluation_profile,
                ]
                .map(Digest32::into_array),
            },
            payloads: snapshot
                .receipts
                .iter()
                .map(learning_iteration_receipt_signing_bytes_v1)
                .collect::<Result<_, _>>()?,
            attestations,
        })
    }

    pub(super) fn read(path: &std::path::Path) -> anyhow::Result<Self> {
        let file = std::fs::File::open(path)?;
        anyhow::ensure!(file.metadata()?.is_file(), "regular checkpoint required");
        let mut bytes = Vec::new();
        file.take(LIMIT + 1).read_to_end(&mut bytes)?;
        anyhow::ensure!(bytes.len() as u64 <= LIMIT, "checkpoint limit");
        let disk: Self = serde_json::from_slice(&bytes)?;
        anyhow::ensure!(
            (3..=4).contains(&disk.payloads.len())
                && disk.attestations.len() == disk.payloads.len(),
            "training or evaluated fixture profile required"
        );
        Ok(disk)
    }

    pub(super) fn snapshot(
        &self,
        request: &LearningIterationRequestV1,
        owners: LearningIterationOwnersV1,
        pinned_head: Digest32,
    ) -> anyhow::Result<LearningIterationSnapshotV1> {
        let initial = LearningIterationCoordinatorV1::new(request.clone(), owners.clone())?;
        anyhow::ensure!(
            initial.snapshot().head_digest.into_array() == self.initial
                && pinned_head.into_array() == self.head,
            "host checkpoint pins differ"
        );
        let [
            base,
            heads,
            composition,
            encoder,
            tokenizer,
            normalizer,
            calibration,
            numeric_profile,
            output_schema,
            state_schema,
            state_semantics,
        ] = self.candidate.components.map(Digest32::from_array);
        let [organ_adapter, cell_adapter, rollback_predecessor] = self
            .candidate
            .optional
            .map(|item| item.map(Digest32::from_array));
        let [source_bundle, dataset, update_rule, evaluation_profile] =
            self.candidate.lineage.map(Digest32::from_array);
        let candidate = CellCompatibilityBundleV1 {
            artifact_id: StableId::new(&self.candidate.artifact)?,
            generation: codex_hepta_types::Generation::new(self.candidate.generation)?,
            components: CellBundleComponentsV1 {
                base,
                organ_adapter,
                cell_adapter,
                heads,
                composition,
                encoder,
                tokenizer,
                normalizer,
                calibration,
                numeric_profile,
                output_schema,
                state_schema,
                state_semantics,
            },
            training_lineage: Some(CellTrainingLineageV1 {
                source_bundle,
                dataset,
                update_rule,
                evaluation_profile,
            }),
            rollback_predecessor,
        };
        let receipts = self
            .payloads
            .iter()
            .map(|bytes| decode_receipt(bytes, &candidate))
            .collect::<anyhow::Result<_>>()?;
        Ok(LearningIterationSnapshotV1 {
            request: request.clone(),
            owners,
            receipts,
            head_digest: pinned_head,
        })
    }

    pub(super) fn attestation(
        &self,
        receipt: &LearningIterationReceiptV1,
    ) -> anyhow::Result<SignedLearningEvidenceV1> {
        let payload = learning_iteration_receipt_signing_bytes_v1(receipt)?;
        let index = self
            .payloads
            .iter()
            .position(|stored| *stored == payload)
            .ok_or_else(|| anyhow::anyhow!("receipt not retained"))?;
        let (bytes, signature) = &self.attestations[index];
        let mut input = Input::new(bytes, ATTESTATION)?;
        let evidence_id = input.id64()?;
        let principal_id = input.id64()?;
        let role = match input.array::<1>()?[0] {
            0 => LearningEvidenceRoleV1::Generator,
            1 => LearningEvidenceRoleV1::Observer,
            2 => LearningEvidenceRoleV1::Evaluator,
            _ => anyhow::bail!("unexpected fixture signer role"),
        };
        let signed = SignedLearningEvidenceV1 {
            evidence_id,
            principal_id,
            role,
            trust_digest: Digest32::from_array(input.array()?),
            scope_digest: Digest32::from_array(input.array()?),
            objective_digest: Digest32::from_array(input.array()?),
            authority_epoch: input.u64()?,
            issued_at: input.u64()?,
            expires_at: input.u64()?,
            payload_digest: Digest32::from_array(input.array()?),
            signature: signature.as_slice().try_into()?,
        };
        anyhow::ensure!(input.0.is_empty(), "trailing attestation bytes");
        Ok(signed)
    }
}

fn decode_receipt(
    bytes: &[u8],
    candidate: &CellCompatibilityBundleV1,
) -> anyhow::Result<LearningIterationReceiptV1> {
    let mut input = Input::new(bytes, OBSERVATION)?;
    let operation_id = input.id32()?;
    let predecessor = Digest32::from_array(input.array()?);
    let actor_id = input.id32()?;
    let evidence_digest = Digest32::from_array(input.array()?);
    let observed_unix_seconds = input.u64()?;
    let observation = match input.array::<1>()?[0] {
        0 => LearningIterationObservationV1::Experience {
            episode_digest: Digest32::from_array(input.array()?),
            completed_task_receipt: Digest32::from_array(input.array()?),
        },
        1 => LearningIterationObservationV1::Dataset {
            snapshot_digest: Digest32::from_array(input.array()?),
            episode_digest: Digest32::from_array(input.array()?),
            withdrawal_frontier: Digest32::from_array(input.array()?),
            rows: u32::from_be_bytes(input.array()?),
            bytes: input.u64()?,
        },
        2 => {
            anyhow::ensure!(
                input.array::<32>()? == candidate.digest()?.into_array(),
                "candidate differs from signed receipt"
            );
            LearningIterationObservationV1::Training {
                candidate: Box::new(candidate.clone()),
                steps: input.u64()?,
                milliseconds: input.u64()?,
                artifact_bytes: input.u64()?,
            }
        }
        3 => LearningIterationObservationV1::Evaluation {
            candidate_bundle: Digest32::from_array(input.array()?),
            evaluation_profile: Digest32::from_array(input.array()?),
            disposition: match input.array::<1>()?[0] {
                0 => LearningEvaluationDispositionV1::Qualified,
                1 => LearningEvaluationDispositionV1::NoUpdate,
                _ => anyhow::bail!("unknown evaluation disposition"),
            },
        },
        _ => anyhow::bail!("unsupported fixture stage"),
    };
    anyhow::ensure!(input.0.is_empty(), "trailing receipt bytes");
    Ok(LearningIterationReceiptV1 {
        operation_id,
        predecessor,
        actor_id,
        evidence_digest,
        observed_unix_seconds,
        observation,
    })
}

struct Input<'a>(&'a [u8]);

impl<'a> Input<'a> {
    fn new(bytes: &'a [u8], domain: &[u8]) -> anyhow::Result<Self> {
        Ok(Self(
            bytes
                .strip_prefix(domain)
                .ok_or_else(|| anyhow::anyhow!("wrong domain"))?,
        ))
    }
    fn array<const N: usize>(&mut self) -> anyhow::Result<[u8; N]> {
        let (value, rest) = self
            .0
            .split_at_checked(N)
            .ok_or_else(|| anyhow::anyhow!("short canonical input"))?;
        self.0 = rest;
        Ok(value.try_into()?)
    }
    fn u64(&mut self) -> anyhow::Result<u64> {
        Ok(u64::from_be_bytes(self.array()?))
    }
    fn id32(&mut self) -> anyhow::Result<StableId> {
        let size = u32::from_be_bytes(self.array()?) as u64;
        self.id(size)
    }
    fn id64(&mut self) -> anyhow::Result<StableId> {
        let size = self.u64()?;
        self.id(size)
    }
    fn id(&mut self, size: u64) -> anyhow::Result<StableId> {
        anyhow::ensure!(size <= LIMIT, "identifier limit");
        let (value, rest) = self
            .0
            .split_at_checked(size as usize)
            .ok_or_else(|| anyhow::anyhow!("short identifier"))?;
        self.0 = rest;
        Ok(StableId::new(std::str::from_utf8(value)?)?)
    }
}
