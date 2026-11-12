//! Bounded purpose data. This format has no decoder for a native Cell plan,
//! evaluation receipt, qualification, runner, heldout owner or signing key.

use std::io;
use std::path::PathBuf;

use codex_hepta_learning_artifacts::LearningEvaluationDispositionV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use codex_hepta_neuron::CellBackendManifestV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::HostAuthorityRegisteredIdentity;

pub(crate) const PURPOSE: &str = "runtime.learning.independent-b-evaluation.v1";
pub(crate) const SOCKET: &str = "independent-b-evaluation-v1.sock";

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Bootstrap {
    pub(crate) purpose: String,
    pub(crate) root: CognitiveCheckpointPeerLifetime,
    pub(crate) consumer: CognitiveCheckpointPeerLifetime,
    pub(crate) identity: HostAuthorityRegisteredIdentity,
    pub(crate) initial: String,
    pub(crate) scope: String,
    pub(crate) writer: String,
    pub(crate) binding: String,
    pub(crate) socket: PathBuf,
    pub(crate) candidate_data_device: u64,
    pub(crate) candidate_data_inode: u64,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Request {
    pub(crate) schema: u8,
    pub(crate) purpose: String,
    pub(crate) sequence: u64,
    pub(crate) binding: String,
    pub(crate) command: Command,
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum Command {
    Observe,
    PrepareCandidate {
        training_head: String,
        training_attestation: Vec<u8>,
    },
    Complete {
        training_head: String,
        training_attestation: Vec<u8>,
        plan_attestation: Vec<u8>,
        source_admission: Box<crate::root_independent_b_source_ready::SourceReadyData>,
    },
    Readback {
        training_head: String,
    },
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Response {
    pub(crate) schema: u8,
    pub(crate) purpose: String,
    pub(crate) sequence: u64,
    pub(crate) binding: String,
    pub(crate) result: Observation,
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum Observation {
    Bound { initial: String },
    Prepared(Box<PreparedPlanData>),
    Completed(Box<CompletedData>),
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct CompletedData {
    pub(crate) training_head: String,
    pub(crate) receipt: ReceiptData,
    pub(crate) attestation: Vec<u8>,
    pub(crate) manifest: CellBackendManifestV2,
    pub(crate) comparison_digest: String,
    pub(crate) plan_digest: String,
    pub(crate) execution_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ReceiptData {
    operation: String,
    predecessor: String,
    actor: String,
    evidence: String,
    observed_at: u64,
    candidate: String,
    profile: String,
    disposition: Disposition,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum Disposition {
    Qualified,
    NoUpdate,
}

impl ReceiptData {
    pub(crate) fn from_original(receipt: &LearningIterationReceiptV1) -> io::Result<Self> {
        let LearningIterationObservationV1::Evaluation {
            candidate_bundle,
            evaluation_profile,
            disposition,
        } = &receipt.observation
        else {
            return Err(io::Error::other("original B receipt is not Evaluation"));
        };
        Ok(Self {
            operation: receipt.operation_id.to_string(),
            predecessor: receipt.predecessor.to_string(),
            actor: receipt.actor_id.to_string(),
            evidence: receipt.evidence_digest.to_string(),
            observed_at: receipt.observed_unix_seconds,
            candidate: candidate_bundle.to_string(),
            profile: evaluation_profile.to_string(),
            disposition: match disposition {
                LearningEvaluationDispositionV1::Qualified => Disposition::Qualified,
                LearningEvaluationDispositionV1::NoUpdate => Disposition::NoUpdate,
            },
        })
    }

    pub(crate) fn data(&self) -> io::Result<LearningIterationReceiptV1> {
        for value in [&self.operation, &self.actor] {
            if value.is_empty() || value.len() > 128 {
                return Err(io::Error::other("bounded original B receipt id required"));
            }
        }
        Ok(LearningIterationReceiptV1 {
            operation_id: StableId::new(&self.operation).map_err(io::Error::other)?,
            predecessor: digest(&self.predecessor)?,
            actor_id: StableId::new(&self.actor).map_err(io::Error::other)?,
            evidence_digest: digest(&self.evidence)?,
            observed_unix_seconds: self.observed_at,
            observation: LearningIterationObservationV1::Evaluation {
                candidate_bundle: digest(&self.candidate)?,
                evaluation_profile: digest(&self.profile)?,
                disposition: match self.disposition {
                    Disposition::Qualified => LearningEvaluationDispositionV1::Qualified,
                    Disposition::NoUpdate => LearningEvaluationDispositionV1::NoUpdate,
                },
            },
        })
    }
}

pub(crate) fn digest(value: &str) -> io::Result<Digest32> {
    let result = value.parse::<Digest32>().map_err(io::Error::other)?;
    if result.is_zero() || result.to_string() != value {
        return Err(io::Error::other("canonical nonempty B digest required"));
    }
    Ok(result)
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PreparedPlanData {
    pub(crate) initial: String,
    pub(crate) scope: String,
    pub(crate) training_head: String,
    pub(crate) candidate_bundle: String,
    pub(crate) profile: String,
    pub(crate) plan_digest: String,
    pub(crate) comparison_digest: String,
    pub(crate) expires_at_seconds: u64,
}
