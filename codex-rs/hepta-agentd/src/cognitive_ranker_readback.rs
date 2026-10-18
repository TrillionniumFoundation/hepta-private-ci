use super::PinnedCognitiveRanker;
use super::RankerEvaluationAdmission;
use crate::CognitiveModelIdentity;
use crate::CognitiveModelReadback;

impl PinnedCognitiveRanker {
    pub(crate) fn readback(&self) -> Result<CognitiveModelReadback, String> {
        self.with_current(|| {
            let selection = match &self.admission {
                RankerEvaluationAdmission::Selected(selection) => Some(selection.as_ref()),
                RankerEvaluationAdmission::HostPinned | RankerEvaluationAdmission::Rollback(_) => {
                    None
                }
            };
            Ok(CognitiveModelReadback {
                spawn_generation: self.body_generation,
                model: CognitiveModelIdentity {
                    artifact_id: self.model.artifact_id().as_str().to_owned(),
                    artifact_generation: self.model_generation,
                    payload_sha256: self.policy_digest.to_string(),
                },
                source_manifest_sha256: self
                    .source_manifest_digest
                    .map(|digest| digest.to_string()),
                selection_sha256: selection
                    .map(|selection| selection.selection_digest().to_string()),
                evaluated_predecessor: selection.map(|selection| {
                    let receipt = selection.receipt();
                    CognitiveModelIdentity {
                        artifact_id: receipt.predecessor_id.as_str().to_owned(),
                        artifact_generation: receipt.predecessor_generation.get(),
                        payload_sha256: receipt.predecessor_artifact_digest.to_string(),
                    }
                }),
                current_owner_trust_sha256: self.current_owner_trust_digest.to_string(),
            })
        })
    }
}
