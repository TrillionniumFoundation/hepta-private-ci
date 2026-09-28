from pathlib import Path
import json

ROOT = Path.cwd()

def replace(path: str, old: str, new: str, count: int = 1) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    actual = text.count(old)
    if actual < count:
        raise SystemExit(
            f"{path}: expected at least {count} occurrence(s), found {actual}: {old[:120]!r}"
        )
    target.write_text(text.replace(old, new, count), encoding="utf-8")

def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.rstrip() + "\n", encoding="utf-8")

# --- Typed admission and recovery contract.
write(
    "codex-rs/hepta-bellman-operator/src/admission.rs",
    r"""
//! Shared admission stages and actionable failure dispositions.
//!
//! These types describe existing owner boundaries. They do not create a
//! second selector, evaluator, artifact registry, or runtime.

use crate::OperatorDatasetBindingError;
use crate::TabularPayloadError;
use codex_hepta_learning_ledger::SignedEvidenceError;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OperatorAdmissionStageV1 {
    RawInput,
    StructurallyValidated,
    SourceAuthenticated,
    CurrentAtUse,
    ImmutableCandidate,
    IndependentlyEvaluated,
    SelectedReadOnly,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OperatorFailureScopeV1 {
    Request,
    Candidate,
    Consumer,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OperatorRecoveryActionV1 {
    CorrectRequest,
    ObtainFreshOwnerEvidence,
    RejectCandidate,
    ReloadSelectedCandidate,
    AbstainUnsupportedCell,
    StopConsumer,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct OperatorFailureDispositionV1 {
    pub scope: OperatorFailureScopeV1,
    pub action: OperatorRecoveryActionV1,
}

impl OperatorFailureDispositionV1 {
    #[must_use]
    pub const fn stops_consumer(self) -> bool {
        matches!(self.action, OperatorRecoveryActionV1::StopConsumer)
    }

    #[must_use]
    pub const fn rejects_candidate(self) -> bool {
        matches!(self.action, OperatorRecoveryActionV1::RejectCandidate)
    }
}

pub trait ClassifyOperatorAdmissionFailure {
    fn disposition(&self) -> OperatorFailureDispositionV1;
}

impl ClassifyOperatorAdmissionFailure for OperatorDatasetBindingError {
    fn disposition(&self) -> OperatorFailureDispositionV1 {
        use OperatorFailureScopeV1 as Scope;
        use OperatorRecoveryActionV1 as Action;

        match self {
            Self::SignedEvidence(error) => match error {
                SignedEvidenceError::Revoked
                | SignedEvidenceError::ValidityWindow
                | SignedEvidenceError::ContextMismatch
                | SignedEvidenceError::UnknownSigner => OperatorFailureDispositionV1 {
                    scope: Scope::Candidate,
                    action: Action::ObtainFreshOwnerEvidence,
                },
                SignedEvidenceError::PayloadLimit => OperatorFailureDispositionV1 {
                    scope: Scope::Request,
                    action: Action::CorrectRequest,
                },
                SignedEvidenceError::Principal(_)
                | SignedEvidenceError::InvalidTrust
                | SignedEvidenceError::InvalidKey
                | SignedEvidenceError::RoleMismatch
                | SignedEvidenceError::PayloadMismatch
                | SignedEvidenceError::InvalidSignature
                | SignedEvidenceError::ControllerCollision => {
                    OperatorFailureDispositionV1 {
                        scope: Scope::Candidate,
                        action: Action::RejectCandidate,
                    }
                }
            },
            Self::DatasetReceipt(_) | Self::TrustContextMismatch => {
                OperatorFailureDispositionV1 {
                    scope: Scope::Candidate,
                    action: Action::ObtainFreshOwnerEvidence,
                }
            },
            Self::ClockRegression | Self::Owner(_) => OperatorFailureDispositionV1 {
                scope: Scope::Consumer,
                action: Action::StopConsumer,
            },
            Self::Learned(_) | Self::WorldModel(_) => OperatorFailureDispositionV1 {
                scope: Scope::Candidate,
                action: Action::RejectCandidate,
            },
            Self::DatasetDigestMismatch
            | Self::ObjectiveDigestMismatch
            | Self::EvidenceSetMismatch
            | Self::DuplicateEvidence
            | Self::DuplicateIdentity
            | Self::Bounds
            | Self::Arithmetic => OperatorFailureDispositionV1 {
                scope: Scope::Request,
                action: Action::CorrectRequest,
            },
        }
    }
}

impl ClassifyOperatorAdmissionFailure for TabularPayloadError {
    fn disposition(&self) -> OperatorFailureDispositionV1 {
        use OperatorFailureScopeV1 as Scope;
        use OperatorRecoveryActionV1 as Action;

        match self {
            Self::UnsupportedCell => OperatorFailureDispositionV1 {
                scope: Scope::Request,
                action: Action::AbstainUnsupportedCell,
            },
            Self::Binding => OperatorFailureDispositionV1 {
                scope: Scope::Consumer,
                action: Action::ReloadSelectedCandidate,
            },
            Self::Authority => OperatorFailureDispositionV1 {
                scope: Scope::Consumer,
                action: Action::StopConsumer,
            },
            Self::Bounds | Self::Encoding | Self::Grid => {
                OperatorFailureDispositionV1 {
                    scope: Scope::Candidate,
                    action: Action::RejectCandidate,
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unsupported_cells_abstain_without_invalidating_the_candidate() {
        assert_eq!(
            TabularPayloadError::UnsupportedCell.disposition(),
            OperatorFailureDispositionV1 {
                scope: OperatorFailureScopeV1::Request,
                action: OperatorRecoveryActionV1::AbstainUnsupportedCell,
            }
        );
    }

    #[test]
    fn payload_authority_failure_stops_the_consumer() {
        assert!(
            TabularPayloadError::Authority
                .disposition()
                .stops_consumer()
        );
    }

    #[test]
    fn malformed_candidate_payload_is_candidate_global() {
        assert!(
            TabularPayloadError::Encoding
                .disposition()
                .rejects_candidate()
        );
    }

    #[test]
    fn revoked_evidence_requires_fresh_owner_admission() {
        let failure =
            OperatorDatasetBindingError::SignedEvidence(SignedEvidenceError::Revoked);
        assert_eq!(
            failure.disposition(),
            OperatorFailureDispositionV1 {
                scope: OperatorFailureScopeV1::Candidate,
                action: OperatorRecoveryActionV1::ObtainFreshOwnerEvidence,
            }
        );
    }
}
""",
)

replace(
    "codex-rs/hepta-bellman-operator/src/lib.rs",
    "mod authenticated;\nmod dataset_bound;",
    "mod admission;\nmod authenticated;\nmod dataset_bound;",
)
replace(
    "codex-rs/hepta-bellman-operator/src/lib.rs",
    "pub use authenticated::AuthenticatedApplicabilityAdmissionV2;",
    """pub use admission::ClassifyOperatorAdmissionFailure;
pub use admission::OperatorAdmissionStageV1;
pub use admission::OperatorFailureDispositionV1;
pub use admission::OperatorFailureScopeV1;
pub use admission::OperatorRecoveryActionV1;
pub use authenticated::AuthenticatedApplicabilityAdmissionV2;""",
)
replace(
    "codex-rs/hepta-bellman-operator/src/lib.rs",
    "pub use dataset_bound::OperatorDatasetBindingError;",
    """pub use dataset_bound::OperatorDatasetBindingError;
pub use dataset_bound::OwnerDatasetFailureV1;
pub use dataset_bound::OwnerDatasetOperationV1;""",
)

# --- Dataset owner errors retain the failed owner operation.
replace(
    "codex-rs/hepta-bellman-operator/src/dataset_bound.rs",
    "use crate::StrictLearnedOperatorError;",
    "use crate::OperatorAdmissionStageV1;\nuse crate::StrictLearnedOperatorError;",
)
replace(
    "codex-rs/hepta-bellman-operator/src/dataset_bound.rs",
    "impl VerifiedTabularOperatorPlanV3<'_> {\n    #[must_use]\n    pub fn ledger_head_digest",
    """impl VerifiedTabularOperatorPlanV2 {
    #[must_use]
    pub const fn admission_stage(&self) -> OperatorAdmissionStageV1 {
        OperatorAdmissionStageV1::StructurallyValidated
    }
}

impl VerifiedTabularOperatorPlanV3<'_> {
    #[must_use]
    pub const fn admission_stage(&self) -> OperatorAdmissionStageV1 {
        OperatorAdmissionStageV1::SourceAuthenticated
    }

    #[must_use]
    pub fn ledger_head_digest""",
)
replace(
    "codex-rs/hepta-bellman-operator/src/dataset_bound.rs",
    "impl VerifiedWorldModelDatasetV3<'_> {\n    #[must_use]\n    pub fn ledger_head_digest",
    """impl VerifiedWorldModelDatasetV2 {
    #[must_use]
    pub const fn admission_stage(&self) -> OperatorAdmissionStageV1 {
        OperatorAdmissionStageV1::StructurallyValidated
    }
}

impl VerifiedWorldModelDatasetV3<'_> {
    #[must_use]
    pub const fn admission_stage(&self) -> OperatorAdmissionStageV1 {
        OperatorAdmissionStageV1::SourceAuthenticated
    }

    #[must_use]
    pub fn ledger_head_digest""",
)
replace(
    "codex-rs/hepta-bellman-operator/src/dataset_bound.rs",
    """.freeze_dataset(plan.clone(), &self.freeze_evidence, now)
            .map_err(|error| OperatorDatasetBindingError::Owner(error.to_string()))?;""",
    """.freeze_dataset(plan.clone(), &self.freeze_evidence, now)
            .map_err(|error| {
                owner_failure(OwnerDatasetOperationV1::FreezeDataset, error)
            })?;""",
)
replace(
    "codex-rs/hepta-bellman-operator/src/dataset_bound.rs",
    """.read_dataset_records(&self.receipt, now)
            .map_err(|error| OperatorDatasetBindingError::Owner(error.to_string()))?;""",
    """.read_dataset_records(&self.receipt, now)
            .map_err(|error| {
                owner_failure(OwnerDatasetOperationV1::ReadDatasetRecords, error)
            })?;""",
)
replace(
    "codex-rs/hepta-bellman-operator/src/dataset_bound.rs",
    """.snapshot()
            .map_err(|error| OperatorDatasetBindingError::Owner(error.to_string()))?;""",
    """.snapshot()
            .map_err(|error| owner_failure(OwnerDatasetOperationV1::Snapshot, error))?;""",
)
replace(
    "codex-rs/hepta-bellman-operator/src/dataset_bound.rs",
    """let freeze_payload = dataset_freeze_signing_payload_v2(&snapshot, &plan)
            .map_err(|error| OperatorDatasetBindingError::Owner(error.to_string()))?;""",
    """let freeze_payload = dataset_freeze_signing_payload_v2(&snapshot, &plan)
            .map_err(|error| {
                owner_failure(OwnerDatasetOperationV1::EncodeFreezePayload, error)
            })?;""",
)
replace(
    "codex-rs/hepta-bellman-operator/src/dataset_bound.rs",
    "#[derive(Clone, Debug, Eq, PartialEq)]\npub enum OperatorDatasetBindingError {",
    r"""#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OwnerDatasetOperationV1 {
    FreezeDataset,
    ReadDatasetRecords,
    Snapshot,
    EncodeFreezePayload,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OwnerDatasetFailureV1 {
    pub operation: OwnerDatasetOperationV1,
    pub message: String,
}

impl fmt::Display for OwnerDatasetFailureV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{:?}: {}", self.operation, self.message)
    }
}
impl StdError for OwnerDatasetFailureV1 {}

fn owner_failure(
    operation: OwnerDatasetOperationV1,
    error: impl fmt::Display,
) -> OperatorDatasetBindingError {
    OperatorDatasetBindingError::Owner(OwnerDatasetFailureV1 {
        operation,
        message: error.to_string(),
    })
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum OperatorDatasetBindingError {""",
)
replace(
    "codex-rs/hepta-bellman-operator/src/dataset_bound.rs",
    "    Owner(String),",
    "    Owner(OwnerDatasetFailureV1),",
)
replace(
    "codex-rs/hepta-bellman-operator/src/dataset_bound.rs",
    "impl StdError for OperatorDatasetBindingError {}",
    """impl StdError for OperatorDatasetBindingError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::DatasetReceipt(error) => Some(error),
            Self::SignedEvidence(error) => Some(error),
            Self::Owner(error) => Some(error),
            Self::Learned(error) => Some(error),
            Self::WorldModel(error) => Some(error),
            Self::DatasetDigestMismatch
            | Self::ObjectiveDigestMismatch
            | Self::EvidenceSetMismatch
            | Self::TrustContextMismatch
            | Self::DuplicateEvidence
            | Self::DuplicateIdentity
            | Self::Bounds
            | Self::ClockRegression
            | Self::Arithmetic => None,
        }
    }
}""",
)

# --- Explicit stage accessors for structural and selected values.
replace(
    "codex-rs/hepta-bellman-operator/src/loaded.rs",
    "use crate::TabularOperatorArtifactV1;",
    "use crate::OperatorAdmissionStageV1;\nuse crate::TabularOperatorArtifactV1;",
)
replace(
    "codex-rs/hepta-bellman-operator/src/loaded.rs",
    """impl LoadedTabularOperatorV1 {
    /// Verify a host-selected pin before decoding or permitting predictions.""",
    """impl LoadedTabularOperatorV1 {
    #[must_use]
    pub const fn admission_stage(&self) -> OperatorAdmissionStageV1 {
        OperatorAdmissionStageV1::StructurallyValidated
    }

    /// Verify a host-selected pin before decoding or permitting predictions.""",
)
replace(
    "codex-rs/hepta-bellman-operator/src/loaded.rs",
    """impl ValidatedTabularOperatorV1 {
    #[must_use]
    pub fn artifact_id""",
    """impl ValidatedTabularOperatorV1 {
    #[must_use]
    pub const fn admission_stage(&self) -> OperatorAdmissionStageV1 {
        OperatorAdmissionStageV1::StructurallyValidated
    }

    #[must_use]
    pub fn artifact_id""",
)
replace(
    "codex-rs/hepta-bellman-operator/src/loaded.rs",
    """impl LoadedTabularOperatorV2 {
    pub fn from_pinned_payload_v2""",
    """impl LoadedTabularOperatorV2 {
    #[must_use]
    pub const fn admission_stage(&self) -> OperatorAdmissionStageV1 {
        OperatorAdmissionStageV1::ImmutableCandidate
    }

    pub fn from_pinned_payload_v2""",
)

# The Agentd evaluated consumer is the selected read-only state.
replace(
    "codex-rs/hepta-agentd/src/cognitive_ranker.rs",
    "use codex_hepta_bellman_operator::TabularPayloadError;",
    "use codex_hepta_bellman_operator::OperatorAdmissionStageV1;\nuse codex_hepta_bellman_operator::TabularPayloadError;",
)
replace(
    "codex-rs/hepta-agentd/src/cognitive_ranker.rs",
    "impl PinnedCognitiveRanker {\n    #[cfg(test)]",
    """impl PinnedCognitiveRanker {
    #[must_use]
    pub fn admission_stage(&self) -> OperatorAdmissionStageV1 {
        if self.admission.is_some() {
            OperatorAdmissionStageV1::SelectedReadOnly
        } else {
            OperatorAdmissionStageV1::StructurallyValidated
        }
    }

    #[cfg(test)]""",
)

# Keep the selection/rollback enum bounded without suppressing lint.
replace(
    "codex-rs/hepta-agentd/src/cognitive_ranker_admission.rs",
    """enum Authorization {
    Selection(VerifiedSelfEvolutionSelectionV1),
    Rollback(VerifiedSelfEvolutionRollbackV1),
}""",
    """enum Authorization {
    Selection(Box<VerifiedSelfEvolutionSelectionV1>),
    Rollback(Box<VerifiedSelfEvolutionRollbackV1>),
}""",
)
replace(
    "codex-rs/hepta-agentd/src/cognitive_ranker_admission.rs",
    "Authorization::Selection(selection.clone()),",
    "Authorization::Selection(Box::new(selection.clone())),",
)
replace(
    "codex-rs/hepta-agentd/src/cognitive_ranker_admission.rs",
    "Authorization::Rollback(rollback.clone()),",
    "Authorization::Rollback(Box::new(rollback.clone())),",
)

# --- Full V3 qualification/persistence/reload profile.
replace(
    "codex-rs/hepta-bellman-operator/src/owner_dataset_tests.rs",
    "use crate::TabularOperatorSampleV1;",
    """use crate::LoadedTabularOperatorV2;
use crate::OperatorAdmissionStageV1;
use crate::TABULAR_ARTIFACT_SCHEMA_V1;
use crate::TABULAR_PAYLOAD_SCHEMA_V1;
use crate::TabularOperatorSampleV1;
use crate::TabularPayloadPinV2;
use crate::encode_tabular_payload_v1;""",
)
replace(
    "codex-rs/hepta-bellman-operator/src/owner_dataset_tests.rs",
    "use std::path::PathBuf;",
    """use std::io::Read;
use std::io::Write;
use std::path::PathBuf;""",
)
replace(
    "codex-rs/hepta-bellman-operator/src/owner_dataset_tests.rs",
    "use std::sync::atomic::Ordering;",
    "use std::sync::atomic::Ordering;\nuse std::time::Instant;",
)
owner_tests = ROOT / "codex-rs/hepta-bellman-operator/src/owner_dataset_tests.rs"
owner_text = owner_tests.read_text(encoding="utf-8")
marker = "fn full_v3_qualification_path_profile()"
if marker not in owner_text:
    owner_text += r"""

fn peak_rss_kib() -> u64 {
    fs::read_to_string("/proc/self/status")
        .ok()
        .and_then(|status| {
            status
                .lines()
                .find(|line| line.starts_with("VmHWM:"))
                .and_then(|line| line.split_whitespace().nth(1))
                .and_then(|value| value.parse().ok())
        })
        .unwrap_or(0)
}

#[test]
#[ignore = "explicit qualification performance profile"]
fn full_v3_qualification_path_profile() {
    let total = Instant::now();
    let fixture = Fixture::new();

    let started = Instant::now();
    let (receipt, freeze) = fixture.dataset();
    let freeze_us = started.elapsed().as_micros();

    let input = plan(&receipt);
    let started = Instant::now();
    let payload =
        tabular_training_signing_payload_v2(&input, &receipt, &fixture.owner).unwrap();
    let row = sign(
        &fixture.owner,
        "observer",
        2,
        LearningEvidenceRoleV1::Observer,
        &payload,
    );
    let canonicalize_and_sign_us = started.elapsed().as_micros();

    let started = Instant::now();
    let verified = verify_tabular_operator_plan_v3(
        input,
        &receipt,
        &fixture.owner,
        &freeze,
        &row,
        50,
    )
    .unwrap();
    assert_eq!(
        verified.admission_stage(),
        OperatorAdmissionStageV1::SourceAuthenticated
    );
    let owner_admission_us = started.elapsed().as_micros();

    let started = Instant::now();
    let artifact = fit_tabular_operator_verified_v3(verified, 51).unwrap();
    let fit_with_revalidation_us = started.elapsed().as_micros();

    let started = Instant::now();
    let bytes = encode_tabular_payload_v1(&artifact).unwrap();
    let encode_us = started.elapsed().as_micros();

    let payload_path = fixture.root.join("operator-payload");
    let started = Instant::now();
    let mut output = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&payload_path)
        .unwrap();
    output.write_all(&bytes).unwrap();
    output.sync_all().unwrap();
    drop(output);
    let persist_us = started.elapsed().as_micros();

    let started = Instant::now();
    let mut reopened = Vec::new();
    File::open(&payload_path)
        .unwrap()
        .read_to_end(&mut reopened)
        .unwrap();
    let pin = TabularPayloadPinV2 {
        artifact_id: artifact.artifact_id.clone(),
        producer_id: artifact.producer_id.clone(),
        artifact_schema_version: TABULAR_ARTIFACT_SCHEMA_V1,
        payload_schema_version: TABULAR_PAYLOAD_SCHEMA_V1,
        payload_digest: Digest32::of_bytes(&reopened),
        artifact_digest: artifact.artifact_digest,
        objective_digest: artifact.objective_digest,
        dataset_digest: artifact.dataset_digest,
        sensor_core_digest: artifact.sensor_core_digest,
        training_profile_digest: artifact.training_profile_digest,
        runtime_profile_digest: hash("runtime-profile"),
        trust_digest: fixture.owner.verifier().trust_digest(),
        registry_head_digest: receipt.snapshot.ledger_head_digest,
        authority_epoch: fixture.owner.verifier().authority_epoch(),
        generation: artifact.generation,
    };
    let loaded =
        LoadedTabularOperatorV2::from_pinned_payload_v2(&reopened, &pin).unwrap();
    assert_eq!(
        loaded.admission_stage(),
        OperatorAdmissionStageV1::ImmutableCandidate
    );
    let reload_us = started.elapsed().as_micros();

    let started = Instant::now();
    let prediction = loaded.predict(&id("sensor"), &id("action")).unwrap();
    let first_prediction_us = started.elapsed().as_micros();
    assert_eq!(prediction.value.raw(), 20);

    println!(
        "LEARNING_OPERATOR_FULL_PATH_PROFILE={{\"rows\":{},\"payload_bytes\":{},\"peak_rss_kib\":{},\"freeze_us\":{},\"canonicalize_and_sign_us\":{},\"owner_admission_us\":{},\"fit_with_revalidation_us\":{},\"encode_us\":{},\"persist_us\":{},\"reload_us\":{},\"first_prediction_us\":{},\"total_us\":{}}}",
        receipt.snapshot.source_record_digests.len(),
        reopened.len(),
        peak_rss_kib(),
        freeze_us,
        canonicalize_and_sign_us,
        owner_admission_us,
        fit_with_revalidation_us,
        encode_us,
        persist_us,
        reload_us,
        first_prediction_us,
        total.elapsed().as_micros(),
    );
}
"""
    owner_tests.write_text(owner_text, encoding="utf-8")

# The signed V2 primitive is authentication-gated and used by existing
# product hosts; unsigned direct comparators remain crate-private.
replace(
    "scripts/hepta_lane_e_contract.py",
    '"pub(crate) use signed_evaluation::decide_with_signed_evidence_v2;",',
    '"pub use signed_evaluation::decide_with_signed_evidence_v2;",',
)

replace(
    "codex-rs/hepta-bellman-operator/NATIVE_MAPPING.md",
    "| build deterministic Bellman targets | `build_targets` (`train` compatibility alias) | `src/lib.rs` | implemented |",
    "| classify admission stage and recovery action | `OperatorAdmissionStageV1` / `ClassifyOperatorAdmissionFailure::disposition` | `src/admission.rs` | implemented; no new authority |\n| build deterministic Bellman targets | `build_targets` (`train` compatibility alias) | `src/lib.rs` | implemented |",
)
replace(
    "codex-rs/hepta-bellman-operator/NATIVE_MAPPING.md",
    "| bind frozen dataset to tabular training | `verify_tabular_operator_plan_v2` / `fit_tabular_operator_verified_v2` | `src/dataset_bound.rs` | implemented |",
    "| bind frozen dataset to tabular training | `verify_tabular_operator_plan_v3` / `fit_tabular_operator_verified_v3` | `src/dataset_bound.rs` | owner-bound qualification implemented; V2 compatibility only |",
)
replace(
    "codex-rs/hepta-bellman-operator/NATIVE_MAPPING.md",
    "| bind frozen dataset to world-model training | `verify_world_model_dataset_v2` / `fit_transition_model_verified_v2` | `src/dataset_bound.rs` | implemented |",
    "| bind frozen dataset to world-model training | `verify_world_model_dataset_v3` / `fit_transition_model_verified_v3` | `src/dataset_bound.rs` | owner-bound qualification implemented; V2 compatibility only |",
)
replace(
    "codex-rs/hepta-bellman-operator/NATIVE_MAPPING.md",
    "`verify_tabular_operator_plan_v2` is the qualification ingress: it independently verifies a `DatasetSnapshotReceiptV3`, requires objective/dataset identity equality, and requires the sorted training evidence set to equal the frozen dataset's canonical `source_record_digests` exactly. Only its opaque `VerifiedTabularOperatorPlanV2` can enter `fit_tabular_operator_verified_v2`.",
    "`verify_tabular_operator_plan_v3` is the qualification ingress: it borrows the actual durable `LedgerWriter`, verifies the `DatasetSnapshotReceiptV3`, requires objective/dataset identity equality and the exact frozen source-record set, authenticates canonical row semantics, and returns a single-use opaque value. `fit_tabular_operator_verified_v3` repeats current-owner, expiry, revocation, and signer checks immediately before fitting. V2 wrappers remain structural compatibility inputs.",
)
replace(
    "codex-rs/hepta-bellman-operator/NATIVE_MAPPING.md",
    "`verify_world_model_dataset_v2` applies the same frozen-receipt and exact evidence-set rule to world-model rows.",
    "`verify_world_model_dataset_v3` applies the owner-bound frozen-receipt, exact evidence-set, signed-row, and final-use revalidation rules to world-model rows.",
)
replace(
    "codex-rs/hepta-bellman-operator/NATIVE_MAPPING.md",
    "All integers are big-endian; counts are bounded before allocation. The payload\nceiling is 64 MiB, the grid is at most 262,144 cells and the existing sensor,\naction and sample bounds apply.",
    "All integers are big-endian; counts are bounded before allocation. The payload\nceiling is 64 MiB, the compatibility grid is at most 262,144 cells and can\nrepresent up to 1,000,000 samples. Owner-authenticated V3 admission is separately\nbounded to 4,096 signed rows and requires `sensors × actions × minimum_samples_per_cell ≤ 4096`.",
)
replace(
    "codex-rs/hepta-bellman-operator/NATIVE_MAPPING.md",
    "- `src/world_model_tests.rs`.",
    "- `src/world_model_tests.rs`;\n- `src/owner_dataset_tests.rs` (owner-bound V3 admission and full-path profile);\n- `src/loaded_tests.rs` (immutable load and process rollback).",
)

# --- Canonical documentation entrypoints.
replace(
    "docs/modules/learning.operator/TECHNICAL.md",
    "Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.\n\n## 1. Identity, mission and ownership",
    "Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.\n\nCanonical candidate-state, failure-scope, recovery-action, and V2/V3 capacity semantics are in [ADMISSION_CONTRACT.md](ADMISSION_CONTRACT.md).\n\n## 1. Identity, mission and ownership",
)

write(
    "docs/modules/learning.operator/ADMISSION_CONTRACT.md",
    r"""
# `learning.operator` admission contract

This document is the canonical entrypoint for candidate state, failure
scope, recovery action, and qualification evidence. It describes the
existing owners; it does not introduce another runtime or authority.

## State progression

| State | Concrete representation | Meaning |
|---|---|---|
| Raw input | `TabularOperatorPlanV1`, `Vec<WorldModelSampleV1>` | Caller data only; no trust or currentness claim. |
| Structurally validated | V2 compatibility wrappers or `ValidatedTabularOperatorV1` | Shape and digest consistency only. This is not production admission. |
| Source authenticated | `VerifiedTabularOperatorPlanV3` / `VerifiedWorldModelDatasetV3` | Opaque, single-use owner borrow; exact frozen source set and signed row semantics verified. |
| Current at use | `fit_*_verified_v3` revalidation | Ledger membership, correction/revocation cuts, trust epoch, expiry, and role separation are checked again immediately before fitting. |
| Immutable candidate | `TabularPayloadPinV2` + `LoadedTabularOperatorV2` | Complete immutable identity, runtime profile, trust snapshot, epoch, and registry head are host-selected; this still does not prove evaluation or selection. |
| Independently evaluated | sealed `learning.eval` receipt and verified selection evidence | Owned by the evaluator/selector; signatures authenticate evidence but do not prove scientific efficacy. |
| Selected read-only | `PinnedCognitiveRanker::load_evaluated` | Agentd binds the independently selected artifact and revalidates registry, trust, revocation, runtime, and authorization on every read. |

`OperatorAdmissionStageV1` names these states. APIs return opaque types
at the applicable boundaries; callers must not reconstruct state from
booleans or caller-authored digests.

## Failure scope and recovery

`ClassifyOperatorAdmissionFailure` maps dataset-binding and payload
failures to `OperatorFailureDispositionV1`.

- Request-local shape, identity, evidence-set, or arithmetic failures:
  correct the request; do not retry unchanged input.
- Candidate-global model, decoder, grid, or persisted-payload failures:
  reject that candidate.
- Expired, revoked, or trust-context evidence:
  obtain fresh owner evidence and repeat admission.
- Payload-pin movement:
  reload an independently selected immutable candidate.
- Unsupported prediction cells:
  abstain for the decision; do not invalidate the entire candidate.
- Owner I/O, clock regression, or authority violation:
  stop the consumer and preserve evidence.

`OwnerDatasetFailureV1` retains the failed owner operation instead of
flattening freeze, record-read, snapshot, and canonical-payload errors
into one unstructured string.

## Capacity

The compatibility fitter can represent up to 1,000,000 rows and
262,144 cells. The owner-authenticated V3 signing path is deliberately
narrower: at most `MAX_SIGNED_OPERATOR_ROWS = 4096` rows and frozen
source records.

A signed tabular profile must satisfy, before allocation or sorting:

```text
sensor_count × action_count × minimum_samples_per_cell ≤ 4096
```

The other hard limits remain 4,096 sensors, 128 actions, and 64 MiB
persisted payload bytes.

## Performance evidence

Run the explicit end-to-end qualification-core profile:

```bash
cargo test --locked -p codex-hepta-bellman-operator \
  full_v3_qualification_path_profile -- --ignored --nocapture
```

It records dataset freeze, row canonicalization/signing, owner
admission, fit-time revalidation, encoding, create-only persistence,
reload, first prediction, total wall time, payload bytes, and process
peak RSS. These measurements are candidate/host observations, not
acceptance or future-window efficacy evidence.
""",
)

write(
    "docs/modules/learning.operator/DEVELOPER_GUIDE.md",
    r"""
# `learning.operator` developer guide

Canonical state and recovery semantics are in
[ADMISSION_CONTRACT.md](ADMISSION_CONTRACT.md).

## Production qualification sequence

1. Replay the authoritative `learning.ledger` and freeze a
   `DatasetSnapshotReceiptV3`.
2. Rebind the receipt to that replay with
   `verify_dataset_snapshot_receipt_against_ledger_v3`.
3. Construct `LearningEvidenceVerifierV1` only from host-owned trust
   configuration. Candidate input may not choose keys, roles, scope,
   objective, or authority epoch.
4. Canonically encode every training row, including row identity,
   state/sensor, action, target/outcome, next-state semantics, and
   source evidence digest.
5. Require an independent Ed25519 `Observer` attestation over those
   exact canonical bytes.
6. Call `verify_tabular_operator_plan_v3` or
   `verify_world_model_dataset_v3`. Only the opaque V3 result may reach
   the corresponding V3 fit API.
7. Revalidate current owner state immediately before fitting. Do not
   remove this second check to save time.
8. Persist create-only payload bytes and a host-selected complete
   `TabularPayloadPinV2`.
9. Independently evaluate and select the exact immutable artifact.
10. Load in a fresh process through `LoadedTabularOperatorV2` and the
    evaluated read-only Agentd consumer. Keep authority deny-all.
11. Roll back by reopening an immutable predecessor and original pin;
    never retrain or rewrite it.

V2 dataset wrappers and V1 payload pins are compatibility surfaces.
They establish structural validity only, not current owner-bound
production admission.

## Local checks

```bash
python3 scripts/hepta-lane-e-closure.py self-test
python3 scripts/hepta-lane-e-closure.py verify
python3 scripts/hepta-implementation-maps.py verify
cargo test --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-bellman-operator --locked
cargo clippy --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-bellman-operator \
  -p codex-hepta-intelligence-eval \
  -p codex-hepta-learning-ledger \
  --all-targets --locked --no-deps -- -D warnings
cargo test --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-agentd --lib cognitive_ranker::evaluated_tests \
  -- --nocapture
cargo test --manifest-path codex-rs/Cargo.toml \
  -p codex-hepta-bellman-operator \
  full_v3_qualification_path_profile --locked -- --ignored --nocapture
```

Exact-source CI executes every gate independently and publishes an
explicit pass/fail/timeout record. A failed lint gate does not silently
skip the executable tests.

## Error semantics

Use `ClassifyOperatorAdmissionFailure::disposition`; do not parse error
display strings. Request-local failures are corrected, stale evidence
is re-admitted against current owners, candidate-global failures reject
the candidate, unsupported cells abstain, and owner/clock/authority
failures stop the consumer.

## Ownership boundaries

`learning.operator` constructs deterministic qualification candidates.
It does not own the ledger, artifact registry, evaluator, selector,
activation policy, production writer, or rollback authority.
""",
)

write(
    "docs/modules/learning.operator/COMPATIBILITY_RESOURCE_AND_SHADOW_POLICY.md",
    r"""
# `learning.operator` compatibility, resource, and shadow policy

## Schema and backward compatibility

- V1 payload bytes remain decodable only while their schema is pinned.
- V1 pins and V2 dataset wrappers are structural compatibility inputs;
  neither independently authorizes promotion.
- V3 owner-bound inputs establish exact frozen-source and signed-row
  admission and are revalidated immediately before fit.
- V2 payload pins bind artifact and producer identity, artifact/payload
  schemas, runtime profile, trust snapshot, authority epoch, and
  registry head in addition to numerical digests.
- Every schema version uses a new domain separator and explicit
  decoder. Unknown versions fail closed.
- Migration is decode old → validate old → encode new → compare full
  semantics → persist create-only → independently re-evaluate.
- Downgrade reopens the original immutable predecessor and original pin.

## Resource budgets

Compatibility/storage ceilings:

- at most 1,000,000 represented training samples;
- at most 262,144 tabular cells;
- at most 4,096 sensors;
- at most 128 actions;
- at most 64 MiB persisted payload.

Owner-authenticated V3 admission is narrower:

- at most 4,096 signed rows and frozen source records;
- `sensors × actions × minimum_samples_per_cell ≤ rows ≤ 4096`.

Impossible profiles fail during allocation-free preflight. The larger
compatibility ceiling must never be presented as the V3 admission
capacity.

Qualification publishes peak resident memory, total wall time, and
stage timings for freeze, canonicalization, owner admission, fit-time
revalidation, encoding, create-only persistence, reload, and first
prediction. Structural ceilings alone are not acceptance evidence.

## Longitudinal shadow acceptance

Thresholds are preregistered before final outcomes. Promotion requires
zero identity/trust/authority violations, zero unauthorized writes,
fresh-process load and immutable rollback, stable calibration and
subgroup coverage, bounded abstention/OOD, no independently measured
utility regression, no budget breach, and restart/permutation/read
concurrency stability.

A hard-bound violation rejects the candidate. Passing shadow
acceptance authorizes only the separately declared next stage.

## Required robustness suites

The gate includes decoder fuzzing, determinism/order properties,
semantic-row mutation, trust rotation/revocation races, registry
movement, restart recovery, immutable rollback, maximum-profile
measurements, and fail-closed mutation tests. Missing or skipped
execution is reported as missing evidence, never success.
""",
)

write(
    "docs/modules/learning.operator/OPERATIONS_RUNBOOK.md",
    r"""
# `learning.operator` operations runbook

State and error semantics are defined in
[ADMISSION_CONTRACT.md](ADMISSION_CONTRACT.md).

## Trust rotation and revocation

Every selection pins the trust digest and authority epoch used for
generator, observer, evaluator, and selector evidence. Rotation creates
a new immutable trust snapshot; it never rewrites old evidence. At or
after `revoked_at`, re-verification fails and the candidate leaves the
eligible shadow set.

Trust material comes from the host authority store. Candidate payloads,
manifests, receipts, and remote callers cannot replace verifier keys,
controller mapping, scope, objective, or epoch.

## Actionable failure handling

- `CorrectRequest`: reject the unchanged request; do not busy-retry.
- `ObtainFreshOwnerEvidence`: rebuild the freeze/attestation chain
  against the current owner.
- `RejectCandidate`: quarantine the immutable candidate identity and
  preserve its evidence.
- `ReloadSelectedCandidate`: reopen the independently selected bytes and
  complete pin; never synthesize a replacement.
- `AbstainUnsupportedCell`: leave the candidate loaded and abstain for
  that decision.
- `StopConsumer`: stop reads and preserve diagnostics until explicit
  operator recovery.

Owner failures include the exact failed operation (`FreezeDataset`,
`ReadDatasetRecords`, `Snapshot`, or `EncodeFreezePayload`).

## Registry movement

Before each read-only use, verify a signed current-registry view and
exact predecessor/head binding. A stale head, generation regression,
predecessor mismatch, revocation, or unavailable witness closes the
consumer. Do not fall back while retaining learned-policy claims.

## Rollback

Reopen an already persisted immutable predecessor and its original
complete pin. Verify artifact/producer identity, generations, schemas,
runtime profile, trust digest, authority epoch, and registry head.

Success requires a fresh-process load and read-only prediction smoke
test. Failure to reopen the exact predecessor is a stop condition.

## Incident stop conditions

Stop admission and preserve evidence on ledger/source-set mismatch,
signature/controller/trust/revocation failure, row-semantics drift,
registry or immutable identity mismatch, calibration/coverage/resource
breach, missing independent evaluation/selection, or any attempted
production write by the shadow consumer.
""",
)

# Dossier: V3 is the qualification path; V2 remains compatibility only.
replace(
    "qualification/module-execution-dossiers/detail/learning.operator.md",
    """qualification APIs `validate_applicability_with_signed_evidence_v2`, `admit_operator_regularity_with_signed_evidence_v2`, `verify_tabular_operator_plan_v2 -> fit_tabular_operator_verified_v2`, and `verify_world_model_dataset_v2 -> fit_transition_model_verified_v2`; prediction APIs remain deny-all and synthetic.""",
    """qualification APIs `validate_applicability_with_signed_evidence_v2`, `admit_operator_regularity_with_signed_evidence_v2`, `verify_tabular_operator_plan_v3 -> fit_tabular_operator_verified_v3`, and `verify_world_model_dataset_v3 -> fit_transition_model_verified_v3`; V2 dataset wrappers remain structural compatibility surfaces, and prediction APIs remain deny-all and synthetic.""",
)
replace(
    "qualification/module-execution-dossiers/detail/learning.operator.md",
    """For qualification, `verify_tabular_operator_plan_v2` independently verifies the `DatasetSnapshotReceiptV3`, objective/dataset identity and exact equality between training evidence and the frozen source-record set before producing an opaque input accepted by `fit_tabular_operator_verified_v2`.""",
    """For qualification, `verify_tabular_operator_plan_v3` binds the actual durable `LedgerWriter`, independently verifies the `DatasetSnapshotReceiptV3`, objective/dataset identity, exact frozen source-record set and signed row semantics, then produces a single-use opaque input accepted by `fit_tabular_operator_verified_v3`; the fit repeats current-owner verification immediately before training.""",
)
replace(
    "qualification/module-execution-dossiers/detail/learning.operator.md",
    """Qualification uses `verify_world_model_dataset_v2` so rows are bound to the exact frozen dataset receipt before fitting.""",
    """Qualification uses `verify_world_model_dataset_v3` so rows are bound to the exact frozen dataset receipt, current owner and signed row semantics before fitting.""",
)
replace(
    "qualification/module-execution-dossiers/detail/learning.operator.md",
    """The tabular grid is bounded to 262144 cells and its training rows to 1000000.""",
    """The persisted/compatibility tabular grid is bounded to 262144 cells and 1000000 represented samples; the owner-authenticated V3 signing path is separately bounded to 4096 rows and requires `sensors × actions × minimum_samples_per_cell ≤ 4096`.""",
)
replace(
    "qualification/module-execution-dossiers/detail/learning.operator.md",
    """- OP-06: qualification fitting consumes an exact self-verifying frozen dataset receipt; persisted candidates require an independent pin and separate-process reload/rollback behavior.""",
    """- OP-06: V3 qualification fitting consumes an exact self-verifying frozen dataset receipt, current owner and signed row semantics; persisted candidates require an independent complete pin and separate-process reload/rollback behavior.""",
)
replace(
    "qualification/module-execution-dossiers/detail/learning.operator.md",
    """- **Implemented entrypoints:** `build_targets` in [src/lib.rs](../../../codex-rs/hepta-bellman-operator/src/lib.rs);""",
    """- **Implemented entrypoints:** typed stage/failure classification in [src/admission.rs](../../../codex-rs/hepta-bellman-operator/src/admission.rs); `build_targets` in [src/lib.rs](../../../codex-rs/hepta-bellman-operator/src/lib.rs);""",
)
replace(
    "qualification/module-execution-dossiers/detail/learning.operator.md",
    """[dataset_bound_tests.rs](../../../codex-rs/hepta-bellman-operator/src/dataset_bound_tests.rs) and [loaded_tests.rs]""",
    """[dataset_bound_tests.rs](../../../codex-rs/hepta-bellman-operator/src/dataset_bound_tests.rs), [owner_dataset_tests.rs](../../../codex-rs/hepta-bellman-operator/src/owner_dataset_tests.rs) and [loaded_tests.rs]""",
)

# Keep the public admission/recovery surface in the implementation map.
operator_map_path = ROOT / "docs/modules/learning.operator/IMPLEMENTATION_MAP.json"
operator_map = json.loads(operator_map_path.read_text(encoding="utf-8"))
if not any(
    operation.get("operation") == "classify_operator_admission_failure"
    for operation in operator_map.get("operations", [])
):
    operator_map["operations"].insert(
        1,
        {
            "operation": "classify_operator_admission_failure",
            "designOperation": "classify_operator_admission_failure",
            "nativeSymbol": "ClassifyOperatorAdmissionFailure::disposition",
            "sourcePath": "codex-rs/hepta-bellman-operator/src/admission.rs",
            "mappingClass": "owner_native",
            "delegatedCallees": [],
            "tests": [
                "codex-rs/hepta-bellman-operator/src/admission.rs::unsupported_cells_abstain_without_invalidating_the_candidate",
                "codex-rs/hepta-bellman-operator/src/admission.rs::revoked_evidence_requires_fresh_owner_admission",
            ],
            "state": "source_implemented_not_default_product_loop_composed",
            "authority": "none",
            "sourcePathExists": True,
        },
    )
operator_map_path.write_text(
    json.dumps(operator_map, indent=2, sort_keys=False) + "\n",
    encoding="utf-8",
)

# Static status files never impersonate exact-head execution receipts.
stale_status = ROOT / "qualification/lane-e/latest-verify.json"
if stale_status.exists():
    stale_status.unlink()

write(
    "qualification/lane-e/LEARNING_OPERATOR_STATUS.md",
    r"""
# `learning.operator` evidence status

The repository distinguishes three facts:

1. **Mapped source/test identity** — a function or test exists and is
   connected to a requirement.
2. **Candidate execution** — a literal command ran for an exact SHA/tree
   and ended in pass, fail, or timeout.
3. **External acceptance** — independent efficacy, target-host,
   promotion, canary, and release evidence.

No tracked file is called “latest” or treated as an execution receipt.
The `Learning operator exact-source diagnostics` workflow emits
`status.json` in each diagnostic artifact. Every record contains the
exact candidate SHA/tree, environment, command, duration, terminal
state, and log filenames. Commands are executed independently, so an
earlier lint failure cannot turn later tests into silent skips.

Artifact families:

- `learning-operator-source-<sha>`
- `learning-operator-rust-<sha>`
- `learning-operator-merge-<sha>-<base>`

A missing artifact or command record is missing evidence, not success.
The performance profile is diagnostic evidence only; it is not
independent acceptance.
""",
)

write(
    "qualification/lane-e/learning-operator-status.schema.json",
    json.dumps(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "hepta.learning-operator-gate-status.v1",
            "title": "learning.operator exact-candidate gate status",
            "type": "object",
            "additionalProperties": False,
            "required": [
                "schema",
                "candidate",
                "environment",
                "gates",
                "overall",
                "externalAcceptanceIncluded",
            ],
            "properties": {
                "schema": {
                    "const": "hepta.learning-operator-gate-status.v1",
                },
                "candidate": {
                    "type": "object",
                    "oneOf": [
                        {
                            "required": ["sha", "tree"],
                            "properties": {
                                "sha": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
                                "tree": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
                            },
                        },
                        {
                            "required": [
                                "sourceSha",
                                "baseSha",
                                "mergeSha",
                                "mergeTree",
                            ],
                            "properties": {
                                "sourceSha": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
                                "baseSha": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
                                "mergeSha": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
                                "mergeTree": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
                            },
                        },
                    ],
                },
                "environment": {"type": "object"},
                "gates": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": [
                            "id",
                            "command",
                            "state",
                            "durationMs",
                            "stdout",
                            "stderr",
                        ],
                        "properties": {
                            "id": {"type": "string"},
                            "command": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "state": {
                                "enum": ["pass", "fail", "timeout"],
                            },
                            "exitCode": {
                                "type": ["integer", "null"],
                            },
                            "durationMs": {
                                "type": "integer",
                                "minimum": 0,
                            },
                            "stdout": {"type": "string"},
                            "stderr": {"type": "string"},
                        },
                    },
                },
                "overall": {"enum": ["pass", "fail"]},
                "externalAcceptanceIncluded": {"const": False},
            },
        },
        indent=2,
        sort_keys=True,
    ),
)

# Exact-source and merge diagnostics execute every gate independently.
write(
    ".github/workflows/learning-operator-diagnostics.yml",
    r"""
name: Learning operator exact-source diagnostics

on:
  pull_request:
    branches: [main]
    paths: &learning_operator_paths
      - '.github/workflows/learning-operator-diagnostics.yml'
      - 'scripts/hepta*'
      - 'codex-rs/hepta-*/**'
      - 'docs/lane-e/**'
      - 'docs/modules/learning.operator/**'
      - 'docs/modules/learning.eval/**'
      - 'qualification/lane-e/**'
  push:
    branches: [codex/learning-operator-full-convergence-20260926]
    paths: *learning_operator_paths
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: learning-operator-diagnostics-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true

env:
  SOURCE_SHA: ${{ github.event.pull_request.head.sha || github.sha }}
  EXPECTED_BASE_SHA: a126987b84737dbc2ee2592442a314117bddb4a2

jobs:
  source:
    runs-on: ubuntu-24.04
    timeout-minutes: 25
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
        with:
          ref: ${{ env.SOURCE_SHA }}
          fetch-depth: 0
          persist-credentials: false
      - name: Execute every source gate and record terminal state
        shell: bash
        run: |
          set -euo pipefail
          mkdir -p "$RUNNER_TEMP/operator-source"
          python3 - <<'PY'
          import json
          import os
          import pathlib
          import platform
          import subprocess
          import sys
          import time

          root = pathlib.Path(os.environ["RUNNER_TEMP"]) / "operator-source"
          sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
          tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], text=True).strip()
          if sha != os.environ["SOURCE_SHA"]:
              raise SystemExit("checkout/source SHA mismatch")
          commands = [
              ("dossiers", ["python3", "scripts/hepta-implementation-dossiers.py", "verify"]),
              ("closure-self-test", ["python3", "scripts/hepta-lane-e-closure.py", "self-test"]),
              ("closure-verify", ["python3", "scripts/hepta-lane-e-closure.py", "verify"]),
              (
                  "implementation-maps",
                  [
                      "python3",
                      "scripts/hepta-implementation-maps.py",
                      "verify",
                      "--expected-sha",
                      sha,
                      "--expected-tree",
                      tree,
                  ],
              ),
              ("clean-tree", ["git", "diff", "--exit-code"]),
          ]
          gates = []
          for gate_id, command in commands:
              started = time.monotonic()
              try:
                  result = subprocess.run(
                      command,
                      capture_output=True,
                      text=True,
                      timeout=300,
                      check=False,
                  )
                  state = "pass" if result.returncode == 0 else "fail"
                  exit_code = result.returncode
                  stdout = result.stdout
                  stderr = result.stderr
              except subprocess.TimeoutExpired as error:
                  state = "timeout"
                  exit_code = None
                  stdout = error.stdout or ""
                  stderr = error.stderr or ""
              (root / f"{gate_id}.stdout.log").write_text(stdout)
              (root / f"{gate_id}.stderr.log").write_text(stderr)
              print(f"[{state}] {' '.join(command)}", flush=True)
              print(stdout, flush=True)
              print(stderr, file=sys.stderr, flush=True)
              gates.append(
                  {
                      "id": gate_id,
                      "command": command,
                      "state": state,
                      "exitCode": exit_code,
                      "durationMs": round((time.monotonic() - started) * 1000),
                      "stdout": f"{gate_id}.stdout.log",
                      "stderr": f"{gate_id}.stderr.log",
                  }
              )
          status = {
              "schema": "hepta.learning-operator-gate-status.v1",
              "candidate": {"sha": sha, "tree": tree},
              "environment": {
                  "runnerOs": platform.platform(),
                  "python": sys.version,
              },
              "gates": gates,
              "overall": "pass" if all(gate["state"] == "pass" for gate in gates) else "fail",
              "externalAcceptanceIncluded": False,
          }
          (root / "status.json").write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
          raise SystemExit(status["overall"] != "pass")
          PY
      - name: Upload exact-source evidence
        if: always()
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: learning-operator-source-${{ env.SOURCE_SHA }}
          path: ${{ runner.temp }}/operator-source/
          if-no-files-found: error
          retention-days: 14

  rust:
    runs-on: ubuntu-24.04
    timeout-minutes: 110
    env:
      CARGO_BUILD_JOBS: 2
      CARGO_PROFILE_DEV_DEBUG: 0
      CARGO_PROFILE_TEST_DEBUG: 0
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
        with:
          ref: ${{ env.SOURCE_SHA }}
          persist-credentials: false
      - name: Install pinned Rust toolchain
        shell: bash
        run: |
          set -euo pipefail
          rustup toolchain install 1.95.0 --profile minimal --component rustfmt --component clippy
          rustup override set 1.95.0
      - name: Execute every Rust gate and record terminal state
        shell: bash
        run: |
          set -euo pipefail
          mkdir -p "$RUNNER_TEMP/operator-rust"
          python3 - <<'PY'
          import json
          import os
          import pathlib
          import platform
          import re
          import subprocess
          import sys
          import time

          root = pathlib.Path(os.environ["RUNNER_TEMP"]) / "operator-rust"
          cwd = pathlib.Path("codex-rs")
          sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
          tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], text=True).strip()
          toolchain = subprocess.check_output(["rustc", "--version", "--verbose"], text=True)
          commands = [
              (
                  "fmt",
                  [
                      "cargo", "fmt",
                      "-p", "codex-hepta-bellman-operator",
                      "-p", "codex-hepta-intelligence-eval",
                      "-p", "codex-hepta-agentd",
                      "-p", "codex-hepta-learning-ledger",
                      "--", "--check",
                  ],
                  None,
              ),
              (
                  "clippy-learning-core",
                  [
                      "cargo", "clippy", "--locked", "--no-deps",
                      "-p", "codex-hepta-bellman-operator",
                      "-p", "codex-hepta-intelligence-eval",
                      "-p", "codex-hepta-learning-ledger",
                      "--all-targets", "--", "-D", "warnings",
                  ],
                  None,
              ),
              (
                  "operator-eval-tests",
                  [
                      "cargo", "test", "--locked",
                      "-p", "codex-hepta-bellman-operator",
                      "-p", "codex-hepta-intelligence-eval",
                  ],
                  r"test result: ok\.",
              ),
              (
                  "agentd-evaluated-consumer",
                  [
                      "cargo", "test", "--locked",
                      "-p", "codex-hepta-agentd", "--lib",
                      "cognitive_ranker::evaluated_tests", "--", "--nocapture",
                  ],
                  r"test result: ok\. [1-9][0-9]* passed; 0 failed",
              ),
              (
                  "owner-loop-recovery",
                  [
                      "cargo", "test", "--locked",
                      "-p", "codex-hepta-agentd",
                      "--test", "terminal_cell_owner", "--", "--nocapture",
                  ],
                  r"test result: ok\.",
              ),
              (
                  "owner-resource-profile",
                  [
                      "cargo", "test", "--locked",
                      "-p", "codex-hepta-agentd",
                      "--test", "terminal_cell_owner",
                      "durable_owner_history_and_concurrent_training_profile",
                      "--", "--ignored", "--nocapture",
                  ],
                  r"OWNER_HISTORY_PROFILE",
              ),
              (
                  "operator-full-path-profile",
                  [
                      "cargo", "test", "--locked",
                      "-p", "codex-hepta-bellman-operator",
                      "full_v3_qualification_path_profile",
                      "--", "--ignored", "--nocapture",
                  ],
                  r"LEARNING_OPERATOR_FULL_PATH_PROFILE=",
              ),
          ]
          gates = []
          for gate_id, command, required_pattern in commands:
              started = time.monotonic()
              try:
                  result = subprocess.run(
                      command,
                      cwd=cwd,
                      capture_output=True,
                      text=True,
                      timeout=1800,
                      check=False,
                  )
                  output = result.stdout + result.stderr
                  passed = result.returncode == 0 and (
                      required_pattern is None or re.search(required_pattern, output)
                  )
                  state = "pass" if passed else "fail"
                  exit_code = result.returncode
                  stdout = result.stdout
                  stderr = result.stderr
              except subprocess.TimeoutExpired as error:
                  state = "timeout"
                  exit_code = None
                  stdout = error.stdout or ""
                  stderr = error.stderr or ""
              (root / f"{gate_id}.stdout.log").write_text(stdout)
              (root / f"{gate_id}.stderr.log").write_text(stderr)
              print(f"[{state}] {' '.join(command)}", flush=True)
              print(stdout, flush=True)
              print(stderr, file=sys.stderr, flush=True)
              gates.append(
                  {
                      "id": gate_id,
                      "command": command,
                      "state": state,
                      "exitCode": exit_code,
                      "durationMs": round((time.monotonic() - started) * 1000),
                      "requiredPattern": required_pattern,
                      "stdout": f"{gate_id}.stdout.log",
                      "stderr": f"{gate_id}.stderr.log",
                  }
              )
          status = {
              "schema": "hepta.learning-operator-gate-status.v1",
              "candidate": {"sha": sha, "tree": tree},
              "environment": {
                  "runnerOs": platform.platform(),
                  "rustc": toolchain,
              },
              "gates": gates,
              "overall": "pass" if all(gate["state"] == "pass" for gate in gates) else "fail",
              "externalAcceptanceIncluded": False,
          }
          (root / "status.json").write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
          raise SystemExit(status["overall"] != "pass")
          PY
      - name: Upload exact-source Rust evidence
        if: always()
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: learning-operator-rust-${{ env.SOURCE_SHA }}
          path: ${{ runner.temp }}/operator-rust/
          if-no-files-found: error
          retention-days: 14

  merge-candidate:
    runs-on: ubuntu-24.04
    timeout-minutes: 110
    env:
      CARGO_BUILD_JOBS: 2
      CARGO_PROFILE_DEV_DEBUG: 0
      CARGO_PROFILE_TEST_DEBUG: 0
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd
        with:
          ref: ${{ env.SOURCE_SHA }}
          fetch-depth: 0
          persist-credentials: false
      - name: Install pinned Rust toolchain
        shell: bash
        run: |
          set -euo pipefail
          rustup toolchain install 1.95.0 --profile minimal --component rustfmt --component clippy
          rustup override set 1.95.0
      - name: Materialize fixed-base merge
        shell: bash
        run: |
          set -euo pipefail
          mkdir -p "$RUNNER_TEMP/operator-merge"
          test "$(git rev-parse HEAD)" = "$SOURCE_SHA"
          git cat-file -e "$EXPECTED_BASE_SHA^{commit}"
          printf '%s\n' "$SOURCE_SHA" > "$RUNNER_TEMP/operator-merge/source-sha.txt"
          printf '%s\n' "$EXPECTED_BASE_SHA" > "$RUNNER_TEMP/operator-merge/base-sha.txt"
          git config user.name learning-operator-ci
          git config user.email learning-operator-ci@users.noreply.github.com
          git checkout -B learning-operator-fixed-merge "$EXPECTED_BASE_SHA"
          git merge --no-ff --no-commit "$SOURCE_SHA"
          git diff --check "$EXPECTED_BASE_SHA" --
          git commit -m "ci: materialize learning.operator fixed-base merge"
          git rev-parse HEAD > "$RUNNER_TEMP/operator-merge/merge-sha.txt"
          git rev-parse HEAD^{tree} > "$RUNNER_TEMP/operator-merge/merge-tree.txt"
      - name: Execute every merge gate and record terminal state
        shell: bash
        run: |
          set -euo pipefail
          python3 - <<'PY'
          import json
          import os
          import pathlib
          import platform
          import re
          import subprocess
          import sys
          import time

          root = pathlib.Path(os.environ["RUNNER_TEMP"]) / "operator-merge"
          cwd = pathlib.Path("codex-rs")
          repo = pathlib.Path(".")
          merge_sha = (root / "merge-sha.txt").read_text().strip()
          merge_tree = (root / "merge-tree.txt").read_text().strip()
          commands = [
              (
                  "dossiers",
                  ["python3", "scripts/hepta-implementation-dossiers.py", "verify"],
                  None,
                  repo,
              ),
              (
                  "closure-self-test",
                  ["python3", "scripts/hepta-lane-e-closure.py", "self-test"],
                  None,
                  repo,
              ),
              (
                  "closure-verify",
                  ["python3", "scripts/hepta-lane-e-closure.py", "verify"],
                  None,
                  repo,
              ),
              (
                  "implementation-maps",
                  [
                      "python3",
                      "scripts/hepta-implementation-maps.py",
                      "verify",
                      "--expected-sha",
                      merge_sha,
                      "--expected-tree",
                      merge_tree,
                  ],
                  None,
                  repo,
              ),
              (
                  "clean-tree",
                  ["git", "diff", "--exit-code"],
                  None,
                  repo,
              ),
              (
                  "fmt",
                  [
                      "cargo", "fmt",
                      "-p", "codex-hepta-bellman-operator",
                      "-p", "codex-hepta-intelligence-eval",
                      "-p", "codex-hepta-agentd",
                      "-p", "codex-hepta-learning-ledger",
                      "--", "--check",
                  ],
                  None,
              ),
              (
                  "clippy-learning-core",
                  [
                      "cargo", "clippy", "--locked", "--no-deps",
                      "-p", "codex-hepta-bellman-operator",
                      "-p", "codex-hepta-intelligence-eval",
                      "-p", "codex-hepta-learning-ledger",
                      "--all-targets", "--", "-D", "warnings",
                  ],
                  None,
              ),
              (
                  "operator-eval-tests",
                  [
                      "cargo", "test", "--locked",
                      "-p", "codex-hepta-bellman-operator",
                      "-p", "codex-hepta-intelligence-eval",
                  ],
                  r"test result: ok\.",
              ),
              (
                  "agentd-evaluated-consumer",
                  [
                      "cargo", "test", "--locked",
                      "-p", "codex-hepta-agentd", "--lib",
                      "cognitive_ranker::evaluated_tests", "--", "--nocapture",
                  ],
                  r"test result: ok\. [1-9][0-9]* passed; 0 failed",
              ),
              (
                  "owner-loop-recovery",
                  [
                      "cargo", "test", "--locked",
                      "-p", "codex-hepta-agentd",
                      "--test", "terminal_cell_owner", "--", "--nocapture",
                  ],
                  r"test result: ok\.",
              ),
              (
                  "operator-full-path-profile",
                  [
                      "cargo", "test", "--locked",
                      "-p", "codex-hepta-bellman-operator",
                      "full_v3_qualification_path_profile",
                      "--", "--ignored", "--nocapture",
                  ],
                  r"LEARNING_OPERATOR_FULL_PATH_PROFILE=",
              ),
          ]
          gates = []
          for record in commands:
              gate_id, command, required_pattern, *working_directories = record
              command_cwd = working_directories[0] if working_directories else cwd
              started = time.monotonic()
              try:
                  result = subprocess.run(
                      command,
                      cwd=command_cwd,
                      capture_output=True,
                      text=True,
                      timeout=1800,
                      check=False,
                  )
                  output = result.stdout + result.stderr
                  passed = result.returncode == 0 and (
                      required_pattern is None or re.search(required_pattern, output)
                  )
                  state = "pass" if passed else "fail"
                  exit_code = result.returncode
                  stdout = result.stdout
                  stderr = result.stderr
              except subprocess.TimeoutExpired as error:
                  state = "timeout"
                  exit_code = None
                  stdout = error.stdout or ""
                  stderr = error.stderr or ""
              (root / f"{gate_id}.stdout.log").write_text(stdout)
              (root / f"{gate_id}.stderr.log").write_text(stderr)
              print(f"[{state}] {' '.join(command)}", flush=True)
              print(stdout, flush=True)
              print(stderr, file=sys.stderr, flush=True)
              gates.append(
                  {
                      "id": gate_id,
                      "command": command,
                      "state": state,
                      "exitCode": exit_code,
                      "durationMs": round((time.monotonic() - started) * 1000),
                      "requiredPattern": required_pattern,
                      "stdout": f"{gate_id}.stdout.log",
                      "stderr": f"{gate_id}.stderr.log",
                  }
              )
          status = {
              "schema": "hepta.learning-operator-gate-status.v1",
              "candidate": {
                  "sourceSha": os.environ["SOURCE_SHA"],
                  "baseSha": os.environ["EXPECTED_BASE_SHA"],
                  "mergeSha": merge_sha,
                  "mergeTree": merge_tree,
              },
              "environment": {"runnerOs": platform.platform()},
              "gates": gates,
              "overall": "pass" if all(gate["state"] == "pass" for gate in gates) else "fail",
              "externalAcceptanceIncluded": False,
          }
          (root / "status.json").write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
          raise SystemExit(status["overall"] != "pass")
          PY
      - name: Upload fixed-base merge evidence
        if: always()
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: learning-operator-merge-${{ env.SOURCE_SHA }}-${{ env.EXPECTED_BASE_SHA }}
          path: ${{ runner.temp }}/operator-merge/
          if-no-files-found: error
          retention-days: 14
""",
)

# Disable this one-shot materializer in the source commit it creates.
write(
    ".github/workflows/learning-operator-remediation.yml",
    r"""
name: Learning operator remediation materializer (completed)
on:
  workflow_dispatch:
permissions:
  contents: read
jobs:
  completed:
    runs-on: ubuntu-24.04
    steps:
      - run: echo "The remediation was materialized; use the exact-source diagnostics workflow."
""",
)

# Remove the one-shot patch program from the committed source candidate.
materializer = ROOT / "scripts/learning_operator_remediation.py"
if materializer.exists():
    materializer.unlink()
