//! Revision-bound `cognitive.read` ingress for context compiler V2.
//!
//! This adapter verifies a complete canonical shadow and binds every V2
//! candidate to the exact event/provenance source row. It does not mint an
//! admission, classify secrets, serialize context, or grant final-use authority.
//! Those checks remain owned by the existing context admission and provider
//! boundaries.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_cognitive_read::CanonicalAuthoritativeReadShadowV2;
use codex_hepta_cognitive_read::CanonicalReadShadowRowV2;
use codex_hepta_cognitive_read::CanonicalReadShadowV2Error;
use codex_hepta_cognitive_types::hnmf::MemoryLifecycleV1;
use codex_hepta_cognitive_types::hnmf::MemoryVerificationStateV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CompiledContextV2;
use crate::ContextCompilationRequestV2;
use crate::ContextCompilerV2Error;
use crate::ContextRoleV2;
use crate::MAX_CONTEXT_CANDIDATES_V2;
use crate::compile_v2;

const COGNITIVE_READ_INGRESS_ROW_DOMAIN: &[u8] =
    b"hepta.context.cognitive-read-ingress-row.v2";
const COGNITIVE_READ_INGRESS_DOMAIN: &[u8] = b"hepta.context.cognitive-read-ingress.v2";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CognitiveReadIngressRowV2 {
    item_id: StableId,
    source_digest: Digest32,
    event_digest: Digest32,
    legacy_record_id: StableId,
    legacy_record_revision: u64,
}

impl CognitiveReadIngressRowV2 {
    #[must_use]
    pub fn item_id(&self) -> &StableId {
        &self.item_id
    }

    #[must_use]
    pub const fn source_digest(&self) -> Digest32 {
        self.source_digest
    }

    #[must_use]
    pub const fn event_digest(&self) -> Digest32 {
        self.event_digest
    }

    #[must_use]
    pub fn legacy_record_id(&self) -> &StableId {
        &self.legacy_record_id
    }

    #[must_use]
    pub const fn legacy_record_revision(&self) -> u64 {
        self.legacy_record_revision
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedCognitiveReadIngressV2 {
    shadow_binding_digest: Digest32,
    read_receipt_digest: Digest32,
    generation_vector_digest: Digest32,
    rows: Vec<CognitiveReadIngressRowV2>,
    ingress_digest: Digest32,
    authority: AuthorityPosture,
}

impl VerifiedCognitiveReadIngressV2 {
    #[must_use]
    pub const fn shadow_binding_digest(&self) -> Digest32 {
        self.shadow_binding_digest
    }

    #[must_use]
    pub const fn read_receipt_digest(&self) -> Digest32 {
        self.read_receipt_digest
    }

    #[must_use]
    pub const fn generation_vector_digest(&self) -> Digest32 {
        self.generation_vector_digest
    }

    #[must_use]
    pub fn rows(&self) -> &[CognitiveReadIngressRowV2] {
        &self.rows
    }

    #[must_use]
    pub const fn ingress_digest(&self) -> Digest32 {
        self.ingress_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }

    pub fn validate(&self) -> Result<(), CognitiveReadIngressError> {
        for digest in [
            self.shadow_binding_digest,
            self.read_receipt_digest,
            self.generation_vector_digest,
            self.ingress_digest,
        ] {
            if digest.is_zero() {
                return Err(CognitiveReadIngressError::EmptyDigest);
            }
        }
        if self.authority.grants_any() {
            return Err(CognitiveReadIngressError::AuthorityGranted);
        }
        if self.rows.is_empty() || self.rows.len() > MAX_CONTEXT_CANDIDATES_V2 {
            return Err(CognitiveReadIngressError::InvalidRowCount);
        }
        for pair in self.rows.windows(2) {
            if pair[0].item_id >= pair[1].item_id {
                return Err(CognitiveReadIngressError::NonCanonicalRows);
            }
        }
        if self.ingress_digest != self.compute_digest() {
            return Err(CognitiveReadIngressError::BindingDigestMismatch);
        }
        Ok(())
    }

    fn compute_digest(&self) -> Digest32 {
        let mut bytes = COGNITIVE_READ_INGRESS_DOMAIN.to_vec();
        for digest in [
            self.shadow_binding_digest,
            self.read_receipt_digest,
            self.generation_vector_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(
            &u64::try_from(self.rows.len())
                .unwrap_or(u64::MAX)
                .to_be_bytes(),
        );
        for row in &self.rows {
            push_id(&mut bytes, &row.item_id);
            bytes.extend_from_slice(row.source_digest.as_array());
            bytes.extend_from_slice(row.event_digest.as_array());
            push_id(&mut bytes, &row.legacy_record_id);
            bytes.extend_from_slice(&row.legacy_record_revision.to_be_bytes());
        }
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CognitiveReadIngressError {
    Shadow(CanonicalReadShadowV2Error),
    Compiler(ContextCompilerV2Error),
    IncompleteSourceRead { omitted: usize },
    InvalidRowCount,
    UnverifiedEvent(String),
    InactiveEvent(String),
    DuplicateItem(String),
    CandidateSetMismatch,
    CandidateSourceMismatch(String),
    CandidateGenerationMismatch(String),
    CandidateRoleMismatch(String),
    EmptyDigest,
    NonCanonicalRows,
    BindingDigestMismatch,
    AuthorityGranted,
}

impl fmt::Display for CognitiveReadIngressError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CognitiveReadIngressError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Shadow(error) => Some(error),
            Self::Compiler(error) => Some(error),
            _ => None,
        }
    }
}

impl From<CanonicalReadShadowV2Error> for CognitiveReadIngressError {
    fn from(error: CanonicalReadShadowV2Error) -> Self {
        Self::Shadow(error)
    }
}

impl From<ContextCompilerV2Error> for CognitiveReadIngressError {
    fn from(error: ContextCompilerV2Error) -> Self {
        Self::Compiler(error)
    }
}

/// Verify a complete revision-bound source read and produce an unforgeable,
/// authority-free ingress manifest.
///
/// Every row is restricted to an active, verified canonical memory event. The
/// derived source digest binds the complete shadow, exact legacy revision,
/// canonical event and every source revision. Actual context bytes remain a
/// separate admission concern: context.compiler V2 will still require the
/// existing verified admission to bind those bytes to this source digest.
pub fn verify_cognitive_read_ingress_v2(
    shadow: &CanonicalAuthoritativeReadShadowV2,
) -> Result<VerifiedCognitiveReadIngressV2, CognitiveReadIngressError> {
    shadow.validate()?;
    if shadow.omitted_count != 0 {
        return Err(CognitiveReadIngressError::IncompleteSourceRead {
            omitted: shadow.omitted_count,
        });
    }
    if shadow.rows.is_empty() || shadow.rows.len() > MAX_CONTEXT_CANDIDATES_V2 {
        return Err(CognitiveReadIngressError::InvalidRowCount);
    }

    let mut rows = Vec::with_capacity(shadow.rows.len());
    for row in &shadow.rows {
        if row.event.verification != MemoryVerificationStateV1::Verified {
            return Err(CognitiveReadIngressError::UnverifiedEvent(
                row.event_id.to_string(),
            ));
        }
        if row.event.lifecycle != MemoryLifecycleV1::Active {
            return Err(CognitiveReadIngressError::InactiveEvent(
                row.event_id.to_string(),
            ));
        }
        let item_id = row.event_id.as_stable_id().clone();
        rows.push(CognitiveReadIngressRowV2 {
            item_id,
            source_digest: source_digest(shadow.binding_digest, row),
            event_digest: row.event_digest,
            legacy_record_id: row.legacy_record_id.clone(),
            legacy_record_revision: row.legacy_record_revision.get(),
        });
    }
    rows.sort_by(|left, right| left.item_id.cmp(&right.item_id));
    for pair in rows.windows(2) {
        if pair[0].item_id == pair[1].item_id {
            return Err(CognitiveReadIngressError::DuplicateItem(
                pair[0].item_id.to_string(),
            ));
        }
    }

    let mut result = VerifiedCognitiveReadIngressV2 {
        shadow_binding_digest: shadow.binding_digest,
        read_receipt_digest: shadow.read_receipt_digest,
        generation_vector_digest: shadow.generation_vector_digest,
        rows,
        ingress_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    result.ingress_digest = result.compute_digest();
    result.validate()?;
    Ok(result)
}

/// Compile only when the V2 candidate set is the exact active/verified set from
/// one revision-bound cognitive read.
///
/// Cognitive source material is always untrusted evidence. The wrapper checks
/// source identity and generation before delegating to the existing V2
/// compiler, which independently rechecks tokenization, admission, scope,
/// authority domain, secret posture and budgets.
pub fn compile_cognitive_read_v2(
    ingress: &VerifiedCognitiveReadIngressV2,
    request: ContextCompilationRequestV2,
) -> Result<CompiledContextV2, CognitiveReadIngressError> {
    ingress.validate()?;
    if request.generation_vector_digest != ingress.generation_vector_digest {
        return Err(CognitiveReadIngressError::CandidateGenerationMismatch(
            "request".to_string(),
        ));
    }
    if request.candidates.len() != ingress.rows.len() {
        return Err(CognitiveReadIngressError::CandidateSetMismatch);
    }

    let expected = ingress
        .rows
        .iter()
        .map(|row| (row.item_id.clone(), row))
        .collect::<BTreeMap<_, _>>();
    let mut seen = BTreeMap::new();
    for candidate in &request.candidates {
        let Some(row) = expected.get(&candidate.item_id) else {
            return Err(CognitiveReadIngressError::CandidateSetMismatch);
        };
        if candidate.role != ContextRoleV2::UntrustedEvidence {
            return Err(CognitiveReadIngressError::CandidateRoleMismatch(
                candidate.item_id.to_string(),
            ));
        }
        if candidate.source_digest != row.source_digest {
            return Err(CognitiveReadIngressError::CandidateSourceMismatch(
                candidate.item_id.to_string(),
            ));
        }
        if candidate.generation_vector_digest != ingress.generation_vector_digest {
            return Err(CognitiveReadIngressError::CandidateGenerationMismatch(
                candidate.item_id.to_string(),
            ));
        }
        if seen.insert(candidate.item_id.clone(), ()).is_some() {
            return Err(CognitiveReadIngressError::DuplicateItem(
                candidate.item_id.to_string(),
            ));
        }
    }
    if seen.len() != expected.len() {
        return Err(CognitiveReadIngressError::CandidateSetMismatch);
    }
    compile_v2(request).map_err(Into::into)
}

/// Validate and compile in one call when the caller does not need to retain the
/// borrow-free manifest for a later request-local step.
pub fn compile_revision_bound_cognitive_read_v2(
    shadow: &CanonicalAuthoritativeReadShadowV2,
    request: ContextCompilationRequestV2,
) -> Result<CompiledContextV2, CognitiveReadIngressError> {
    let ingress = verify_cognitive_read_ingress_v2(shadow)?;
    compile_cognitive_read_v2(&ingress, request)
}

fn source_digest(shadow_binding: Digest32, row: &CanonicalReadShadowRowV2) -> Digest32 {
    let mut bytes = COGNITIVE_READ_INGRESS_ROW_DOMAIN.to_vec();
    bytes.extend_from_slice(shadow_binding.as_array());
    push_id(&mut bytes, &row.legacy_record_id);
    bytes.extend_from_slice(&row.legacy_record_revision.get().to_be_bytes());
    bytes.extend_from_slice(row.legacy_record_digest.as_array());
    push_id(&mut bytes, row.event_id.as_stable_id());
    bytes.extend_from_slice(row.event_digest.as_array());
    bytes.extend_from_slice(
        &u32::try_from(row.source_revisions.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    for source in &row.source_revisions {
        push_id(&mut bytes, &source.source_id);
        bytes.extend_from_slice(&source.source_revision.to_be_bytes());
        bytes.extend_from_slice(source.source_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "cognitive_read_ingress_tests.rs"]
mod tests;
