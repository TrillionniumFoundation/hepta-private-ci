#!/usr/bin/env python3
"""One-shot learning.operator owner-failure classification follow-up."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text()
    if old not in text:
        raise SystemExit(f"missing expected block in {path}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1))


def insert_before(path: str, marker: str, addition: str) -> None:
    target = ROOT / path
    text = target.read_text()
    if marker not in text:
        raise SystemExit(f"missing insertion marker in {path}: {marker!r}")
    target.write_text(text.replace(marker, addition + marker, 1))


replace(
    "codex-rs/hepta-bellman-operator/src/dataset_bound.rs",
    "use std::fmt;\n",
    "use std::fmt;\nuse std::io;\n",
)
replace(
    "codex-rs/hepta-bellman-operator/src/dataset_bound.rs",
    "use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;\n"
    "use codex_hepta_learning_ledger::LearningEvidenceRoleV1;\n"
    "use codex_hepta_learning_ledger::LedgerWriter;\n",
    "use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;\n"
    "use codex_hepta_learning_ledger::DurableLedgerError;\n"
    "use codex_hepta_learning_ledger::LearningEvidenceRoleV1;\n"
    "use codex_hepta_learning_ledger::LedgerWriter;\n"
    "use codex_hepta_learning_ledger::ProductionLedgerError;\n",
)
replace(
    "codex-rs/hepta-bellman-operator/src/dataset_bound.rs",
    "#[derive(Clone, Debug, Eq, PartialEq)]\n"
    "pub struct OwnerDatasetFailureV1 {\n"
    "    pub operation: OwnerDatasetOperationV1,\n"
    "    pub message: String,\n"
    "}\n\n"
    "impl fmt::Display for OwnerDatasetFailureV1 {\n"
    "    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {\n"
    "        write!(formatter, \"{:?}: {}\", self.operation, self.message)\n"
    "    }\n"
    "}\n"
    "impl StdError for OwnerDatasetFailureV1 {}\n\n"
    "fn owner_failure(\n"
    "    operation: OwnerDatasetOperationV1,\n"
    "    error: impl fmt::Display,\n"
    ") -> OperatorDatasetBindingError {\n"
    "    OperatorDatasetBindingError::Owner(OwnerDatasetFailureV1 {\n"
    "        operation,\n"
    "        message: error.to_string(),\n"
    "    })\n"
    "}\n",
    "#[derive(Clone, Copy, Debug, Eq, PartialEq)]\n"
    "pub enum OwnerDatasetFailureKindV1 {\n"
    "    TemporarilyUnavailable,\n"
    "    StopRequired,\n"
    "}\n\n"
    "#[derive(Clone, Debug, Eq, PartialEq)]\n"
    "pub struct OwnerDatasetFailureV1 {\n"
    "    pub operation: OwnerDatasetOperationV1,\n"
    "    pub kind: OwnerDatasetFailureKindV1,\n"
    "    pub message: String,\n"
    "}\n\n"
    "impl fmt::Display for OwnerDatasetFailureV1 {\n"
    "    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {\n"
    "        write!(\n"
    "            formatter,\n"
    "            \"{:?}/{:?}: {}\",\n"
    "            self.operation, self.kind, self.message\n"
    "        )\n"
    "    }\n"
    "}\n"
    "impl StdError for OwnerDatasetFailureV1 {}\n\n"
    "fn durable_owner_failure_is_retryable(error: &DurableLedgerError) -> bool {\n"
    "    match error {\n"
    "        DurableLedgerError::Busy => true,\n"
    "        DurableLedgerError::Io(kind) => matches!(\n"
    "            kind,\n"
    "            io::ErrorKind::Interrupted | io::ErrorKind::WouldBlock | io::ErrorKind::TimedOut\n"
    "        ),\n"
    "        DurableLedgerError::InvalidBinding\n"
    "        | DurableLedgerError::InvalidLimit\n"
    "        | DurableLedgerError::InvalidAnchor\n"
    "        | DurableLedgerError::NotRegular\n"
    "        | DurableLedgerError::NotDirectory\n"
    "        | DurableLedgerError::AlreadyInitialized\n"
    "        | DurableLedgerError::MissingHeader\n"
    "        | DurableLedgerError::BindingMismatch\n"
    "        | DurableLedgerError::AcknowledgedHistoryMissing\n"
    "        | DurableLedgerError::AnchorMismatch\n"
    "        | DurableLedgerError::IncompleteTail\n"
    "        | DurableLedgerError::UnwitnessedTail\n"
    "        | DurableLedgerError::Corrupt\n"
    "        | DurableLedgerError::Conflict\n"
    "        | DurableLedgerError::Capacity\n"
    "        | DurableLedgerError::Indeterminate\n"
    "        | DurableLedgerError::Poisoned\n"
    "        | DurableLedgerError::Semantic(_) => false,\n"
    "    }\n"
    "}\n\n"
    "fn owner_failure(\n"
    "    operation: OwnerDatasetOperationV1,\n"
    "    error: ProductionLedgerError,\n"
    ") -> OperatorDatasetBindingError {\n"
    "    match error {\n"
    "        ProductionLedgerError::Evidence(error) => {\n"
    "            OperatorDatasetBindingError::SignedEvidence(error)\n"
    "        }\n"
    "        ProductionLedgerError::Dataset(error) => {\n"
    "            OperatorDatasetBindingError::DatasetReceipt(error)\n"
    "        }\n"
    "        ProductionLedgerError::Durable(error)\n"
    "            if durable_owner_failure_is_retryable(&error) =>\n"
    "        {\n"
    "            OperatorDatasetBindingError::Owner(OwnerDatasetFailureV1 {\n"
    "                operation,\n"
    "                kind: OwnerDatasetFailureKindV1::TemporarilyUnavailable,\n"
    "                message: ProductionLedgerError::Durable(error).to_string(),\n"
    "            })\n"
    "        }\n"
    "        error => OperatorDatasetBindingError::Owner(OwnerDatasetFailureV1 {\n"
    "            operation,\n"
    "            kind: OwnerDatasetFailureKindV1::StopRequired,\n"
    "            message: error.to_string(),\n"
    "        }),\n"
    "    }\n"
    "}\n",
)

insert_before(
    "codex-rs/hepta-bellman-operator/src/dataset_bound.rs",
    "#[cfg(test)]\n#[path = \"owner_dataset_tests.rs\"]\nmod owner_tests;\n",
    "#[cfg(test)]\nmod owner_failure_tests {\n"
    "    use super::*;\n\n"
    "    #[test]\n"
    "    fn owner_evidence_failure_keeps_signed_evidence_semantics() {\n"
    "        assert!(matches!(\n"
    "            owner_failure(\n"
    "                OwnerDatasetOperationV1::FreezeDataset,\n"
    "                ProductionLedgerError::Evidence(SignedEvidenceError::Revoked),\n"
    "            ),\n"
    "            OperatorDatasetBindingError::SignedEvidence(SignedEvidenceError::Revoked)\n"
    "        ));\n"
    "    }\n\n"
    "    #[test]\n"
    "    fn busy_owner_is_typed_as_temporarily_unavailable() {\n"
    "        let OperatorDatasetBindingError::Owner(failure) = owner_failure(\n"
    "            OwnerDatasetOperationV1::ReadDatasetRecords,\n"
    "            ProductionLedgerError::Durable(DurableLedgerError::Busy),\n"
    "        ) else {\n"
    "            panic!(\"expected owner failure\");\n"
    "        };\n"
    "        assert_eq!(\n"
    "            failure.kind,\n"
    "            OwnerDatasetFailureKindV1::TemporarilyUnavailable\n"
    "        );\n"
    "    }\n"
    "}\n\n",
)

replace(
    "codex-rs/hepta-bellman-operator/src/admission.rs",
    "use crate::OperatorDatasetBindingError;\n",
    "use crate::OperatorDatasetBindingError;\nuse crate::OwnerDatasetFailureKindV1;\n",
)
replace(
    "codex-rs/hepta-bellman-operator/src/admission.rs",
    "    ReloadSelectedCandidate,\n"
    "    AbstainUnsupportedCell,\n"
    "    StopConsumer,\n",
    "    ReloadSelectedCandidate,\n"
    "    RetryWhenOwnerAvailable,\n"
    "    AbstainUnsupportedCell,\n"
    "    StopConsumer,\n",
)
replace(
    "codex-rs/hepta-bellman-operator/src/admission.rs",
    "            Self::ClockRegression | Self::Owner(_) => OperatorFailureDispositionV1 {\n"
    "                scope: Scope::Consumer,\n"
    "                action: Action::StopConsumer,\n"
    "            },\n",
    "            Self::ClockRegression => OperatorFailureDispositionV1 {\n"
    "                scope: Scope::Consumer,\n"
    "                action: Action::StopConsumer,\n"
    "            },\n"
    "            Self::Owner(error) => match error.kind {\n"
    "                OwnerDatasetFailureKindV1::TemporarilyUnavailable => {\n"
    "                    OperatorFailureDispositionV1 {\n"
    "                        scope: Scope::Consumer,\n"
    "                        action: Action::RetryWhenOwnerAvailable,\n"
    "                    }\n"
    "                }\n"
    "                OwnerDatasetFailureKindV1::StopRequired => {\n"
    "                    OperatorFailureDispositionV1 {\n"
    "                        scope: Scope::Consumer,\n"
    "                        action: Action::StopConsumer,\n"
    "                    }\n"
    "                }\n"
    "            },\n",
)
insert_before(
    "codex-rs/hepta-bellman-operator/src/admission.rs",
    "    #[test]\n    fn revoked_evidence_requires_fresh_owner_admission() {\n",
    "    #[test]\n"
    "    fn temporarily_unavailable_owner_is_retryable_without_reconstructing_admission() {\n"
    "        let failure = OperatorDatasetBindingError::Owner(crate::OwnerDatasetFailureV1 {\n"
    "            operation: crate::OwnerDatasetOperationV1::Snapshot,\n"
    "            kind: OwnerDatasetFailureKindV1::TemporarilyUnavailable,\n"
    "            message: \"Busy\".into(),\n"
    "        });\n"
    "        assert_eq!(\n"
    "            failure.disposition(),\n"
    "            OperatorFailureDispositionV1 {\n"
    "                scope: OperatorFailureScopeV1::Consumer,\n"
    "                action: OperatorRecoveryActionV1::RetryWhenOwnerAvailable,\n"
    "            }\n"
    "        );\n"
    "    }\n\n"
    "    #[test]\n"
    "    fn owner_integrity_failure_stops_the_consumer() {\n"
    "        let failure = OperatorDatasetBindingError::Owner(crate::OwnerDatasetFailureV1 {\n"
    "            operation: crate::OwnerDatasetOperationV1::Snapshot,\n"
    "            kind: OwnerDatasetFailureKindV1::StopRequired,\n"
    "            message: \"Corrupt\".into(),\n"
    "        });\n"
    "        assert!(failure.disposition().stops_consumer());\n"
    "    }\n\n",
)

replace(
    "codex-rs/hepta-bellman-operator/src/lib.rs",
    "pub use dataset_bound::OwnerDatasetFailureV1;\n",
    "pub use dataset_bound::OwnerDatasetFailureKindV1;\n"
    "pub use dataset_bound::OwnerDatasetFailureV1;\n",
)

replace(
    "docs/modules/learning.operator/ADMISSION_CONTRACT.md",
    "- Owner I/O, clock regression, or authority violation:\n"
    "  stop the consumer and preserve evidence.\n",
    "- Owner `Busy`, `WouldBlock`, `Interrupted`, or `TimedOut` failures:\n"
    "  retry only after the authoritative owner is available; retain the opaque\n"
    "  admission value and repeat current-at-use validation.\n"
    "- Owner integrity, clock regression, indeterminate persistence, or authority\n"
    "  violation: stop the consumer and preserve evidence.\n",
)
replace(
    "docs/modules/learning.operator/ADMISSION_CONTRACT.md",
    "`OwnerDatasetFailureV1` retains the failed owner operation instead of\n"
    "flattening freeze, record-read, snapshot, and canonical-payload errors\n"
    "into one unstructured string.\n",
    "`OwnerDatasetFailureV1` retains the failed owner operation and typed\n"
    "availability class instead of flattening freeze, record-read, snapshot,\n"
    "and canonical-payload errors into one unstructured string. Embedded owner\n"
    "evidence and dataset errors are restored to their original structured\n"
    "variants before recovery classification.\n",
)
replace(
    "docs/modules/learning.operator/DEVELOPER_GUIDE.md",
    "candidate-global failures reject\n"
    "the candidate, unsupported cells abstain, and owner/clock/authority\n"
    "failures stop the consumer.\n",
    "candidate-global failures reject\n"
    "the candidate, unsupported cells abstain, typed transient owner\n"
    "availability failures retry only after owner recovery, and\n"
    "integrity/clock/authority failures stop the consumer.\n",
)
replace(
    "qualification/module-execution-dossiers/detail/learning.operator.md",
    "- OP-05: canonical tabular fitting is deterministic and complete-grid, and both default and strict V2 admission reject relabelled duplicate evidence.\n",
    "- OP-05: canonical tabular fitting is deterministic and complete-grid, and the compatibility fitters reject relabelled duplicate evidence.\n",
)

print("learning.operator owner-failure follow-up applied")
