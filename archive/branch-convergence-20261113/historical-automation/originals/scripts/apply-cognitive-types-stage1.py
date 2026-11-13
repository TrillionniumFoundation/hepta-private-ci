#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path.cwd()

def read(path: str | Path) -> str:
    return (ROOT / path if isinstance(path, str) else path).read_text(encoding="utf-8")

def write(path: str | Path, content: str) -> None:
    target = ROOT / path if isinstance(path, str) else path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")

def replace_once(text: str, old: str, new: str, path: str | Path) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one occurrence, found {count}: {old[:120]!r}")
    return text.replace(old, new, 1)

def replace_re(text: str, pattern: str, replacement: str, path: str | Path, *, flags: int = re.S) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise SystemExit(f"{path}: regex expected one occurrence, found {count}: {pattern[:120]!r}")
    return updated

# ---------------------------------------------------------------------------
# cognitive.types Lane C write receipt + federation semantics
# ---------------------------------------------------------------------------
path = "codex-rs/hepta-cognitive-types/src/lane_c.rs"
text = read(path)
text = replace_once(
    text,
    '''pub const MAX_CONTEXT_DELIVERY_SEGMENTS: usize = 4_096;''',
    '''pub const MAX_CONTEXT_DELIVERY_SEGMENTS: usize = 4_096;
pub const MAX_MEMORY_WRITE_REJECTION_FIELD_PATH_BYTES: usize = 256;
const MEMORY_WRITE_INTENT_DOMAIN: &[u8] = b"hepta.cognitive.memory-write-intent.v1\\0";
const MEMORY_WRITE_RECEIPT_DOMAIN: &[u8] = b"hepta.cognitive.memory-write-receipt.v1\\0";''',
    path,
)
old = '''impl MemoryWriteIntentV1 {
    pub fn validate(&self) -> Result<(), LaneCContractError> {
        self.expected_snapshot.validate()?;
        ensure_digest("candidate", self.candidate_digest)?;
        ensure_digest("writer_fence", self.writer_fence_digest)?;
        ensure_digest("authorization", self.authorization_digest)?;
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MemoryWriteDisposition {
    Inserted,
    Unchanged,
    Rejected,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryWriteReceiptV1 {
    pub intent_id: StableId,
    pub record_id: StableId,
    pub record_digest: Digest32,
    pub committed_frontier: u64,
    pub snapshot_key: CognitiveSnapshotKeyV1,
    pub disposition: MemoryWriteDisposition,
    pub authority: AuthorityPosture,
}

impl MemoryWriteReceiptV1 {
    pub fn validate(&self) -> Result<(), LaneCContractError> {
        if self.committed_frontier == 0 {
            return Err(LaneCContractError::ZeroValue("committed_frontier"));
        }
        ensure_digest("record", self.record_digest)?;
        self.snapshot_key.validate()?;
        ensure_deny_all(self.authority)
    }
}
'''
new = '''impl MemoryWriteIntentV1 {
    pub fn validate(&self) -> Result<(), LaneCContractError> {
        self.expected_snapshot.validate()?;
        ensure_digest("candidate", self.candidate_digest)?;
        ensure_digest("writer_fence", self.writer_fence_digest)?;
        ensure_digest("authorization", self.authorization_digest)?;
        Ok(())
    }

    /// Digest of the exact candidate, expected snapshot, fence and authorization
    /// admitted by this intent.
    pub fn intent_digest(&self) -> Result<Digest32, LaneCContractError> {
        self.validate()?;
        Ok(compute_memory_write_intent_digest(
            &self.intent_id,
            self.candidate_digest,
            self.expected_snapshot.vector_digest,
            self.writer_fence_digest,
            self.authorization_digest,
        ))
    }

    pub fn receipt_binding(&self) -> Result<MemoryWriteReceiptBindingV1, LaneCContractError> {
        MemoryWriteReceiptBindingV1::from_intent(self)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MemoryWriteDisposition {
    Inserted,
    Unchanged,
    /// Compatibility projection only. Rejections are represented by
    /// `MemoryWriteOutcomeV1::Rejected`, never by a committed record.
    Rejected,
}

/// Immutable binding carried by every memory mutation receipt.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryWriteReceiptBindingV1 {
    intent_id: StableId,
    intent_digest: Digest32,
    candidate_digest: Digest32,
    expected_snapshot_digest: Digest32,
    writer_fence_digest: Digest32,
    authorization_digest: Digest32,
}

impl MemoryWriteReceiptBindingV1 {
    pub fn new(
        intent_id: StableId,
        candidate_digest: Digest32,
        expected_snapshot_digest: Digest32,
        writer_fence_digest: Digest32,
        authorization_digest: Digest32,
    ) -> Result<Self, LaneCContractError> {
        for (name, digest) in [
            ("candidate", candidate_digest),
            ("expected_snapshot", expected_snapshot_digest),
            ("writer_fence", writer_fence_digest),
            ("authorization", authorization_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        let intent_digest = compute_memory_write_intent_digest(
            &intent_id,
            candidate_digest,
            expected_snapshot_digest,
            writer_fence_digest,
            authorization_digest,
        );
        Ok(Self {
            intent_id,
            intent_digest,
            candidate_digest,
            expected_snapshot_digest,
            writer_fence_digest,
            authorization_digest,
        })
    }

    pub fn from_intent(intent: &MemoryWriteIntentV1) -> Result<Self, LaneCContractError> {
        intent.validate()?;
        Self::new(
            intent.intent_id.clone(),
            intent.candidate_digest,
            intent.expected_snapshot.vector_digest,
            intent.writer_fence_digest,
            intent.authorization_digest,
        )
    }

    pub fn validate(&self) -> Result<(), LaneCContractError> {
        for (name, digest) in [
            ("intent", self.intent_digest),
            ("candidate", self.candidate_digest),
            ("expected_snapshot", self.expected_snapshot_digest),
            ("writer_fence", self.writer_fence_digest),
            ("authorization", self.authorization_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.intent_digest
            != compute_memory_write_intent_digest(
                &self.intent_id,
                self.candidate_digest,
                self.expected_snapshot_digest,
                self.writer_fence_digest,
                self.authorization_digest,
            )
        {
            return Err(LaneCContractError::DigestMismatch("memory_write_intent"));
        }
        Ok(())
    }

    pub fn intent_id(&self) -> &StableId {
        &self.intent_id
    }

    pub const fn intent_digest(&self) -> Digest32 {
        self.intent_digest
    }

    pub const fn candidate_digest(&self) -> Digest32 {
        self.candidate_digest
    }

    pub const fn expected_snapshot_digest(&self) -> Digest32 {
        self.expected_snapshot_digest
    }

    pub const fn writer_fence_digest(&self) -> Digest32 {
        self.writer_fence_digest
    }

    pub const fn authorization_digest(&self) -> Digest32 {
        self.authorization_digest
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MemoryWriteRejectionCodeV1 {
    InvalidCandidate,
    AuthorizationDenied,
    SnapshotConflict,
    WriterFenceMismatch,
    CapacityExceeded,
    IdentityConflict,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum MemoryWriteOutcomeV1 {
    Committed {
        record_id: StableId,
        record_digest: Digest32,
        committed_frontier: u64,
        snapshot_key: CognitiveSnapshotKeyV1,
        disposition: MemoryWriteDisposition,
    },
    Rejected {
        code: MemoryWriteRejectionCodeV1,
        field_path: Option<String>,
        observed_snapshot: Option<CognitiveSnapshotKeyV1>,
    },
}

/// A receipt has exactly one tagged outcome. Rejected receipts contain no
/// record identifier, record digest or committed frontier.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryWriteReceiptV1 {
    binding: MemoryWriteReceiptBindingV1,
    outcome: MemoryWriteOutcomeV1,
    receipt_digest: Digest32,
    authority: AuthorityPosture,
}

impl MemoryWriteReceiptV1 {
    pub fn committed(
        binding: MemoryWriteReceiptBindingV1,
        record_id: StableId,
        record_digest: Digest32,
        committed_frontier: u64,
        snapshot_key: CognitiveSnapshotKeyV1,
        disposition: MemoryWriteDisposition,
    ) -> Result<Self, LaneCContractError> {
        let outcome = MemoryWriteOutcomeV1::Committed {
            record_id,
            record_digest,
            committed_frontier,
            snapshot_key,
            disposition,
        };
        Self::new(binding, outcome)
    }

    pub fn rejected(
        binding: MemoryWriteReceiptBindingV1,
        code: MemoryWriteRejectionCodeV1,
        field_path: Option<String>,
        observed_snapshot: Option<CognitiveSnapshotKeyV1>,
    ) -> Result<Self, LaneCContractError> {
        let outcome = MemoryWriteOutcomeV1::Rejected {
            code,
            field_path,
            observed_snapshot,
        };
        Self::new(binding, outcome)
    }

    fn new(
        binding: MemoryWriteReceiptBindingV1,
        outcome: MemoryWriteOutcomeV1,
    ) -> Result<Self, LaneCContractError> {
        let mut receipt = Self {
            binding,
            outcome,
            receipt_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        receipt.receipt_digest = receipt.compute_receipt_digest();
        receipt.validate()?;
        Ok(receipt)
    }

    pub fn validate(&self) -> Result<(), LaneCContractError> {
        self.binding.validate()?;
        ensure_deny_all(self.authority)?;
        match &self.outcome {
            MemoryWriteOutcomeV1::Committed {
                record_digest,
                committed_frontier,
                snapshot_key,
                disposition,
                ..
            } => {
                if *committed_frontier == 0 {
                    return Err(LaneCContractError::ZeroValue("committed_frontier"));
                }
                ensure_digest("record", *record_digest)?;
                snapshot_key.validate()?;
                if snapshot_key.vector.memory_ledger_frontier != *committed_frontier {
                    return Err(LaneCContractError::InvalidState(
                        "memory_write_frontier_binding",
                    ));
                }
                if matches!(disposition, MemoryWriteDisposition::Rejected) {
                    return Err(LaneCContractError::InvalidState(
                        "committed_write_cannot_be_rejected",
                    ));
                }
            }
            MemoryWriteOutcomeV1::Rejected {
                field_path,
                observed_snapshot,
                ..
            } => {
                if let Some(path) = field_path {
                    if path.trim().is_empty()
                        || path.len() > MAX_MEMORY_WRITE_REJECTION_FIELD_PATH_BYTES
                        || path.chars().any(char::is_control)
                    {
                        return Err(LaneCContractError::InvalidState(
                            "memory_write_rejection_field_path",
                        ));
                    }
                }
                if let Some(snapshot) = observed_snapshot {
                    snapshot.validate()?;
                }
            }
        }
        if self.receipt_digest != self.compute_receipt_digest() {
            return Err(LaneCContractError::DigestMismatch("memory_write_receipt"));
        }
        Ok(())
    }

    pub fn binding(&self) -> &MemoryWriteReceiptBindingV1 {
        &self.binding
    }

    pub fn outcome(&self) -> &MemoryWriteOutcomeV1 {
        &self.outcome
    }

    pub fn intent_id(&self) -> &StableId {
        self.binding.intent_id()
    }

    pub const fn intent_digest(&self) -> Digest32 {
        self.binding.intent_digest()
    }

    pub const fn candidate_digest(&self) -> Digest32 {
        self.binding.candidate_digest()
    }

    pub const fn authorization_digest(&self) -> Digest32 {
        self.binding.authorization_digest()
    }

    pub const fn writer_fence_digest(&self) -> Digest32 {
        self.binding.writer_fence_digest()
    }

    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    pub fn record_id(&self) -> Option<&StableId> {
        match &self.outcome {
            MemoryWriteOutcomeV1::Committed { record_id, .. } => Some(record_id),
            MemoryWriteOutcomeV1::Rejected { .. } => None,
        }
    }

    pub fn record_digest(&self) -> Option<Digest32> {
        match self.outcome {
            MemoryWriteOutcomeV1::Committed { record_digest, .. } => Some(record_digest),
            MemoryWriteOutcomeV1::Rejected { .. } => None,
        }
    }

    pub fn committed_frontier(&self) -> Option<u64> {
        match self.outcome {
            MemoryWriteOutcomeV1::Committed {
                committed_frontier,
                ..
            } => Some(committed_frontier),
            MemoryWriteOutcomeV1::Rejected { .. } => None,
        }
    }

    pub fn snapshot_key(&self) -> Option<&CognitiveSnapshotKeyV1> {
        match &self.outcome {
            MemoryWriteOutcomeV1::Committed { snapshot_key, .. } => Some(snapshot_key),
            MemoryWriteOutcomeV1::Rejected {
                observed_snapshot, ..
            } => observed_snapshot.as_ref(),
        }
    }

    pub fn disposition(&self) -> MemoryWriteDisposition {
        match self.outcome {
            MemoryWriteOutcomeV1::Committed { disposition, .. } => disposition,
            MemoryWriteOutcomeV1::Rejected { .. } => MemoryWriteDisposition::Rejected,
        }
    }

    #[cfg(test)]
    pub fn corrupt_intent_id_for_test(&mut self, intent_id: StableId) {
        self.binding.intent_id = intent_id;
    }

    #[cfg(test)]
    pub fn corrupt_record_digest_for_test(&mut self, digest: Digest32) {
        if let MemoryWriteOutcomeV1::Committed { record_digest, .. } = &mut self.outcome {
            *record_digest = digest;
        }
    }

    #[must_use]
    pub fn compute_receipt_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(MEMORY_WRITE_RECEIPT_DOMAIN);
        push_digest(&mut bytes, self.binding.intent_digest());
        push_digest(&mut bytes, self.binding.candidate_digest());
        push_digest(&mut bytes, self.binding.expected_snapshot_digest());
        push_digest(&mut bytes, self.binding.writer_fence_digest());
        push_digest(&mut bytes, self.binding.authorization_digest());
        match &self.outcome {
            MemoryWriteOutcomeV1::Committed {
                record_id,
                record_digest,
                committed_frontier,
                snapshot_key,
                disposition,
            } => {
                bytes.push(0);
                push_id(&mut bytes, record_id);
                push_digest(&mut bytes, *record_digest);
                push_u64(&mut bytes, *committed_frontier);
                push_digest(&mut bytes, snapshot_key.vector_digest);
                bytes.push(memory_write_disposition_code(*disposition));
            }
            MemoryWriteOutcomeV1::Rejected {
                code,
                field_path,
                observed_snapshot,
            } => {
                bytes.push(1);
                bytes.push(memory_write_rejection_code(*code));
                match field_path {
                    Some(path) => {
                        bytes.push(1);
                        push_len(&mut bytes, path.len());
                        bytes.extend_from_slice(path.as_bytes());
                    }
                    None => bytes.push(0),
                }
                match observed_snapshot {
                    Some(snapshot) => {
                        bytes.push(1);
                        push_digest(&mut bytes, snapshot.vector_digest);
                    }
                    None => bytes.push(0),
                }
            }
        }
        Digest32::of_bytes(&bytes)
    }
}
'''
text = replace_once(text, old, new, path)

old = '''        if matches!(self.completeness, FederatedCompletenessV1::Empty) && !self.items.is_empty() {
            return Err(LaneCContractError::InvalidState("federated_empty_result"));
        }
        if matches!(self.completeness, FederatedCompletenessV1::Complete)
            && self.coverage.failed_peers > 0
        {
            return Err(LaneCContractError::InvalidState(
                "federated_complete_with_failed_peers",
            ));
        }'''
new = '''        match self.completeness {
            FederatedCompletenessV1::Complete => {
                if self.items.is_empty()
                    || self.coverage.failed_peers != 0
                    || self.coverage.truncated_items != 0
                    || self.coverage.completed_peers != self.coverage.requested_peers
                {
                    return Err(LaneCContractError::InvalidState(
                        "federated_complete_coverage",
                    ));
                }
            }
            FederatedCompletenessV1::Partial => {
                if self.items.is_empty()
                    || (self.coverage.failed_peers == 0
                        && self.coverage.truncated_items == 0
                        && self.coverage.completed_peers == self.coverage.requested_peers)
                {
                    return Err(LaneCContractError::InvalidState(
                        "federated_partial_without_gap",
                    ));
                }
            }
            FederatedCompletenessV1::Empty => {
                if !self.items.is_empty() || self.coverage.truncated_items != 0 {
                    return Err(LaneCContractError::InvalidState(
                        "federated_empty_result",
                    ));
                }
            }
            FederatedCompletenessV1::Indeterminate => {
                if !self.items.is_empty()
                    || (self.coverage.failed_peers == 0
                        && self.coverage.completed_peers == self.coverage.requested_peers)
                {
                    return Err(LaneCContractError::InvalidState(
                        "federated_indeterminate_coverage",
                    ));
                }
            }
        }'''
text = replace_once(text, old, new, path)

needle = '''    #[must_use]
    pub fn compute_result_digest(&self) -> Digest32 {'''
insert = '''    pub fn validate_against_query(
        &self,
        query: &FederatedEvidenceQueryV1,
    ) -> Result<(), LaneCContractError> {
        self.validate()?;
        query.validate()?;
        if self.query_id != query.query_id
            || self.observed_snapshot != query.minimum_snapshot
            || self.coverage.requested_peers == 0
        {
            return Err(LaneCContractError::InvalidState(
                "federated_result_query_binding",
            ));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_result_digest(&self) -> Digest32 {'''
text = replace_once(text, needle, insert, path)

needle = '''const fn memory_admission_kind_code(value: MemoryAdmissionKind) -> u8 {'''
insert = '''fn compute_memory_write_intent_digest(
    intent_id: &StableId,
    candidate_digest: Digest32,
    expected_snapshot_digest: Digest32,
    writer_fence_digest: Digest32,
    authorization_digest: Digest32,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(MEMORY_WRITE_INTENT_DOMAIN);
    push_id(&mut bytes, intent_id);
    push_digest(&mut bytes, candidate_digest);
    push_digest(&mut bytes, expected_snapshot_digest);
    push_digest(&mut bytes, writer_fence_digest);
    push_digest(&mut bytes, authorization_digest);
    Digest32::of_bytes(&bytes)
}

const fn memory_write_disposition_code(value: MemoryWriteDisposition) -> u8 {
    match value {
        MemoryWriteDisposition::Inserted => 0,
        MemoryWriteDisposition::Unchanged => 1,
        MemoryWriteDisposition::Rejected => 2,
    }
}

const fn memory_write_rejection_code(value: MemoryWriteRejectionCodeV1) -> u8 {
    match value {
        MemoryWriteRejectionCodeV1::InvalidCandidate => 0,
        MemoryWriteRejectionCodeV1::AuthorizationDenied => 1,
        MemoryWriteRejectionCodeV1::SnapshotConflict => 2,
        MemoryWriteRejectionCodeV1::WriterFenceMismatch => 3,
        MemoryWriteRejectionCodeV1::CapacityExceeded => 4,
        MemoryWriteRejectionCodeV1::IdentityConflict => 5,
        MemoryWriteRejectionCodeV1::Indeterminate => 6,
    }
}

const fn memory_admission_kind_code(value: MemoryAdmissionKind) -> u8 {'''
text = replace_once(text, needle, insert, path)
write(path, text)

# ---------------------------------------------------------------------------
# HNMF selector manifests: authenticated membership, JSON pointer grammar
# ---------------------------------------------------------------------------
path = "codex-rs/hepta-cognitive-types/src/hnmf.rs"
text = read(path)
text = replace_once(
    text,
    '''pub const MAX_PATH_BYTES: usize = 4_096;
pub const MAX_LABEL_BYTES: usize = 128;''',
    '''pub const MAX_PATH_BYTES: usize = 4_096;
pub const MAX_LABEL_BYTES: usize = 128;
pub const MAX_SELECTOR_INDEX_ENTRIES: usize = 65_536;''',
    path,
)
text = replace_once(
    text,
    '''            (ModalityKindV1::StructuredData, Self::JsonPointer { pointer }) => {
                if !pointer.is_empty() && !pointer.starts_with('/') {
                    return Err(HnmfContractError::Invalid("JSON pointer"));
                }
                validate_bounded(pointer, MAX_PATH_BYTES, "JSON pointer")
            }''',
    '''            (ModalityKindV1::StructuredData, Self::JsonPointer { pointer }) => {
                validate_json_pointer_v1(pointer)
            }''',
    path,
)
text = replace_once(
    text,
    '''    CodeAst,
    GuiState,
    ToolTrajectory {
        event_count: u64,
    },
    StructuredData,
    Sensor {''',
    '''    CodeAst {
        selector_index_sha256: ContractDigestV1,
        valid_paths: BTreeSet<String>,
    },
    GuiState {
        selector_index_sha256: ContractDigestV1,
        valid_node_ids: BTreeSet<ContractIdV1>,
    },
    ToolTrajectory {
        event_count: u64,
    },
    StructuredData {
        selector_index_sha256: ContractDigestV1,
        valid_pointers: BTreeSet<String>,
    },
    Sensor {''',
    path,
)
needle = '''#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ModalitySpanRefV1 {'''
insert = '''impl AssetManifestV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        match (&self.extent, self.modality) {
            (AssetExtentV1::Bytes { byte_len }, ModalityKindV1::Text)
                if *byte_len > 0 => {}
            (AssetExtentV1::Image { width, height }, ModalityKindV1::Image)
                if *width > 0 && *height > 0 => {}
            (
                AssetExtentV1::Audio {
                    sample_count,
                    sample_rate_hz,
                },
                ModalityKindV1::Audio,
            ) if *sample_count > 0 && *sample_rate_hz > 0 => {}
            (
                AssetExtentV1::Video {
                    frame_count,
                    timebase_num,
                    timebase_den,
                },
                ModalityKindV1::Video,
            ) if *frame_count > 0 && *timebase_num > 0 && *timebase_den > 0 => {}
            (
                AssetExtentV1::CodeAst { valid_paths, .. },
                ModalityKindV1::CodeAst,
            ) => {
                validate_selector_count(valid_paths.len(), "AST selector index")?;
                for path in valid_paths {
                    validate_text(path, MAX_PATH_BYTES, "AST path")?;
                }
            }
            (
                AssetExtentV1::GuiState { valid_node_ids, .. },
                ModalityKindV1::GuiState,
            ) => validate_selector_count(valid_node_ids.len(), "GUI selector index")?,
            (
                AssetExtentV1::ToolTrajectory { event_count },
                ModalityKindV1::ToolTrajectory,
            ) if *event_count > 0 => {}
            (
                AssetExtentV1::StructuredData { valid_pointers, .. },
                ModalityKindV1::StructuredData,
            ) => {
                validate_selector_count(valid_pointers.len(), "JSON selector index")?;
                for pointer in valid_pointers {
                    validate_json_pointer_v1(pointer)?;
                }
            }
            (
                AssetExtentV1::Sensor { sample_count, unit },
                ModalityKindV1::Sensor,
            ) if *sample_count > 0 => validate_text(unit, MAX_LABEL_BYTES, "sensor unit")?,
            _ => {
                return Err(HnmfContractError::Conflict(
                    "asset extent/modality binding",
                ));
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ModalitySpanRefV1 {'''
text = replace_once(text, needle, insert, path)
text = replace_once(
    text,
    '''    span.validate()?;
    if span.asset_sha256 != manifest.asset_sha256''',
    '''    manifest.validate()?;
    span.validate()?;
    if span.asset_sha256 != manifest.asset_sha256''',
    path,
)
text = replace_once(
    text,
    '''        (AssetExtentV1::CodeAst, SpanRangeV1::AstPath { .. }, ModalityKindV1::CodeAst)
        | (AssetExtentV1::GuiState, SpanRangeV1::GuiNode { .. }, ModalityKindV1::GuiState)
        | (
            AssetExtentV1::StructuredData,
            SpanRangeV1::JsonPointer { .. },
            ModalityKindV1::StructuredData,
        ) => Ok(()),''',
    '''        (
            AssetExtentV1::CodeAst { valid_paths, .. },
            SpanRangeV1::AstPath { path },
            ModalityKindV1::CodeAst,
        ) if valid_paths.contains(path) => Ok(()),
        (
            AssetExtentV1::GuiState { valid_node_ids, .. },
            SpanRangeV1::GuiNode { stable_node_id },
            ModalityKindV1::GuiState,
        ) if valid_node_ids.contains(stable_node_id) => Ok(()),
        (
            AssetExtentV1::StructuredData { valid_pointers, .. },
            SpanRangeV1::JsonPointer { pointer },
            ModalityKindV1::StructuredData,
        ) if valid_pointers.contains(pointer) => Ok(()),''',
    path,
)
needle = '''pub(crate) fn increasing(
    start: u64,
    end: u64,
    name: &'static str,
) -> Result<(), HnmfContractError> {'''
insert = '''fn validate_selector_count(
    count: usize,
    field: &'static str,
) -> Result<(), HnmfContractError> {
    if count == 0 || count > MAX_SELECTOR_INDEX_ENTRIES {
        return Err(HnmfContractError::LimitExceeded {
            field,
            actual: count,
            maximum: MAX_SELECTOR_INDEX_ENTRIES,
        });
    }
    Ok(())
}

fn validate_json_pointer_v1(pointer: &str) -> Result<(), HnmfContractError> {
    validate_bounded(pointer, MAX_PATH_BYTES, "JSON pointer")?;
    if pointer.is_empty() {
        return Ok(());
    }
    if !pointer.starts_with('/') {
        return Err(HnmfContractError::Invalid("JSON pointer"));
    }
    let bytes = pointer.as_bytes();
    let mut index = 0usize;
    while index < bytes.len() {
        if bytes[index] == b'~' {
            let Some(next) = bytes.get(index + 1) else {
                return Err(HnmfContractError::Invalid("JSON pointer escape"));
            };
            if !matches!(*next, b'0' | b'1') {
                return Err(HnmfContractError::Invalid("JSON pointer escape"));
            }
            index += 2;
        } else {
            index += 1;
        }
    }
    Ok(())
}

pub(crate) fn increasing(
    start: u64,
    end: u64,
    name: &'static str,
) -> Result<(), HnmfContractError> {'''
text = replace_once(text, needle, insert, path)
write(path, text)

# ---------------------------------------------------------------------------
# Learning contracts: collection caps + semantic cross-field invariants
# ---------------------------------------------------------------------------
path = "codex-rs/hepta-cognitive-types/src/hnmf_learning.rs"
text = read(path)
text = replace_once(
    text,
    '''pub const MAX_WEIGHT_DELTA_PPM: i32 = 50_000;
pub const Q16_ONE: i32 = 65_536;''',
    '''pub const MAX_WEIGHT_DELTA_PPM: i32 = 50_000;
pub const MAX_REPLAY_SOURCE_BUCKETS: usize = 256;
pub const MAX_CONTRADICTIONS: usize = 512;
pub const MAX_WEIGHT_PROPOSALS: usize = 32_768;
pub const MAX_THRESHOLD_PROPOSALS: usize = 4_096;
pub const MAX_TOPOLOGY_DELTA_NODES: usize = 4_096;
pub const MAX_TOPOLOGY_DELTA_EDGES: usize = 32_768;
pub const MAX_FORGET_RETIRED_NODES: usize = 4_096;
pub const MAX_FORGET_RETIRED_SYNAPSES: usize = 32_768;
pub const Q16_ONE: i32 = 65_536;''',
    path,
)
text = replace_once(
    text,
    '''        if !(-(PPM as i32)..=PPM as i32).contains(&self.eligibility_ppm) {
            return Err(HnmfContractError::Invalid("synapse eligibility"));
        }
        Ok(())''',
    '''        if !(-(PPM as i32)..=PPM as i32).contains(&self.eligibility_ppm) {
            return Err(HnmfContractError::Invalid("synapse eligibility"));
        }
        validate_signed_relation(self.relation, self.weight_q16, "synapse relation/weight")?;
        if self.plasticity_class == PlasticityClassV1::Fixed && self.eligibility_ppm != 0 {
            return Err(HnmfContractError::Conflict(
                "fixed synapse has eligibility",
            ));
        }
        Ok(())''',
    path,
)
text = replace_once(
    text,
    '''        if self.source_node_id == self.target_node_id
            || !(-(PPM as i32)..=PPM as i32).contains(&self.contribution_ppm)
        {
            return Err(HnmfContractError::Invalid("activation path"));
        }
        Ok(())''',
    '''        if self.source_node_id == self.target_node_id
            || !(-(PPM as i32)..=PPM as i32).contains(&self.contribution_ppm)
        {
            return Err(HnmfContractError::Invalid("activation path"));
        }
        validate_signed_relation(
            self.relation,
            self.contribution_ppm,
            "activation path relation/contribution",
        )
''',
    path,
)
text = replace_once(
    text,
    '''        if self.selected_events.len() > MAX_RECALL_EVENTS
            || self.active_nodes.len() > MAX_ACTIVE_NODES
            || self.activation_paths.len() > MAX_ACTIVATION_PATHS
        {''',
    '''        if self.selected_events.len() > MAX_RECALL_EVENTS
            || self.active_nodes.len() > MAX_ACTIVE_NODES
            || self.activation_paths.len() > MAX_ACTIVATION_PATHS
            || self.contradictions.len() > MAX_CONTRADICTIONS
        {''',
    path,
)
text = replace_once(
    text,
    '''        if candidate_count > MAX_REPLAY_CANDIDATES
            || selected_count > MAX_REPLAY_SELECTION
            || selected_count > candidate_count
            || self.selected_event_ids.len() != selected_count''',
    '''        if candidate_count > MAX_REPLAY_CANDIDATES
            || selected_count > MAX_REPLAY_SELECTION
            || selected_count > candidate_count
            || self.selected_event_ids.len() != selected_count
            || self.source_bucket_counts.len() > MAX_REPLAY_SOURCE_BUCKETS''',
    path,
)
text = replace_once(
    text,
    '''        ensure_strict_order(&self.selected_event_ids, "selectedEventIds")?;
        if self''',
    '''        ensure_strict_order(&self.selected_event_ids, "selectedEventIds")?;
        if selected_count == 0 && !self.source_bucket_counts.is_empty() {
            return Err(HnmfContractError::Invalid("empty replay bucket counts"));
        }
        if self''',
    path,
)
text = replace_once(
    text,
    '''        validate_unit_q16(self.old_weight_q16, "old weight")?;
        validate_unit_q16(self.new_weight_q16, "new weight")?;
        if q16_delta_ppm(self.old_weight_q16, self.new_weight_q16)? != self.delta_ppm {''',
    '''        validate_unit_q16(self.old_weight_q16, "old weight")?;
        validate_unit_q16(self.new_weight_q16, "new weight")?;
        validate_signed_relation(
            self.relation,
            self.old_weight_q16,
            "old weight relation",
        )?;
        validate_signed_relation(
            self.relation,
            self.new_weight_q16,
            "new weight relation",
        )?;
        if self.old_weight_q16 == self.new_weight_q16 || self.delta_ppm == 0 {
            return Err(HnmfContractError::Invalid("no-op weight proposal"));
        }
        if q16_delta_ppm(self.old_weight_q16, self.new_weight_q16)? != self.delta_ppm {''',
    path,
)
text = replace_once(
    text,
    '''        validate_unit_q16(self.old_threshold_q16, "old threshold")?;
        validate_unit_q16(self.new_threshold_q16, "new threshold")?;
        if q16_delta_ppm(self.old_threshold_q16, self.new_threshold_q16)? != self.delta_ppm {''',
    '''        validate_unit_q16(self.old_threshold_q16, "old threshold")?;
        validate_unit_q16(self.new_threshold_q16, "new threshold")?;
        if self.old_threshold_q16 == self.new_threshold_q16 || self.delta_ppm == 0 {
            return Err(HnmfContractError::Invalid("no-op threshold proposal"));
        }
        if q16_delta_ppm(self.old_threshold_q16, self.new_threshold_q16)? != self.delta_ppm {''',
    path,
)
text = replace_once(
    text,
    '''        if self.predecessor_generation.next()? != self.next_generation
            || !self.current_snapshot_immutable
            || self.production_activation_allowed
        {
            return Err(HnmfContractError::Conflict(
                "plasticity generation/authority",
            ));
        }
        ensure_strict_order(&self.weight_proposals, "weightProposals")?;''',
    '''        if self.predecessor_generation.next()? != self.next_generation
            || !self.current_snapshot_immutable
            || self.production_activation_allowed
        {
            return Err(HnmfContractError::Conflict(
                "plasticity generation/authority",
            ));
        }
        if self.weight_proposals.is_empty() && self.threshold_proposals.is_empty() {
            return Err(HnmfContractError::Invalid("empty plasticity batch"));
        }
        if self.weight_proposals.len() > MAX_WEIGHT_PROPOSALS
            || self.threshold_proposals.len() > MAX_THRESHOLD_PROPOSALS
        {
            return Err(HnmfContractError::Invalid("plasticity batch bound"));
        }
        ensure_strict_order(&self.weight_proposals, "weightProposals")?;''',
    path,
)
text = replace_once(
    text,
    '''        if self.nodes.len() > MAX_NODES || self.edges.len() > MAX_SYNAPSES {
            return Err(HnmfContractError::Invalid("topology delta bound"));
        }''',
    '''        if self.nodes.len() > MAX_TOPOLOGY_DELTA_NODES
            || self.edges.len() > MAX_TOPOLOGY_DELTA_EDGES
        {
            return Err(HnmfContractError::Invalid("topology delta bound"));
        }''',
    path,
)
text = replace_once(
    text,
    '''impl TopologyProposalV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        self.typed_nodes_edges.validate()
    }
}''',
    '''impl TopologyProposalV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        self.typed_nodes_edges.validate()?;
        let nodes = i64::try_from(self.typed_nodes_edges.nodes.len())
            .map_err(|_| HnmfContractError::Invalid("topology node count"))?;
        let edges = i64::try_from(self.typed_nodes_edges.edges.len())
            .map_err(|_| HnmfContractError::Invalid("topology edge count"))?;
        match self.operation {
            TopologyOperationV1::Add => {
                if self.resource_delta.node_delta != nodes
                    || self.resource_delta.edge_delta != edges
                    || self.resource_delta.resident_bytes_upper_bound_delta <= 0
                {
                    return Err(HnmfContractError::Conflict("topology add delta"));
                }
            }
            TopologyOperationV1::Retire => {
                if self.resource_delta.node_delta != -nodes
                    || self.resource_delta.edge_delta != -edges
                    || self.resource_delta.resident_bytes_upper_bound_delta > 0
                {
                    return Err(HnmfContractError::Conflict("topology retire delta"));
                }
            }
            TopologyOperationV1::Split => {
                if nodes < 2
                    || self.resource_delta.node_delta != nodes - 1
                    || self.resource_delta.edge_delta < 0
                    || self.resource_delta.edge_delta > edges
                    || self.resource_delta.resident_bytes_upper_bound_delta <= 0
                {
                    return Err(HnmfContractError::Conflict("topology split delta"));
                }
            }
            TopologyOperationV1::Merge => {
                if nodes < 2
                    || self.resource_delta.node_delta != -(nodes - 1)
                    || self.resource_delta.edge_delta > 0
                    || self.resource_delta.edge_delta.abs() > edges
                    || self.resource_delta.resident_bytes_upper_bound_delta > 0
                {
                    return Err(HnmfContractError::Conflict("topology merge delta"));
                }
            }
            TopologyOperationV1::Rewire => {
                if !self.typed_nodes_edges.nodes.is_empty()
                    || self.typed_nodes_edges.edges.is_empty()
                    || self.resource_delta.node_delta != 0
                    || self.resource_delta.edge_delta != 0
                    || self.resource_delta.resident_bytes_upper_bound_delta != 0
                {
                    return Err(HnmfContractError::Conflict("topology rewire delta"));
                }
            }
        }
        Ok(())
    }
}''',
    path,
)
text = replace_once(
    text,
    '''impl ForgetPropagationReceiptV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.predecessor_generation.next()? != self.next_generation
            || !self.projection_rebuild_required
            || !self.artifact_revocation_required
        {
            return Err(HnmfContractError::Conflict("forget propagation"));
        }
        ensure_strict_order(&self.retired_node_ids, "retiredNodeIds")?;
        ensure_strict_order(&self.retired_synapses, "retiredSynapses")
    }
}''',
    '''impl ForgetPropagationReceiptV1 {
    pub fn validate(&self) -> Result<(), HnmfContractError> {
        if self.predecessor_generation.next()? != self.next_generation
            || !self.projection_rebuild_required
            || !self.artifact_revocation_required
        {
            return Err(HnmfContractError::Conflict("forget propagation"));
        }
        if self.retired_node_ids.is_empty() && self.retired_synapses.is_empty() {
            return Err(HnmfContractError::Invalid("empty forget propagation"));
        }
        if self.retired_node_ids.len() > MAX_FORGET_RETIRED_NODES
            || self.retired_synapses.len() > MAX_FORGET_RETIRED_SYNAPSES
        {
            return Err(HnmfContractError::Invalid("forget propagation bound"));
        }
        ensure_strict_order(&self.retired_node_ids, "retiredNodeIds")?;
        ensure_strict_order(&self.retired_synapses, "retiredSynapses")?;
        if self
            .retired_synapses
            .iter()
            .any(|synapse| synapse.source_node_id == synapse.target_node_id)
        {
            return Err(HnmfContractError::Invalid(
                "retired synapse self-loop",
            ));
        }
        Ok(())
    }
}''',
    path,
)
needle = '''fn validate_unit_q16(value: i32, field: &'static str) -> Result<(), HnmfContractError> {'''
insert = '''fn validate_signed_relation(
    relation: SynapseRelationV1,
    value: i32,
    field: &'static str,
) -> Result<(), HnmfContractError> {
    if (relation.is_negative() && value > 0) || (!relation.is_negative() && value < 0) {
        return Err(HnmfContractError::Conflict(field));
    }
    Ok(())
}

fn validate_unit_q16(value: i32, field: &'static str) -> Result<(), HnmfContractError> {'''
text = replace_once(text, needle, insert, path)
write(path, text)

# ---------------------------------------------------------------------------
# Wire safety: Validated<T>, registered closed-world decoder, digest domains
# ---------------------------------------------------------------------------
path = "codex-rs/hepta-cognitive-types/src/wire.rs"
text = read(path)
text = replace_once(
    text,
    '''pub const COGNITIVE_WIRE_VERSION_V1: u32 = 1;
const MAX_ENVELOPE_OVERHEAD_BYTES: usize = 1_024;
const DIGEST_DOMAIN_V1: &[u8] = b"hepta.cognitive.contract.canonical-json.v1\\0";''',
    '''pub const COGNITIVE_WIRE_VERSION_V1: u32 = 1;
pub const CANONICALIZATION_ALGORITHM_V1: &str =
    "canonical_json_utf8_sorted_object_keys_integer_only_no_unicode_normalization_v1";
pub const UNICODE_NORMALIZATION_POLICY_V1: &str = "none_codepoint_exact";
const MAX_ENVELOPE_OVERHEAD_BYTES: usize = 1_024;
const DIGEST_DOMAIN_V1: &[u8] = b"hepta.cognitive.contract.canonical-json\\0";''',
    path,
)
needle = '''macro_rules! impl_contract {'''
insert = '''#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Validated<T: CognitiveContractV1> {
    value: T,
}

impl<T: CognitiveContractV1> Validated<T> {
    pub fn new(value: T) -> Result<Self, CognitiveWireError> {
        value
            .validate_contract()
            .map_err(CognitiveWireError::Contract)?;
        Ok(Self { value })
    }

    pub fn get(&self) -> &T {
        &self.value
    }

    pub fn into_inner(self) -> T {
        self.value
    }

    pub fn encode_payload(&self) -> Result<Vec<u8>, CognitiveWireError> {
        encode_payload_validated_v1(self)
    }

    pub fn encode_wire(&self) -> Result<Vec<u8>, CognitiveWireError> {
        encode_validated_wire_v1(self)
    }

    pub fn digest(&self) -> Result<Digest32, CognitiveWireError> {
        canonical_validated_digest_v1(self)
    }
}

macro_rules! impl_contract {'''
text = replace_once(text, needle, insert, path)
needle = '''#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CognitiveWireEnvelopeV1<T> {
    schema: String,
    schema_version: u32,
    contract: String,
    payload: T,
}
'''
insert = '''#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CognitiveWireEnvelopeV1<T> {
    schema: String,
    schema_version: u32,
    contract: String,
    payload: T,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct CognitiveWireEnvelopeRefV1<'a, T> {
    schema: &'static str,
    schema_version: u32,
    contract: &'static str,
    payload: &'a T,
}
'''
text = replace_once(text, needle, insert, path)

pattern = r'''pub fn encode_payload_canonical_v1<T: CognitiveContractV1>\(
    value: &T,
\) -> Result<Vec<u8>, CognitiveWireError> \{.*?
\}

pub fn encode_wire_v1<T: CognitiveContractV1>\(value: &T\) -> Result<Vec<u8>, CognitiveWireError> \{.*?
\}

pub fn decode_wire_v1'''
replacement = '''pub fn encode_payload_canonical_v1<T: CognitiveContractV1>(
    value: &T,
) -> Result<Vec<u8>, CognitiveWireError> {
    Validated::new(value.clone())?.encode_payload()
}

pub fn encode_payload_validated_v1<T: CognitiveContractV1>(
    value: &Validated<T>,
) -> Result<Vec<u8>, CognitiveWireError> {
    let encoded = canonical_json_bytes(value.get())?;
    if encoded.is_empty() || encoded.len() > T::MAX_ENCODED_BYTES {
        return Err(CognitiveWireError::PayloadLength {
            actual: encoded.len(),
            maximum: T::MAX_ENCODED_BYTES,
        });
    }
    Ok(encoded)
}

pub fn encode_wire_v1<T: CognitiveContractV1>(value: &T) -> Result<Vec<u8>, CognitiveWireError> {
    Validated::new(value.clone())?.encode_wire()
}

pub fn encode_validated_wire_v1<T: CognitiveContractV1>(
    value: &Validated<T>,
) -> Result<Vec<u8>, CognitiveWireError> {
    let payload = encode_payload_validated_v1(value)?;
    let envelope = CognitiveWireEnvelopeRefV1 {
        schema: T::SCHEMA_ID,
        schema_version: COGNITIVE_WIRE_VERSION_V1,
        contract: T::CONTRACT_ID,
        payload: value.get(),
    };
    let encoded = canonical_json_bytes(&envelope)?;
    let maximum = T::MAX_ENCODED_BYTES + MAX_ENVELOPE_OVERHEAD_BYTES;
    if encoded.len() > maximum {
        return Err(CognitiveWireError::EnvelopeLength {
            actual: encoded.len(),
            maximum,
        });
    }
    debug_assert!(encoded.len() >= payload.len());
    Ok(encoded)
}

pub fn decode_wire_v1'''
text = replace_re(text, pattern, replacement, path)
text = replace_once(
    text,
    '''    envelope
        .payload
        .validate_contract()
        .map_err(CognitiveWireError::Contract)?;
    let payload = canonical_json_bytes(&envelope.payload)?;''',
    '''    let validated = Validated::new(envelope.payload.clone())?;
    let payload = encode_payload_validated_v1(&validated)?;''',
    path,
)
text = replace_once(
    text,
    '''    Ok(envelope.payload)
}

/// Canonical V1 digest''',
    '''    Ok(validated.into_inner())
}

/// Canonical V1 digest''',
    path,
)
text = replace_once(
    text,
    '''pub fn canonical_contract_digest_v1<T: CognitiveContractV1>(
    value: &T,
) -> Result<Digest32, CognitiveWireError> {
    let payload = encode_payload_canonical_v1(value)?;
    Ok(Digest32::of_parts(&[
        DIGEST_DOMAIN_V1,
        T::CONTRACT_ID.as_bytes(),
        b"\\0",
        payload.as_slice(),
    ]))
}
''',
    '''pub fn canonical_contract_digest_v1<T: CognitiveContractV1>(
    value: &T,
) -> Result<Digest32, CognitiveWireError> {
    Validated::new(value.clone())?.digest()
}

pub fn canonical_validated_digest_v1<T: CognitiveContractV1>(
    value: &Validated<T>,
) -> Result<Digest32, CognitiveWireError> {
    let payload = encode_payload_validated_v1(value)?;
    let version = COGNITIVE_WIRE_VERSION_V1.to_string();
    Ok(Digest32::of_parts(&[
        DIGEST_DOMAIN_V1,
        T::SCHEMA_ID.as_bytes(),
        b"\\0",
        version.as_bytes(),
        b"\\0",
        CANONICALIZATION_ALGORITHM_V1.as_bytes(),
        b"\\0",
        T::CONTRACT_ID.as_bytes(),
        b"\\0",
        payload.as_slice(),
    ]))
}
''',
    path,
)
needle = '''fn canonical_json_bytes<T: Serialize>(value: &T) -> Result<Vec<u8>, CognitiveWireError> {'''
insert = '''#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RegisteredCognitiveContractV1 {
    ModalitySpanRef(ModalitySpanRefV1),
    MemoryEvent(MemoryEventV1),
    CrossModalBinding(CrossModalBindingV1),
    EngramNode(EngramNodeV1),
    Synapse(SynapseV1),
    MemoryCue(MemoryCueV1),
    RecallPacket(RecallPacketV1),
    OutcomeSignal(OutcomeSignalV1),
    ReplaySelectionReceipt(ReplaySelectionReceiptV1),
    PlasticityBatch(PlasticityBatchV1),
    TopologyProposal(TopologyProposalV1),
    ForgetPropagationReceipt(ForgetPropagationReceiptV1),
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CognitiveWireHeaderV1 {
    schema: String,
    schema_version: u32,
    contract: String,
    payload: Value,
}

pub fn decode_registered_wire_v1(
    bytes: &[u8],
) -> Result<RegisteredCognitiveContractV1, CognitiveWireError> {
    let maximum = 262_144 + MAX_ENVELOPE_OVERHEAD_BYTES;
    if bytes.is_empty() || bytes.len() > maximum {
        return Err(CognitiveWireError::EnvelopeLength {
            actual: bytes.len(),
            maximum,
        });
    }
    let header: CognitiveWireHeaderV1 =
        serde_json::from_slice(bytes).map_err(CognitiveWireError::Json)?;
    if header.schema_version != COGNITIVE_WIRE_VERSION_V1 {
        return Err(CognitiveWireError::VersionMismatch(header.schema_version));
    }
    let identity = (header.schema.as_str(), header.contract.as_str());
    let decoded = match identity {
        (ModalitySpanRefV1::SCHEMA_ID, ModalitySpanRefV1::CONTRACT_ID) => {
            RegisteredCognitiveContractV1::ModalitySpanRef(decode_wire_v1(bytes)?)
        }
        (MemoryEventV1::SCHEMA_ID, MemoryEventV1::CONTRACT_ID) => {
            RegisteredCognitiveContractV1::MemoryEvent(decode_wire_v1(bytes)?)
        }
        (CrossModalBindingV1::SCHEMA_ID, CrossModalBindingV1::CONTRACT_ID) => {
            RegisteredCognitiveContractV1::CrossModalBinding(decode_wire_v1(bytes)?)
        }
        (EngramNodeV1::SCHEMA_ID, EngramNodeV1::CONTRACT_ID) => {
            RegisteredCognitiveContractV1::EngramNode(decode_wire_v1(bytes)?)
        }
        (SynapseV1::SCHEMA_ID, SynapseV1::CONTRACT_ID) => {
            RegisteredCognitiveContractV1::Synapse(decode_wire_v1(bytes)?)
        }
        (MemoryCueV1::SCHEMA_ID, MemoryCueV1::CONTRACT_ID) => {
            RegisteredCognitiveContractV1::MemoryCue(decode_wire_v1(bytes)?)
        }
        (RecallPacketV1::SCHEMA_ID, RecallPacketV1::CONTRACT_ID) => {
            RegisteredCognitiveContractV1::RecallPacket(decode_wire_v1(bytes)?)
        }
        (OutcomeSignalV1::SCHEMA_ID, OutcomeSignalV1::CONTRACT_ID) => {
            RegisteredCognitiveContractV1::OutcomeSignal(decode_wire_v1(bytes)?)
        }
        (
            ReplaySelectionReceiptV1::SCHEMA_ID,
            ReplaySelectionReceiptV1::CONTRACT_ID,
        ) => RegisteredCognitiveContractV1::ReplaySelectionReceipt(decode_wire_v1(bytes)?),
        (PlasticityBatchV1::SCHEMA_ID, PlasticityBatchV1::CONTRACT_ID) => {
            RegisteredCognitiveContractV1::PlasticityBatch(decode_wire_v1(bytes)?)
        }
        (TopologyProposalV1::SCHEMA_ID, TopologyProposalV1::CONTRACT_ID) => {
            RegisteredCognitiveContractV1::TopologyProposal(decode_wire_v1(bytes)?)
        }
        (
            ForgetPropagationReceiptV1::SCHEMA_ID,
            ForgetPropagationReceiptV1::CONTRACT_ID,
        ) => RegisteredCognitiveContractV1::ForgetPropagationReceipt(decode_wire_v1(bytes)?),
        _ => return Err(CognitiveWireError::UnregisteredContract),
    };
    let _ = header.payload;
    Ok(decoded)
}

fn canonical_json_bytes<T: Serialize>(value: &T) -> Result<Vec<u8>, CognitiveWireError> {'''
text = replace_once(text, needle, insert, path)
text = replace_once(
    text,
    '''    ContractMismatch,
    NonCanonicalInput,''',
    '''    ContractMismatch,
    UnregisteredContract,
    NonCanonicalInput,''',
    path,
)
text = replace_once(
    text,
    '''            Self::ContractMismatch => formatter.write_str("cognitive wire contract mismatch"),
            Self::NonCanonicalInput => {''',
    '''            Self::ContractMismatch => formatter.write_str("cognitive wire contract mismatch"),
            Self::UnregisteredContract => {
                formatter.write_str("cognitive wire contract is not registered")
            }
            Self::NonCanonicalInput => {''',
    path,
)
write(path, text)

# ---------------------------------------------------------------------------
# Record transition validation
# ---------------------------------------------------------------------------
path = "codex-rs/hepta-cognitive-types/src/lib.rs"
text = read(path)
needle = '''    #[must_use]
    pub fn record_digest(&self) -> Digest32 {'''
insert = '''    pub fn validated_digest(&self) -> Result<Digest32, CognitiveTypeError> {
        self.validate()?;
        Ok(self.record_digest())
    }

    pub fn validate_transition_from(
        &self,
        previous: &MemoryRecord,
    ) -> Result<(), CognitiveTypeError> {
        previous.validate()?;
        self.validate()?;
        if self.record_id != previous.record_id
            || self.revision.get() != previous.revision.get().saturating_add(1)
            || self.predecessor_digest != Some(previous.validated_digest()?)
            || previous.state == RecordState::Tombstone
        {
            return Err(CognitiveTypeError::InvalidRecordTransition);
        }
        Ok(())
    }

    #[must_use]
    pub fn record_digest(&self) -> Digest32 {'''
text = replace_once(text, needle, insert, path)
text = replace_once(
    text,
    '''    DuplicateRevision { record_id: String, revision: u64 },
}''',
    '''    DuplicateRevision { record_id: String, revision: u64 },
    InvalidRecordTransition,
}''',
    path,
)
write(path, text)

# ---------------------------------------------------------------------------
# Store migration for bound receipts
# ---------------------------------------------------------------------------
path = "codex-rs/hepta-cognitive-store/src/v2.rs"
text = read(path)
text = replace_once(
    text,
    '''use codex_hepta_cognitive_types::lane_c::MemoryWriteReceiptV1;''',
    '''use codex_hepta_cognitive_types::lane_c::MemoryWriteReceiptBindingV1;
use codex_hepta_cognitive_types::lane_c::MemoryWriteReceiptV1;''',
    path,
)
text = replace_once(
    text,
    '''        let candidate_digest = candidate.digest();
        if intent.candidate_digest != candidate_digest {''',
    '''        let candidate_digest = candidate.digest();
        if intent.candidate_digest != candidate_digest {''',
    path,
)
text = replace_once(
    text,
    '''        let semantic_digest = append_semantic_digest(&candidate, &intent);''',
    '''        let receipt_binding = intent
            .receipt_binding()
            .map_err(CognitiveStoreV2Error::Contract)?;
        let semantic_digest = append_semantic_digest(&candidate, &intent);''',
    path,
)
text = replace_once(
    text,
    '''                    let receipt = MemoryWriteReceiptV1 {
                        intent_id: intent.intent_id.clone(),
                        record_id,
                        record_digest: head.record_digest(),
                        committed_frontier: self.snapshot_key.vector.memory_ledger_frontier,
                        snapshot_key: self.snapshot_key.clone(),
                        disposition: MemoryWriteDisposition::Unchanged,
                        authority: AuthorityPosture::DENY_ALL,
                    };''',
    '''                    let receipt = MemoryWriteReceiptV1::committed(
                        receipt_binding.clone(),
                        record_id,
                        head.record_digest(),
                        self.snapshot_key.vector.memory_ledger_frontier,
                        self.snapshot_key.clone(),
                        MemoryWriteDisposition::Unchanged,
                    )
                    .map_err(CognitiveStoreV2Error::Contract)?;''',
    path,
)
text = replace_once(
    text,
    '''        self.commit_record(intent.intent_id, semantic_digest, record, disposition)''',
    '''        self.commit_record(receipt_binding, semantic_digest, record, disposition)''',
    path,
)
text = replace_once(
    text,
    '''        let mut shadow_receipt = CanonicalMemoryEventShadowReceiptV1 {
            event_id,
            event_digest,
            candidate_digest,
            record_id: write_receipt.record_id.clone(),
            record_digest: write_receipt.record_digest,
            snapshot_vector_digest: write_receipt.snapshot_key.vector_digest,
            disposition: write_receipt.disposition,
            binding_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };''',
    '''        let record_id = write_receipt
            .record_id()
            .cloned()
            .ok_or(CognitiveStoreV2Error::CanonicalShadowReceiptMismatch)?;
        let record_digest = write_receipt
            .record_digest()
            .ok_or(CognitiveStoreV2Error::CanonicalShadowReceiptMismatch)?;
        let snapshot_vector_digest = write_receipt
            .snapshot_key()
            .ok_or(CognitiveStoreV2Error::CanonicalShadowReceiptMismatch)?
            .vector_digest;
        let mut shadow_receipt = CanonicalMemoryEventShadowReceiptV1 {
            event_id,
            event_digest,
            candidate_digest,
            record_id,
            record_digest,
            snapshot_vector_digest,
            disposition: write_receipt.disposition(),
            binding_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };''',
    path,
)
text = replace_once(
    text,
    '''        self.commit_record(
            intent.intent_id,
            semantic_digest,
            record,
            MemoryWriteDisposition::Inserted,
        )''',
    '''        let receipt_binding = MemoryWriteReceiptBindingV1::new(
            intent.intent_id,
            semantic_digest,
            intent.expected_snapshot.vector_digest,
            intent.writer_fence_digest,
            intent.authorization_digest,
        )
        .map_err(CognitiveStoreV2Error::Contract)?;
        self.commit_record(
            receipt_binding,
            semantic_digest,
            record,
            MemoryWriteDisposition::Inserted,
        )''',
    path,
)
text = replace_once(
    text,
    '''    fn commit_record(
        &mut self,
        intent_id: StableId,
        semantic_digest: Digest32,
        record: MemoryRecord,
        disposition: MemoryWriteDisposition,
    ) -> Result<MemoryWriteReceiptV1, CognitiveStoreV2Error> {''',
    '''    fn commit_record(
        &mut self,
        receipt_binding: MemoryWriteReceiptBindingV1,
        semantic_digest: Digest32,
        record: MemoryRecord,
        disposition: MemoryWriteDisposition,
    ) -> Result<MemoryWriteReceiptV1, CognitiveStoreV2Error> {''',
    path,
)
text = replace_once(
    text,
    '''        let receipt = MemoryWriteReceiptV1 {
            intent_id: intent_id.clone(),
            record_id: record_id.clone(),
            record_digest,
            committed_frontier: next_memory_frontier,
            snapshot_key: next_snapshot_key.clone(),
            disposition,
            authority: AuthorityPosture::DENY_ALL,
        };''',
    '''        let intent_id = receipt_binding.intent_id().clone();
        let receipt = MemoryWriteReceiptV1::committed(
            receipt_binding,
            record_id.clone(),
            record_digest,
            next_memory_frontier,
            next_snapshot_key.clone(),
            disposition,
        )
        .map_err(CognitiveStoreV2Error::Contract)?;''',
    path,
)
text = text.replace('entry.receipt.intent_id', 'entry.receipt.intent_id()')
text = text.replace('entry.receipt.record_id', 'entry.receipt.record_id().expect("committed receipt record")')
text = text.replace('entry.receipt.record_digest', 'entry.receipt.record_digest().expect("committed receipt digest")')
text = text.replace('entry.receipt.disposition', 'entry.receipt.disposition()')
text = text.replace('entry.receipt.committed_frontier', 'entry.receipt.committed_frontier().expect("committed receipt frontier")')
text = text.replace('entry.receipt.snapshot_key', 'entry.receipt.snapshot_key().expect("committed receipt snapshot")')
text = text.replace(
    'inserted_receipts.sort_by_key(|entry| entry.receipt.committed_frontier().expect("committed receipt frontier"));',
    'inserted_receipts.sort_by_key(|entry| entry.receipt.committed_frontier());'
)
text = text.replace(
    '.get(&first.receipt.record_digest)',
    '.get(&first.receipt.record_digest().expect("inserted receipt record digest"))'
)
text = text.replace(
    '''first
                .receipt
                .committed_frontier
                .checked_sub(1)''',
    '''first
                .receipt
                .committed_frontier()
                .expect("inserted receipt frontier")
                .checked_sub(1)'''
)
text = text.replace(
    '''first
                .receipt
                .snapshot_key
                .vector
                .knowledge_fact_frontier''',
    '''first
                .receipt
                .snapshot_key()
                .expect("inserted receipt snapshot")
                .vector
                .knowledge_fact_frontier'''
)
text = text.replace(
    '''first
                .receipt
                .snapshot_key
                .vector
                .tombstone_frontier''',
    '''first
                .receipt
                .snapshot_key()
                .expect("inserted receipt snapshot")
                .vector
                .tombstone_frontier'''
)
text = text.replace(
    '.get(&entry.receipt.record_digest)',
    '.get(&entry.receipt.record_digest().expect("inserted receipt record digest"))'
)
text = text.replace(
    '!covered_records.insert(entry.receipt.record_digest)',
    '!covered_records.insert(entry.receipt.record_digest().expect("inserted receipt record digest"))'
)
text = text.replace(
    'let vector = &entry.receipt.snapshot_key.vector;',
    'let vector = &entry.receipt.snapshot_key().expect("inserted receipt snapshot").vector;'
)
text = text.replace(
    'if entry.receipt.committed_frontier != expected_memory',
    'if entry.receipt.committed_frontier() != Some(expected_memory)'
)
text = replace_once(
    text,
    '''            push_id(&mut bytes, &entry.receipt.intent_id);
            push_id(&mut bytes, &entry.receipt.record_id);
            push_digest(&mut bytes, entry.receipt.record_digest);
            push_digest(&mut bytes, entry.receipt.snapshot_key.vector_digest);
            push_u64(&mut bytes, entry.receipt.committed_frontier);
            bytes.push(memory_write_disposition_code(entry.receipt.disposition));''',
    '''            push_id(&mut bytes, entry.receipt.intent_id());
            push_digest(&mut bytes, entry.receipt.receipt_digest());''',
    path,
)
write(path, text)

path = "codex-rs/hepta-cognitive-store/src/v2_tests.rs"
text = read(path)
text = text.replace(
    'wrong_intent.journal[0].receipt.intent_id = id("intent:image:forged");',
    'wrong_intent.journal[0].receipt.corrupt_intent_id_for_test(id("intent:image:forged"));'
)
text = text.replace(
    'wrong_record.journal[0].receipt.record_digest = digest("forged-record");',
    'wrong_record.journal[0].receipt.corrupt_record_digest_for_test(digest("forged-record"));'
)
text = text.replace(
    'result.write_receipt.record_digest',
    'result.write_receipt.record_digest().expect("committed receipt")'
)
write(path, text)

# ---------------------------------------------------------------------------
# Lane C post-patch correctness adjustments
# ---------------------------------------------------------------------------
path = ROOT / "codex-rs/hepta-cognitive-types/src/lane_c.rs"
text = read(path)
text = replace_once(
    text,
    '''    pub fn record_digest(&self) -> Option<Digest32> {
        match self.outcome {
            MemoryWriteOutcomeV1::Committed { record_digest, .. } => Some(record_digest),
            MemoryWriteOutcomeV1::Rejected { .. } => None,
        }
    }

    pub fn committed_frontier(&self) -> Option<u64> {
        match self.outcome {
            MemoryWriteOutcomeV1::Committed {
                committed_frontier,
                ..
            } => Some(committed_frontier),
            MemoryWriteOutcomeV1::Rejected { .. } => None,
        }
    }''',
    '''    pub fn record_digest(&self) -> Option<Digest32> {
        match &self.outcome {
            MemoryWriteOutcomeV1::Committed { record_digest, .. } => Some(*record_digest),
            MemoryWriteOutcomeV1::Rejected { .. } => None,
        }
    }

    pub fn committed_frontier(&self) -> Option<u64> {
        match &self.outcome {
            MemoryWriteOutcomeV1::Committed {
                committed_frontier,
                ..
            } => Some(*committed_frontier),
            MemoryWriteOutcomeV1::Rejected { .. } => None,
        }
    }''',
    path,
)
text = replace_once(
    text,
    '''    pub fn disposition(&self) -> MemoryWriteDisposition {
        match self.outcome {
            MemoryWriteOutcomeV1::Committed { disposition, .. } => disposition,
            MemoryWriteOutcomeV1::Rejected { .. } => MemoryWriteDisposition::Rejected,
        }
    }

    #[cfg(test)]
    pub fn corrupt_intent_id_for_test(&mut self, intent_id: StableId) {
        self.binding.intent_id = intent_id;
    }

    #[cfg(test)]
    pub fn corrupt_record_digest_for_test(&mut self, digest: Digest32) {
        if let MemoryWriteOutcomeV1::Committed { record_digest, .. } = &mut self.outcome {
            *record_digest = digest;
        }
    }''',
    '''    pub fn disposition(&self) -> MemoryWriteDisposition {
        match &self.outcome {
            MemoryWriteOutcomeV1::Committed { disposition, .. } => *disposition,
            MemoryWriteOutcomeV1::Rejected { .. } => MemoryWriteDisposition::Rejected,
        }
    }

    /// Adversarial qualification hook. Production code must never call this.
    #[doc(hidden)]
    pub fn corrupt_intent_id_for_test(&mut self, intent_id: StableId) {
        self.binding.intent_id = intent_id;
    }

    /// Adversarial qualification hook. Production code must never call this.
    #[doc(hidden)]
    pub fn corrupt_record_digest_for_test(&mut self, digest: Digest32) {
        if let MemoryWriteOutcomeV1::Committed { record_digest, .. } = &mut self.outcome {
            *record_digest = digest;
        }
    }''',
    path,
)
write(path, text)

# ---------------------------------------------------------------------------
# Repository-wide CI blocker: route durable SQLite pools through codex-state
# ---------------------------------------------------------------------------
state_sqlite = ROOT / "codex-rs/state/src/sqlite.rs"
text = read(state_sqlite)
needle = '''const THREAD_HISTORY_DB: RuntimeDbSpec = RuntimeDbSpec {
    label: "thread history DB",
    filename: THREAD_HISTORY_DB_FILENAME,
    kind: DbKind::ThreadHistory,
    open_phase: "open_thread_history",
    migrate_phase: "migrate_thread_history",
};'''
insert = needle + '''

/// Centralized opener for append-only, owner-authoritative SQLite evidence
/// stores outside the built-in state database set.
///
/// Callers retain migration and corruption policy ownership. The connection
/// policy is centralized here so every durable store gets WAL, full synchronous
/// durability, foreign-key enforcement, bounded busy waiting and disabled SQL
/// statement logging.
pub async fn open_durable_sqlite_pool(
    path: &Path,
    maximum_connections: u32,
) -> Result<SqlitePool, Error> {
    if maximum_connections == 0 {
        return Err(Error::Configuration(
            "maximum_connections must be non-zero".into(),
        ));
    }
    let options = SqliteConnectOptions::new()
        .filename(path)
        .create_if_missing(true)
        .journal_mode(SqliteJournalMode::Wal)
        .synchronous(SqliteSynchronous::Full)
        .foreign_keys(true)
        .busy_timeout(Duration::from_secs(5))
        .log_statements(LevelFilter::Off);
    SqlitePoolOptions::new()
        .max_connections(maximum_connections)
        .connect_with(options)
        .await
}'''
text = replace_once(text, needle, insert, state_sqlite)
write(state_sqlite, text)

state_lib = ROOT / "codex-rs/state/src/lib.rs"
text = read(state_lib)
text = replace_once(
    text,
    '''pub use sqlite::RuntimeDbPath;''',
    '''pub use sqlite::RuntimeDbPath;
pub use sqlite::open_durable_sqlite_pool;''',
    state_lib,
)
write(state_lib, text)

ops_cargo = ROOT / "codex-rs/hepta-operations/Cargo.toml"
text = read(ops_cargo)
text = replace_once(
    text,
    '''codex-hepta-types = { workspace = true }
sqlx = { workspace = true }''',
    '''codex-hepta-types = { workspace = true }
codex-state = { workspace = true }
sqlx = { workspace = true }''',
    ops_cargo,
)
write(ops_cargo, text)

for relative in [
    "codex-rs/hepta-operations/src/durable_store.rs",
    "codex-rs/hepta-operations/src/destination_dedupe.rs",
]:
    path = ROOT / relative
    text = read(path)
    old = '''        let options = SqliteConnectOptions::new()
            .filename(path)
            .create_if_missing(true)
            .journal_mode(SqliteJournalMode::Wal)
            .synchronous(SqliteSynchronous::Full)
            .foreign_keys(true)
            .busy_timeout(Duration::from_secs(5));
        let pool = SqlitePoolOptions::new()
            .max_connections(4)
            .connect_with(options)
            .await
            .map_err(sqlx_error)?;'''
    new = '''        let pool = codex_state::open_durable_sqlite_pool(path, 4)
            .await
            .map_err(sqlx_error)?;'''
    text = replace_once(text, old, new, path)
    for unused in [
        "use sqlx::sqlite::SqliteConnectOptions;\n",
        "use sqlx::sqlite::SqliteJournalMode;\n",
        "use sqlx::sqlite::SqlitePoolOptions;\n",
        "use sqlx::sqlite::SqliteSynchronous;\n",
    ]:
        if text.count(unused) == 1:
            text = text.replace(unused, "")
    write(path, text)

path = ROOT / "codex-rs/hepta-operations/src/durable_store.rs"
text = read(path)
text = replace_once(
    text,
    '''        if let Some(status) = load_outbox_tx(
            &mut tx,
            &operation.intent.destination,
            scope_id,
            operation_id,
        )
        .await?
        {
            if status.state != DurableOutboxState::Acknowledged {
                let fence = status
                    .fence
                    .checked_add(1)
                    .ok_or(DurableOperationError::Capacity)?;
                sqlx::query(
                    "UPDATE cross_owner_outbox SET state = 'acked', fence = ?, worker_id = NULL,
                     lease_until_ms = NULL, acknowledgement_digest = ?, updated_at_ms = ?,
                     terminal_at_ms = COALESCE(terminal_at_ms, ?)
                     WHERE destination = ? AND scope_id = ? AND operation_id = ?",
                )
                .bind(to_i64(fence)?)
                .bind(receipt.evidence_digest.as_array().as_slice())
                .bind(now)
                .bind(now)
                .bind(operation.intent.destination.as_str())
                .bind(scope_id.as_str())
                .bind(operation_id.as_str())
                .execute(&mut *tx)
                .await
                .map_err(sqlx_error)?;
            }
        }''',
    '''        if let Some(status) = load_outbox_tx(
            &mut tx,
            &operation.intent.destination,
            scope_id,
            operation_id,
        )
        .await?
            && status.state != DurableOutboxState::Acknowledged
        {
            let fence = status
                .fence
                .checked_add(1)
                .ok_or(DurableOperationError::Capacity)?;
            sqlx::query(
                "UPDATE cross_owner_outbox SET state = 'acked', fence = ?, worker_id = NULL,
                 lease_until_ms = NULL, acknowledgement_digest = ?, updated_at_ms = ?,
                 terminal_at_ms = COALESCE(terminal_at_ms, ?)
                 WHERE destination = ? AND scope_id = ? AND operation_id = ?",
            )
            .bind(to_i64(fence)?)
            .bind(receipt.evidence_digest.as_array().as_slice())
            .bind(now)
            .bind(now)
            .bind(operation.intent.destination.as_str())
            .bind(scope_id.as_str())
            .bind(operation_id.as_str())
            .execute(&mut *tx)
            .await
            .map_err(sqlx_error)?;
        }''',
    path,
)
write(path, text)

# ---------------------------------------------------------------------------
# Cross-language digest domain migration + generated vectors + TypeScript oracle
# ---------------------------------------------------------------------------
import json
import runpy

vector_py = ROOT / "qualification/cognitive-types-v1/verify_vectors.py"
text = read(vector_py)
text = replace_once(
    text,
    '''DOMAIN = b"hepta.cognitive.contract.canonical-json.v1\\0"''',
    '''DOMAIN = b"hepta.cognitive.contract.canonical-json\\0"
SCHEMA_VERSION = b"1"
CANONICALIZATION_ALGORITHM = (
    b"canonical_json_utf8_sorted_object_keys_integer_only_no_unicode_normalization_v1"
)''',
    vector_py,
)
text = replace_once(
    text,
    '''def semantic_digest(contract: str, payload: object) -> str:
    return hashlib.sha256(
        DOMAIN + contract.encode("ascii") + b"\\0" + canonical(payload)
    ).hexdigest()''',
    '''def semantic_digest(contract: str, schema: str, payload: object) -> str:
    return hashlib.sha256(
        DOMAIN
        + schema.encode("ascii")
        + b"\\0"
        + SCHEMA_VERSION
        + b"\\0"
        + CANONICALIZATION_ALGORITHM
        + b"\\0"
        + contract.encode("ascii")
        + b"\\0"
        + canonical(payload)
    ).hexdigest()''',
    vector_py,
)
text = replace_once(
    text,
    '''        actual = semantic_digest(contract, payload)''',
    '''        actual = semantic_digest(contract, schema, payload)''',
    vector_py,
)
write(vector_py, text)

namespace = runpy.run_path(str(vector_py), run_name="cognitive_types_vector_migration")
vectors = namespace["VECTORS"]
semantic_digest = namespace["semantic_digest"]
updated = []
for contract, schema, payload, old_digest in vectors:
    updated.append(
        {
            "contract": contract,
            "schema": schema,
            "schemaVersion": 1,
            "canonicalizationAlgorithm": (
                "canonical_json_utf8_sorted_object_keys_integer_only_"
                "no_unicode_normalization_v1"
            ),
            "payload": payload,
            "digest": semantic_digest(contract, schema, payload),
        }
    )

# Replace old digest literals in both independent Python fixture and Rust golden tests.
python_text = read(vector_py)
rust_tests = ROOT / "codex-rs/hepta-cognitive-types/src/contract_tests.rs"
rust_text = read(rust_tests)
for (contract, schema, payload, old_digest), row in zip(vectors, updated, strict=True):
    new_digest = row["digest"]
    if python_text.count(old_digest) != 1:
        raise SystemExit(f"{vector_py}: expected one old digest for {contract}")
    python_text = python_text.replace(old_digest, new_digest)
    if old_digest not in rust_text:
        raise SystemExit(f"{rust_tests}: missing old digest for {contract}")
    rust_text = rust_text.replace(old_digest, new_digest)
write(vector_py, python_text)
write(rust_tests, rust_text)

vectors_json = ROOT / "qualification/cognitive-types-v1/vectors.json"
write(
    vectors_json,
    json.dumps(
        {
            "schema": "hepta.cognitive-types.cross-language-vectors.v1",
            "schemaVersion": 1,
            "unicodeNormalization": "none_codepoint_exact",
            "vectors": updated,
        },
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    )
    + "\n",
)

typescript = r'''#!/usr/bin/env -S node --experimental-strip-types
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
type Vector = {
  contract: string;
  schema: string;
  schemaVersion: number;
  canonicalizationAlgorithm: string;
  payload: Json;
  digest: string;
};

function canonical(value: Json): string {
  if (value === null || typeof value === "boolean" || typeof value === "string") {
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value)) throw new Error("non-integer or unsafe JSON number");
    return String(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map(canonical).join(",")}]`;
  }
  const keys = Object.keys(value).sort();
  return `{${keys.map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
}

function digest(vector: Vector): string {
  const chunks = [
    Buffer.from("hepta.cognitive.contract.canonical-json\0", "utf8"),
    Buffer.from(vector.schema, "ascii"),
    Buffer.from("\0", "utf8"),
    Buffer.from(String(vector.schemaVersion), "ascii"),
    Buffer.from("\0", "utf8"),
    Buffer.from(vector.canonicalizationAlgorithm, "ascii"),
    Buffer.from("\0", "utf8"),
    Buffer.from(vector.contract, "ascii"),
    Buffer.from("\0", "utf8"),
    Buffer.from(canonical(vector.payload), "utf8"),
  ];
  return createHash("sha256").update(Buffer.concat(chunks)).digest("hex");
}

const here = dirname(fileURLToPath(import.meta.url));
const document = JSON.parse(
  readFileSync(join(here, "vectors.json"), "utf8"),
) as { unicodeNormalization: string; vectors: Vector[] };

if (document.unicodeNormalization !== "none_codepoint_exact") {
  throw new Error("unexpected Unicode normalization policy");
}
const observed: Record<string, string> = {};
for (const vector of document.vectors) {
  const actual = digest(vector);
  if (actual !== vector.digest) {
    throw new Error(`${vector.contract} digest mismatch: ${actual}`);
  }
  observed[vector.contract] = actual;
}
console.log(JSON.stringify({
  status: "PASS_COGNITIVE_TYPES_V1_TYPESCRIPT_VECTOR",
  vectorCount: document.vectors.length,
  digests: observed,
}));
'''
write(ROOT / "qualification/cognitive-types-v1/verify_vectors.ts", typescript)

# ---------------------------------------------------------------------------
# Stable structured errors and executable consumer convergence registry
# ---------------------------------------------------------------------------
structured = r'''//! Stable machine-readable cognitive contract failures.

use std::fmt;

use crate::hnmf::HnmfContractError;
use crate::lane_c::LaneCContractError;
use crate::wire::CognitiveWireError;

pub const MAX_CONTRACT_FIELD_PATH_BYTES_V1: usize = 256;

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
#[repr(u16)]
pub enum ContractErrorCodeV1 {
    ZeroValue = 1,
    InvalidValue = 2,
    Conflict = 3,
    Missing = 4,
    DuplicateIdentity = 5,
    LimitExceeded = 6,
    EmptyCollection = 7,
    EmptyDigest = 8,
    DigestMismatch = 9,
    InvalidState = 10,
    AuthorityGranted = 11,
    JsonInvalid = 12,
    SchemaMismatch = 13,
    VersionMismatch = 14,
    ContractMismatch = 15,
    UnregisteredContract = 16,
    NonCanonicalInput = 17,
    NonIntegerNumber = 18,
    PayloadLength = 19,
    EnvelopeLength = 20,
}

impl ContractErrorCodeV1 {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::ZeroValue => "zero_value",
            Self::InvalidValue => "invalid_value",
            Self::Conflict => "conflict",
            Self::Missing => "missing",
            Self::DuplicateIdentity => "duplicate_identity",
            Self::LimitExceeded => "limit_exceeded",
            Self::EmptyCollection => "empty_collection",
            Self::EmptyDigest => "empty_digest",
            Self::DigestMismatch => "digest_mismatch",
            Self::InvalidState => "invalid_state",
            Self::AuthorityGranted => "authority_granted",
            Self::JsonInvalid => "json_invalid",
            Self::SchemaMismatch => "schema_mismatch",
            Self::VersionMismatch => "version_mismatch",
            Self::ContractMismatch => "contract_mismatch",
            Self::UnregisteredContract => "unregistered_contract",
            Self::NonCanonicalInput => "noncanonical_input",
            Self::NonIntegerNumber => "non_integer_number",
            Self::PayloadLength => "payload_length",
            Self::EnvelopeLength => "envelope_length",
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContractFieldPathV1(String);

impl ContractFieldPathV1 {
    pub fn new(value: impl Into<String>) -> Result<Self, ContractFieldPathErrorV1> {
        let value = value.into();
        if value.trim().is_empty()
            || value.len() > MAX_CONTRACT_FIELD_PATH_BYTES_V1
            || value.chars().any(char::is_control)
        {
            return Err(ContractFieldPathErrorV1);
        }
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ContractFieldPathErrorV1;

impl fmt::Display for ContractFieldPathErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("invalid cognitive contract field path")
    }
}

impl std::error::Error for ContractFieldPathErrorV1 {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContractViolationV1 {
    pub code: ContractErrorCodeV1,
    pub field_path: Option<ContractFieldPathV1>,
    pub detail: String,
}

pub trait StructuredContractErrorV1 {
    fn contract_error_code(&self) -> ContractErrorCodeV1;
    fn contract_field_path(&self) -> Option<&str>;

    fn to_contract_violation(&self) -> ContractViolationV1
    where
        Self: fmt::Display,
    {
        ContractViolationV1 {
            code: self.contract_error_code(),
            field_path: self
                .contract_field_path()
                .and_then(|path| ContractFieldPathV1::new(path).ok()),
            detail: self.to_string(),
        }
    }
}

impl StructuredContractErrorV1 for HnmfContractError {
    fn contract_error_code(&self) -> ContractErrorCodeV1 {
        match self {
            Self::ZeroValue(_) => ContractErrorCodeV1::ZeroValue,
            Self::Invalid(_) => ContractErrorCodeV1::InvalidValue,
            Self::Conflict(_) => ContractErrorCodeV1::Conflict,
            Self::Missing(_) => ContractErrorCodeV1::Missing,
            Self::DuplicateIdentity(_) => ContractErrorCodeV1::DuplicateIdentity,
            Self::LimitExceeded { .. } => ContractErrorCodeV1::LimitExceeded,
        }
    }

    fn contract_field_path(&self) -> Option<&str> {
        match self {
            Self::ZeroValue(path)
            | Self::Invalid(path)
            | Self::Conflict(path)
            | Self::Missing(path)
            | Self::DuplicateIdentity(path) => Some(path),
            Self::LimitExceeded { field, .. } => Some(field),
        }
    }
}

impl StructuredContractErrorV1 for LaneCContractError {
    fn contract_error_code(&self) -> ContractErrorCodeV1 {
        match self {
            Self::EmptyCollection(_) => ContractErrorCodeV1::EmptyCollection,
            Self::ZeroValue(_) => ContractErrorCodeV1::ZeroValue,
            Self::EmptyDigest(_) => ContractErrorCodeV1::EmptyDigest,
            Self::DuplicateIdentity(_) => ContractErrorCodeV1::DuplicateIdentity,
            Self::DigestMismatch(_) => ContractErrorCodeV1::DigestMismatch,
            Self::InvalidState(_) => ContractErrorCodeV1::InvalidState,
            Self::AuthorityGranted => ContractErrorCodeV1::AuthorityGranted,
            Self::LimitExceeded { .. } => ContractErrorCodeV1::LimitExceeded,
        }
    }

    fn contract_field_path(&self) -> Option<&str> {
        match self {
            Self::EmptyCollection(path)
            | Self::ZeroValue(path)
            | Self::EmptyDigest(path)
            | Self::DuplicateIdentity(path)
            | Self::DigestMismatch(path)
            | Self::InvalidState(path) => Some(path),
            Self::AuthorityGranted => None,
            Self::LimitExceeded { field, .. } => Some(field),
        }
    }
}

impl StructuredContractErrorV1 for CognitiveWireError {
    fn contract_error_code(&self) -> ContractErrorCodeV1 {
        match self {
            Self::Contract(error) => error.contract_error_code(),
            Self::Json(_) => ContractErrorCodeV1::JsonInvalid,
            Self::SchemaMismatch => ContractErrorCodeV1::SchemaMismatch,
            Self::VersionMismatch(_) => ContractErrorCodeV1::VersionMismatch,
            Self::ContractMismatch => ContractErrorCodeV1::ContractMismatch,
            Self::UnregisteredContract => ContractErrorCodeV1::UnregisteredContract,
            Self::NonCanonicalInput => ContractErrorCodeV1::NonCanonicalInput,
            Self::NonIntegerNumber => ContractErrorCodeV1::NonIntegerNumber,
            Self::PayloadLength { .. } => ContractErrorCodeV1::PayloadLength,
            Self::EnvelopeLength { .. } => ContractErrorCodeV1::EnvelopeLength,
        }
    }

    fn contract_field_path(&self) -> Option<&str> {
        match self {
            Self::Contract(error) => error.contract_field_path(),
            Self::SchemaMismatch => Some("schema"),
            Self::VersionMismatch(_) => Some("schemaVersion"),
            Self::ContractMismatch | Self::UnregisteredContract => Some("contract"),
            Self::PayloadLength { .. } => Some("payload"),
            Self::EnvelopeLength { .. } => Some("envelope"),
            Self::Json(_)
            | Self::NonCanonicalInput
            | Self::NonIntegerNumber => None,
        }
    }
}
'''
write(ROOT / "codex-rs/hepta-cognitive-types/src/structured.rs", structured)

convergence = r'''//! Executable canonical-consumer convergence inventory.
//!
//! Local compatibility values listed here are explicitly non-wire and
//! non-authoritative. A cutover is allowed only after every named gate passes.

use std::collections::BTreeSet;

use codex_hepta_types::Digest32;

use crate::wire::CognitiveWireError;
use crate::wire::RegisteredCognitiveContractV1;
use crate::wire::decode_registered_wire_v1;

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum CognitiveConsumerIdV1 {
    CognitiveRead,
    CognitiveStore,
    MemoryRetrieval,
    CompactEngine,
    IntelligenceControl,
}

impl CognitiveConsumerIdV1 {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::CognitiveRead => "cognitive.read",
            Self::CognitiveStore => "cognitive.store",
            Self::MemoryRetrieval => "memory.retrieval",
            Self::CompactEngine => "compact.engine",
            Self::IntelligenceControl => "intelligence.control",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LocalSurfaceClassV1 {
    NonWireNonAuthorityCompatibility,
    CanonicalWireConsumer,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CanonicalCutoverGateV1 {
    CanonicalAdapterCompiled,
    ShadowDigestMatched,
    AuthenticatedWireIngress,
    ExactHeadQualified,
    SyntheticMergeQualified,
    RollbackExercised,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CognitiveConsumerConvergenceV1 {
    pub consumer: CognitiveConsumerIdV1,
    pub owner: &'static str,
    pub legacy_surface: &'static str,
    pub local_surface_class: LocalSurfaceClassV1,
    pub canonical_schemas: &'static [&'static str],
    pub shadow_mismatch_metric: &'static str,
    pub cutover_gates: &'static [CanonicalCutoverGateV1],
    pub rollback_path: &'static str,
}

const FULL_GATES: &[CanonicalCutoverGateV1] = &[
    CanonicalCutoverGateV1::CanonicalAdapterCompiled,
    CanonicalCutoverGateV1::ShadowDigestMatched,
    CanonicalCutoverGateV1::AuthenticatedWireIngress,
    CanonicalCutoverGateV1::ExactHeadQualified,
    CanonicalCutoverGateV1::SyntheticMergeQualified,
    CanonicalCutoverGateV1::RollbackExercised,
];

pub const COGNITIVE_CONSUMER_CONVERGENCE_V1: &[CognitiveConsumerConvergenceV1] = &[
    CognitiveConsumerConvergenceV1 {
        consumer: CognitiveConsumerIdV1::CognitiveRead,
        owner: "cognitive-read",
        legacy_surface: "MemoryRecord/CognitiveSnapshot",
        local_surface_class: LocalSurfaceClassV1::NonWireNonAuthorityCompatibility,
        canonical_schemas: &[
            "hepta.hnmf.memory-event.v1",
            "hepta.hnmf.cross-modal-binding.v1",
            "hepta.hnmf.forget-propagation-receipt.v1",
        ],
        shadow_mismatch_metric: "hepta.cognitive_types.shadow_mismatch.cognitive_read",
        cutover_gates: FULL_GATES,
        rollback_path: "disable canonical-read cutover and resume generation-bound compatibility reads",
    },
    CognitiveConsumerConvergenceV1 {
        consumer: CognitiveConsumerIdV1::CognitiveStore,
        owner: "cognitive-store",
        legacy_surface: "MemoryRecord/Lane-C local write contracts",
        local_surface_class: LocalSurfaceClassV1::NonWireNonAuthorityCompatibility,
        canonical_schemas: &[
            "hepta.hnmf.memory-event.v1",
            "hepta.hnmf.modality-span-ref.v1",
        ],
        shadow_mismatch_metric: "hepta.cognitive_types.shadow_mismatch.cognitive_store",
        cutover_gates: FULL_GATES,
        rollback_path: "disable canonical writer façade while preserving immutable admission journal",
    },
    CognitiveConsumerConvergenceV1 {
        consumer: CognitiveConsumerIdV1::MemoryRetrieval,
        owner: "memory-retrieval",
        legacy_surface: "generation_bound::RecallPacketV1",
        local_surface_class: LocalSurfaceClassV1::NonWireNonAuthorityCompatibility,
        canonical_schemas: &[
            "hepta.hnmf.memory-cue.v1",
            "hepta.hnmf.recall-packet.v1",
        ],
        shadow_mismatch_metric: "hepta.cognitive_types.shadow_mismatch.memory_retrieval",
        cutover_gates: FULL_GATES,
        rollback_path: "disable canonical recall projection and retain generation-bound result",
    },
    CognitiveConsumerConvergenceV1 {
        consumer: CognitiveConsumerIdV1::CompactEngine,
        owner: "compact-engine",
        legacy_surface: "MemoryRecord/Lane-C compaction proof",
        local_surface_class: LocalSurfaceClassV1::NonWireNonAuthorityCompatibility,
        canonical_schemas: &[
            "hepta.hnmf.memory-event.v1",
            "hepta.hnmf.forget-propagation-receipt.v1",
        ],
        shadow_mismatch_metric: "hepta.cognitive_types.shadow_mismatch.compact_engine",
        cutover_gates: FULL_GATES,
        rollback_path: "retain predecessor checkpoint and reject canonical compact publication",
    },
    CognitiveConsumerConvergenceV1 {
        consumer: CognitiveConsumerIdV1::IntelligenceControl,
        owner: "intelligence-control",
        legacy_surface: "CognitiveSnapshot",
        local_surface_class: LocalSurfaceClassV1::NonWireNonAuthorityCompatibility,
        canonical_schemas: &[
            "hepta.hnmf.recall-packet.v1",
            "hepta.hnmf.outcome-signal.v1",
        ],
        shadow_mismatch_metric: "hepta.cognitive_types.shadow_mismatch.intelligence_control",
        cutover_gates: FULL_GATES,
        rollback_path: "reject canonical attachment and retain prior verified control snapshot",
    },
];

pub fn validate_consumer_convergence_registry_v1() -> Result<(), &'static str> {
    let mut consumers = BTreeSet::new();
    let mut metrics = BTreeSet::new();
    for row in COGNITIVE_CONSUMER_CONVERGENCE_V1 {
        if !consumers.insert(row.consumer)
            || !metrics.insert(row.shadow_mismatch_metric)
            || row.owner.is_empty()
            || row.legacy_surface.is_empty()
            || row.canonical_schemas.is_empty()
            || row.cutover_gates != FULL_GATES
            || row.rollback_path.is_empty()
        {
            return Err("invalid cognitive consumer convergence registry");
        }
    }
    if consumers.len() != 5 {
        return Err("incomplete cognitive consumer convergence registry");
    }
    Ok(())
}

/// Authenticated closed-world ingress. Unknown schema/contract pairs reject
/// before a caller can observe a typed payload.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthenticatedCanonicalEnvelopeV1 {
    contract: RegisteredCognitiveContractV1,
    wire_digest: Digest32,
}

impl AuthenticatedCanonicalEnvelopeV1 {
    pub fn decode(bytes: &[u8]) -> Result<Self, CognitiveWireError> {
        let contract = decode_registered_wire_v1(bytes)?;
        Ok(Self {
            contract,
            wire_digest: Digest32::of_bytes(bytes),
        })
    }

    pub fn contract(&self) -> &RegisteredCognitiveContractV1 {
        &self.contract
    }

    pub const fn wire_digest(&self) -> Digest32 {
        self.wire_digest
    }
}
'''
write(ROOT / "codex-rs/hepta-cognitive-types/src/convergence.rs", convergence)

lib_rs = ROOT / "codex-rs/hepta-cognitive-types/src/lib.rs"
text = read(lib_rs)
anchor = '''pub mod hnmf;
pub mod hnmf_learning;
pub mod lane_c;
pub mod wire;'''
replacement = '''pub mod convergence;
pub mod hnmf;
pub mod hnmf_learning;
pub mod lane_c;
pub mod structured;
pub mod wire;'''
text = replace_once(text, anchor, replacement, lib_rs)
write(lib_rs, text)

# ---------------------------------------------------------------------------
# Focused semantic, API-safety, registry and adversarial tests
# ---------------------------------------------------------------------------
lane_tests = ROOT / "codex-rs/hepta-cognitive-types/src/lane_c_tests.rs"
text = read(lane_tests)
text += r'''

fn write_intent() -> MemoryWriteIntentV1 {
    MemoryWriteIntentV1 {
        intent_id: id("intent:1"),
        candidate_digest: digest("candidate"),
        expected_snapshot: snapshot_key(),
        writer_fence_digest: digest("writer-fence"),
        authorization_digest: digest("authorization"),
    }
}

#[test]
fn memory_write_receipt_binds_exact_intent_and_uses_tagged_outcome() {
    let intent = write_intent();
    let binding = intent.receipt_binding().expect("valid binding");
    let receipt = MemoryWriteReceiptV1::committed(
        binding,
        id("record:1"),
        digest("record"),
        intent.expected_snapshot.vector.memory_ledger_frontier,
        intent.expected_snapshot.clone(),
        MemoryWriteDisposition::Inserted,
    )
    .expect("valid committed receipt");
    receipt.validate().expect("receipt validates");
    assert_eq!(receipt.intent_digest(), intent.intent_digest().expect("intent digest"));
    assert_eq!(receipt.candidate_digest(), intent.candidate_digest);
    assert_eq!(receipt.authorization_digest(), intent.authorization_digest);
    assert_eq!(receipt.writer_fence_digest(), intent.writer_fence_digest);
    assert_eq!(receipt.record_id(), Some(&id("record:1")));
    assert_eq!(receipt.record_digest(), Some(digest("record")));
    assert_ne!(receipt.receipt_digest(), Digest32::ZERO);
}

#[test]
fn rejected_memory_write_receipt_cannot_carry_fake_record_fields() {
    let intent = write_intent();
    let receipt = MemoryWriteReceiptV1::rejected(
        intent.receipt_binding().expect("binding"),
        MemoryWriteRejectionCodeV1::AuthorizationDenied,
        Some("authorizationDigest".to_string()),
        Some(intent.expected_snapshot.clone()),
    )
    .expect("valid rejected receipt");
    receipt.validate().expect("rejection validates");
    assert_eq!(receipt.record_id(), None);
    assert_eq!(receipt.record_digest(), None);
    assert_eq!(receipt.committed_frontier(), None);
    assert_eq!(receipt.disposition(), MemoryWriteDisposition::Rejected);
}

#[test]
fn memory_write_receipt_tampering_is_detected() {
    let intent = write_intent();
    let mut receipt = MemoryWriteReceiptV1::committed(
        intent.receipt_binding().expect("binding"),
        id("record:1"),
        digest("record"),
        intent.expected_snapshot.vector.memory_ledger_frontier,
        intent.expected_snapshot,
        MemoryWriteDisposition::Inserted,
    )
    .expect("valid receipt");
    receipt.corrupt_record_digest_for_test(digest("other-record"));
    assert_eq!(
        receipt.validate(),
        Err(LaneCContractError::DigestMismatch("memory_write_receipt"))
    );
}

#[test]
fn federation_completeness_is_bound_to_coverage_and_items() {
    let mut result = FederatedEvidenceResultV1 {
        query_id: id("query:complete"),
        peer_id: id("peer:1"),
        observed_snapshot: snapshot_key(),
        items: vec![FederatedEvidenceItemV1 {
            source_owner_id: id("owner:1"),
            record_id: id("record:1"),
            record_revision: revision(1),
            record_digest: digest("record"),
            support_digest: digest("support"),
            validity_digest: digest("validity"),
        }],
        coverage: FederatedCoverageV1 {
            requested_peers: 1,
            completed_peers: 1,
            failed_peers: 0,
            truncated_items: 0,
        },
        completeness: FederatedCompletenessV1::Complete,
        validity: FederatedValidityV1::Valid,
        expires_unix_ms: 10,
        result_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    result.result_digest = result.compute_result_digest();
    result.validate().expect("complete result");

    result.coverage.failed_peers = 1;
    result.result_digest = result.compute_result_digest();
    assert_eq!(
        result.validate(),
        Err(LaneCContractError::InvalidState("federated_complete_coverage"))
    );

    result.coverage = FederatedCoverageV1 {
        requested_peers: 1,
        completed_peers: 1,
        failed_peers: 0,
        truncated_items: 0,
    };
    result.completeness = FederatedCompletenessV1::Empty;
    result.result_digest = result.compute_result_digest();
    assert_eq!(
        result.validate(),
        Err(LaneCContractError::InvalidState("federated_empty_result"))
    );
}
'''
write(lane_tests, text)

contract_tests = ROOT / "codex-rs/hepta-cognitive-types/src/contract_tests.rs"
text = read(contract_tests)
text += r'''

#[test]
fn selector_manifests_require_authenticated_membership() {
    let mut ast = text_span();
    ast.modality = ModalityKindV1::CodeAst;
    ast.range = SpanRangeV1::AstPath {
        path: "crate/items/0".to_string(),
    };
    let manifest = AssetManifestV1 {
        asset_sha256: ast.asset_sha256,
        modality: ModalityKindV1::CodeAst,
        extent: AssetExtentV1::CodeAst {
            selector_index_sha256: digest('f'),
            valid_paths: BTreeSet::from(["crate/items/0".to_string()]),
        },
        preprocessor_manifest_sha256: ast.preprocessor_manifest_sha256,
    };
    validate_span_against_manifest_v1(&manifest, &ast).expect("indexed AST selector");

    ast.range = SpanRangeV1::AstPath {
        path: "crate/items/1".to_string(),
    };
    assert_eq!(
        validate_span_against_manifest_v1(&manifest, &ast),
        Err(HnmfContractError::Invalid("span exceeds asset extent"))
    );

    let mut structured = text_span();
    structured.modality = ModalityKindV1::StructuredData;
    structured.range = SpanRangeV1::JsonPointer {
        pointer: "/valid~1key".to_string(),
    };
    let structured_manifest = AssetManifestV1 {
        asset_sha256: structured.asset_sha256,
        modality: ModalityKindV1::StructuredData,
        extent: AssetExtentV1::StructuredData {
            selector_index_sha256: digest('e'),
            valid_pointers: BTreeSet::from(["/valid~1key".to_string()]),
        },
        preprocessor_manifest_sha256: structured.preprocessor_manifest_sha256,
    };
    validate_span_against_manifest_v1(&structured_manifest, &structured)
        .expect("indexed JSON pointer");

    structured.range = SpanRangeV1::JsonPointer {
        pointer: "/invalid~2escape".to_string(),
    };
    assert_eq!(
        structured.validate(),
        Err(HnmfContractError::Invalid("JSON pointer escape"))
    );
}

#[test]
fn synapse_relation_sign_and_fixed_eligibility_fail_closed() {
    let mut value = synapse();
    value.relation = SynapseRelationV1::Inhibitory;
    assert_eq!(
        value.validate(),
        Err(HnmfContractError::Conflict("synapse relation/weight sign"))
    );

    value.weight_q16 = -100;
    value.plasticity_class = PlasticityClassV1::Fixed;
    value.eligibility_ppm = 1;
    assert_eq!(
        value.validate(),
        Err(HnmfContractError::Conflict("fixed synapse eligibility"))
    );
}

#[test]
fn topology_and_forget_receipts_bind_semantic_deltas() {
    let mut proposal = topology();
    proposal.resource_delta.node_delta = 0;
    assert_eq!(
        proposal.validate(),
        Err(HnmfContractError::Conflict("topology operation/resource delta"))
    );

    let mut receipt = forget();
    receipt.retired_node_ids.clear();
    assert_eq!(
        receipt.validate(),
        Err(HnmfContractError::Invalid("empty forget propagation delta"))
    );
}

#[test]
fn unicode_policy_is_explicit_and_codepoint_exact() {
    assert_eq!(UNICODE_NORMALIZATION_POLICY_V1, "none_codepoint_exact");
    let mut nfc = event();
    nfc.semantic_keys = BTreeSet::from(["é".to_string()]);
    let mut nfd = event();
    nfd.semantic_keys = BTreeSet::from(["e\u{301}".to_string()]);
    assert_ne!(
        canonical_contract_digest_v1(&nfc).expect("NFC digest"),
        canonical_contract_digest_v1(&nfd).expect("NFD digest")
    );
}

#[test]
fn closed_world_decoder_rejects_unregistered_contracts() {
    let encoded = encode_wire_v1(&text_span()).expect("registered span");
    assert!(matches!(
        decode_registered_wire_v1(&encoded),
        Ok(RegisteredCognitiveContractV1::ModalitySpanRef(_))
    ));

    let unknown = String::from_utf8(encoded)
        .expect("utf8")
        .replace("ModalitySpanRefV1", "UnknownContractV1");
    assert!(matches!(
        decode_registered_wire_v1(unknown.as_bytes()),
        Err(CognitiveWireError::UnregisteredContract)
            | Err(CognitiveWireError::NonCanonicalInput)
    ));
}

#[test]
fn convergence_registry_and_structured_errors_are_machine_readable() {
    crate::convergence::validate_consumer_convergence_registry_v1()
        .expect("complete consumer convergence registry");
    assert_eq!(
        crate::convergence::COGNITIVE_CONSUMER_CONVERGENCE_V1.len(),
        5
    );

    use crate::structured::ContractErrorCodeV1;
    use crate::structured::StructuredContractErrorV1;
    let error = HnmfContractError::LimitExceeded {
        field: "selectedEvents",
        actual: 17,
        maximum: 16,
    };
    let violation = error.to_contract_violation();
    assert_eq!(violation.code, ContractErrorCodeV1::LimitExceeded);
    assert_eq!(
        violation.field_path.as_ref().map(|path| path.as_str()),
        Some("selectedEvents")
    );
}

#[test]
fn validated_wrapper_is_required_for_unchecked_reuse() {
    let validated = Validated::new(text_span()).expect("validated span");
    assert_eq!(
        validated.digest().expect("validated digest"),
        canonical_contract_digest_v1(validated.get()).expect("checked digest")
    );
    assert_eq!(
        validated.encode_wire().expect("validated wire"),
        encode_wire_v1(validated.get()).expect("checked wire")
    );
}
'''
write(contract_tests, text)

# ---------------------------------------------------------------------------
# Store canonical wire ingress and test migrations
# ---------------------------------------------------------------------------
store_v2 = ROOT / "codex-rs/hepta-cognitive-store/src/v2.rs"
text = read(store_v2)
text = replace_once(
    text,
    '''use codex_hepta_cognitive_types::hnmf::MemoryEventV1;''',
    '''use codex_hepta_cognitive_types::hnmf::MemoryEventV1;
use codex_hepta_cognitive_types::wire::decode_wire_v1;''',
    store_v2,
)
needle = '''    /// Append through the existing authoritative semantic ledger while
    /// emitting a side-by-side canonical MemoryEventV1 co-observation receipt.'''
insert = '''    /// Strict closed-schema canonical ingress for writer callers. Unknown
    /// fields, schemas, versions, contracts and non-canonical JSON reject
    /// before the store authority verifier is invoked.
    pub fn append_admitted_with_canonical_wire<V: StoreAuthorityVerifierV2>(
        &mut self,
        verifier: &V,
        candidate: MemoryAdmissionCandidateV1,
        intent: MemoryWriteIntentV1,
        event_wire: &[u8],
    ) -> Result<CanonicalMemoryEventShadowWriteV1, CognitiveStoreV2Error> {
        let event = decode_wire_v1::<MemoryEventV1>(event_wire)
            .map_err(|error| CognitiveStoreV2Error::CanonicalContract(error.to_string()))?;
        self.append_admitted_with_canonical_shadow(verifier, candidate, intent, event)
    }

    /// Append through the existing authoritative semantic ledger while
    /// emitting a side-by-side canonical MemoryEventV1 co-observation receipt.'''
text = replace_once(text, needle, insert, store_v2)
write(store_v2, text)

store_tests = ROOT / "codex-rs/hepta-cognitive-store/src/v2_tests.rs"
text = read(store_tests)
text = text.replace(
    "assert_eq!(first_receipt.committed_frontier, 2);",
    'assert_eq!(first_receipt.committed_frontier(), Some(2));',
)
text = text.replace(
    "assert_eq!(first_receipt.snapshot_key.vector.knowledge_fact_frontier, 2);",
    '''assert_eq!(
        first_receipt
            .snapshot_key()
            .expect("committed snapshot")
            .vector
            .knowledge_fact_frontier,
        2
    );''',
)
text = text.replace(
    "assert_eq!(second_receipt.committed_frontier, 3);",
    'assert_eq!(second_receipt.committed_frontier(), Some(3));',
)
text += r'''

#[test]
fn canonical_wire_ingress_rejects_noncanonical_or_wrong_schema_before_write() {
    use codex_hepta_cognitive_types::wire::encode_wire_v1;

    let mut store = store();
    let candidate = candidate(
        "memory:wire",
        "content:wire",
        MemoryAdmissionKind::Observation,
    );
    let intent = intent(&store, "intent:wire", &candidate);
    let event = canonical_event("memory:wire");
    let wire = encode_wire_v1(&event).expect("canonical event wire");
    let result = store
        .append_admitted_with_canonical_wire(&Verifier, candidate, intent, &wire)
        .expect("canonical ingress");
    assert_eq!(
        result.write_receipt.disposition(),
        MemoryWriteDisposition::Inserted
    );

    let mut store = store();
    let candidate = candidate(
        "memory:wire:bad",
        "content:wire:bad",
        MemoryAdmissionKind::Observation,
    );
    let intent = intent(&store, "intent:wire:bad", &candidate);
    let event = canonical_event("memory:wire:bad");
    let canonical = String::from_utf8(encode_wire_v1(&event).expect("wire")).expect("utf8");
    let noncanonical = format!(" {canonical}");
    assert!(matches!(
        store.append_admitted_with_canonical_wire(
            &Verifier,
            candidate,
            intent,
            noncanonical.as_bytes(),
        ),
        Err(CognitiveStoreV2Error::CanonicalContract(_))
    ));
    assert!(store.current_head(&id("memory:wire:bad")).is_none());
}
'''
write(store_tests, text)

# Align newly appended assertions with the implementation's stable details.
contract_tests = ROOT / "codex-rs/hepta-cognitive-types/src/contract_tests.rs"
text = read(contract_tests)
text = text.replace(
    'HnmfContractError::Conflict("synapse relation/weight sign")',
    'HnmfContractError::Conflict("synapse relation/weight")',
)
text = text.replace(
    'HnmfContractError::Conflict("fixed synapse eligibility")',
    'HnmfContractError::Conflict("fixed synapse has eligibility")',
)
text = text.replace(
    'HnmfContractError::Conflict("topology operation/resource delta")',
    'HnmfContractError::Conflict("topology add delta")',
)
text = text.replace(
    'HnmfContractError::Invalid("empty forget propagation delta")',
    'HnmfContractError::Invalid("empty forget propagation")',
)
write(contract_tests, text)

# sqlx::Error's zero-connection guard uses a protocol error rather than a boxed
# configuration source.
state_sqlite = ROOT / "codex-rs/state/src/sqlite.rs"
text = read(state_sqlite)
text = text.replace(
    '''return Err(Error::Configuration(
            "maximum_connections must be non-zero".into(),
        ));''',
    '''return Err(Error::Protocol(
            "maximum_connections must be non-zero".to_string(),
        ));''',
)
write(state_sqlite, text)
