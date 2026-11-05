//! Bounded projections of one unchanged durable mutation observation.
//!
//! Cursors are read fences, not authority. A digest checks consistency of the
//! complete projection; signature and current-policy checks remain with owners.

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use super::SupervisordControlFence;
use super::SupervisordRequestValidationError;
use crate::MAX_UNKNOWN_EFFECT_DISPOSITIONS;
use crate::ProductionMutationReceipt;
use crate::ProductionMutationState;
use crate::SupervisorError;
use crate::UnknownEffectDisposition;

pub const PRODUCTION_MUTATION_PAGE_SCHEMA_VERSION: u32 = 1;
const HISTORY_PER_PAGE: usize = 4;
pub(crate) const MAX_PRODUCTION_MUTATION_PAGES: usize =
    MAX_UNKNOWN_EFFECT_DISPOSITIONS.div_ceil(HISTORY_PER_PAGE);
const MAX_PAGE_BYTES: usize = 60 * 1024;
const MAX_STATE_BYTES: usize = 262_144;
const MAX_AGGREGATE_PAGE_BYTES: usize = MAX_PRODUCTION_MUTATION_PAGES * MAX_PAGE_BYTES;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProductionMutationCursorV1 {
    pub schema_version: u32,
    pub intent_sha256: Sha256Digest,
    pub state_sha256: Sha256Digest,
    pub control_fence: SupervisordControlFence,
    pub control_revision: u64,
    pub history_offset: u16,
}

impl ProductionMutationCursorV1 {
    pub(super) fn validate(&self) -> Result<(), SupervisordRequestValidationError> {
        self.control_fence.validate()?;
        if self.schema_version != PRODUCTION_MUTATION_PAGE_SCHEMA_VERSION
            || self.history_offset == 0
            || usize::from(self.history_offset) >= MAX_UNKNOWN_EFFECT_DISPOSITIONS
            || !valid_digest(&self.intent_sha256)
            || !valid_digest(&self.state_sha256)
        {
            return Err(SupervisordRequestValidationError::InvalidRequest);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProductionMutationSummaryV1 {
    pub receipt: ProductionMutationReceipt,
    pub intent_sha256: Sha256Digest,
    pub release_transaction_sha256: Option<Sha256Digest>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProductionMutationPageV1 {
    pub schema_version: u32,
    pub control_fence: SupervisordControlFence,
    pub summary: Option<ProductionMutationSummaryV1>,
    pub state_sha256: Option<Sha256Digest>,
    pub history_offset: u16,
    pub history_total: u16,
    pub unknown_effects: Vec<UnknownEffectDisposition>,
    pub next_cursor: Option<ProductionMutationCursorV1>,
}

/// Capture state and fence under the same supervisor mutex before calling.
pub(crate) fn production_mutation_page(
    state: Option<ProductionMutationState>,
    fence: SupervisordControlFence,
    cursor: Option<&ProductionMutationCursorV1>,
) -> Result<ProductionMutationPageV1, SupervisorError> {
    let mut page = ProductionMutationPageV1 {
        schema_version: PRODUCTION_MUTATION_PAGE_SCHEMA_VERSION,
        control_fence: fence,
        summary: None,
        state_sha256: None,
        history_offset: 0,
        history_total: 0,
        unknown_effects: Vec::new(),
        next_cursor: None,
    };
    if let Some(state) = state {
        if state.unknown_effects.len() > MAX_UNKNOWN_EFFECT_DISPOSITIONS {
            return invalid("production mutation history exceeds its durable bound");
        }
        let digest = state_digest(&state)?;
        if let Some(cursor) = cursor {
            cursor
                .validate()
                .map_err(|_| page_error("invalid production mutation cursor"))?;
            if cursor.intent_sha256 != state.intent_sha256
                || cursor.state_sha256 != digest
                || cursor.control_fence != page.control_fence
                || cursor.control_revision != state.receipt.control_revision
                || usize::from(cursor.history_offset) >= state.unknown_effects.len()
            {
                return invalid("stale production mutation page; refresh status");
            }
            page.history_offset = cursor.history_offset;
        }
        page.history_total = u16::try_from(state.unknown_effects.len())
            .map_err(|_| page_error("production mutation history count overflow"))?;
        page.state_sha256 = Some(digest);
        page.summary = Some(ProductionMutationSummaryV1 {
            receipt: state.receipt,
            intent_sha256: state.intent_sha256,
            release_transaction_sha256: state.release_transaction_sha256,
        });
        page.unknown_effects = state
            .unknown_effects
            .into_iter()
            .skip(usize::from(page.history_offset))
            .take(HISTORY_PER_PAGE)
            .collect();
        page.next_cursor = page.expected_next_cursor()?;
    } else if cursor.is_some() {
        return invalid("stale production mutation page; refresh status");
    }
    page.validate(&page.control_fence.agent_id)?;
    Ok(page)
}

impl ProductionMutationPageV1 {
    fn expected_next_cursor(&self) -> Result<Option<ProductionMutationCursorV1>, SupervisorError> {
        let next = usize::from(self.history_offset) + self.unknown_effects.len();
        if next >= usize::from(self.history_total) {
            return Ok(None);
        }
        let summary = self
            .summary
            .as_ref()
            .ok_or_else(|| page_error("missing mutation summary"))?;
        Ok(Some(ProductionMutationCursorV1 {
            schema_version: PRODUCTION_MUTATION_PAGE_SCHEMA_VERSION,
            intent_sha256: summary.intent_sha256.clone(),
            state_sha256: self
                .state_sha256
                .clone()
                .ok_or_else(|| page_error("missing mutation digest"))?,
            control_fence: self.control_fence.clone(),
            control_revision: summary.receipt.control_revision,
            history_offset: u16::try_from(next)
                .map_err(|_| page_error("mutation offset overflow"))?,
        }))
    }

    fn validate(&self, agent_id: &AgentId) -> Result<usize, SupervisorError> {
        self.control_fence
            .validate()
            .map_err(|_| page_error("invalid mutation page fence"))?;
        if self.schema_version != PRODUCTION_MUTATION_PAGE_SCHEMA_VERSION
            || &self.control_fence.agent_id != agent_id
            || usize::from(self.history_total) > MAX_UNKNOWN_EFFECT_DISPOSITIONS
            || self.history_offset > self.history_total
            || (self.history_total > 0 && self.history_offset == self.history_total)
            || self.unknown_effects.len()
                != HISTORY_PER_PAGE.min(usize::from(self.history_total - self.history_offset))
        {
            return invalid("invalid production mutation page bounds or identity");
        }
        match (&self.summary, &self.state_sha256) {
            (Some(summary), Some(digest))
                if summary.receipt.agent_id == agent_id.as_str()
                    && valid_digest(&summary.intent_sha256)
                    && valid_digest(digest)
                    && summary
                        .release_transaction_sha256
                        .as_ref()
                        .is_none_or(valid_digest) => {}
            (None, None) if self.history_total == 0 && self.history_offset == 0 => {}
            _ => return invalid("incoherent production mutation page summary"),
        }
        if self.next_cursor != self.expected_next_cursor()? {
            return invalid("production mutation cursor does not match this page");
        }
        let bytes = encoded(self)?.len();
        if bytes > MAX_PAGE_BYTES {
            return invalid("production mutation page exceeded frame budget");
        }
        Ok(bytes)
    }
}

pub(crate) struct ProductionMutationPageAssembler {
    first: ProductionMutationPageV1,
    history: Vec<UnknownEffectDisposition>,
    next: Option<ProductionMutationCursorV1>,
    page_count: usize,
    page_bytes: usize,
}

impl ProductionMutationPageAssembler {
    pub(crate) fn new(
        mut page: ProductionMutationPageV1,
        agent_id: &AgentId,
    ) -> Result<Self, SupervisorError> {
        let page_bytes = page.validate(agent_id)?;
        if page.history_offset != 0 {
            return invalid("production mutation first page must start at zero");
        }
        Ok(Self {
            history: std::mem::take(&mut page.unknown_effects),
            next: page.next_cursor.clone(),
            first: page,
            page_count: 1,
            page_bytes,
        })
    }

    pub(crate) fn next_cursor(&self) -> Option<ProductionMutationCursorV1> {
        self.next.clone()
    }

    pub(crate) fn push(&mut self, page: ProductionMutationPageV1) -> Result<(), SupervisorError> {
        let bytes = page.validate(&self.first.control_fence.agent_id)?;
        if self.next.is_none()
            || self.page_count >= MAX_PRODUCTION_MUTATION_PAGES
            || page.control_fence != self.first.control_fence
            || page.summary != self.first.summary
            || page.state_sha256 != self.first.state_sha256
            || page.history_total != self.first.history_total
            || usize::from(page.history_offset) != self.history.len()
        {
            return invalid("production mutation pages are stale, repeated or out of order");
        }
        let total_bytes = self
            .page_bytes
            .checked_add(bytes)
            .ok_or_else(|| page_error("production mutation page byte count overflow"))?;
        if total_bytes > MAX_AGGREGATE_PAGE_BYTES {
            return invalid("production mutation pages exceeded aggregate bound");
        }
        self.history.extend(page.unknown_effects);
        self.next = page.next_cursor;
        self.page_count += 1;
        self.page_bytes = total_bytes;
        Ok(())
    }

    pub(crate) fn finish(self) -> Result<Option<ProductionMutationState>, SupervisorError> {
        if self.next.is_some() || self.history.len() != usize::from(self.first.history_total) {
            return invalid("production mutation history is incomplete");
        }
        let Some(summary) = self.first.summary else {
            return Ok(None);
        };
        let state = ProductionMutationState {
            receipt: summary.receipt,
            intent_sha256: summary.intent_sha256,
            release_transaction_sha256: summary.release_transaction_sha256,
            unknown_effects: self.history,
        };
        if Some(state_digest(&state)?) != self.first.state_sha256 {
            return invalid("assembled production mutation state digest differs");
        }
        Ok(Some(state))
    }
}

fn state_digest(state: &ProductionMutationState) -> Result<Sha256Digest, SupervisorError> {
    let bytes = encoded(state)?;
    if bytes.len() > MAX_STATE_BYTES {
        return invalid("production mutation state exceeds its bounded projection");
    }
    Ok(Sha256Digest::for_bytes(&bytes))
}

fn encoded(value: &impl Serialize) -> Result<Vec<u8>, SupervisorError> {
    serde_json::to_vec(value)
        .map_err(|error| page_error(&format!("encode production mutation page: {error}")))
}

fn valid_digest(digest: &Sha256Digest) -> bool {
    Sha256Digest::parse(digest.as_str().to_string()).is_ok()
}
fn page_error(message: &str) -> SupervisorError {
    SupervisorError::Invalid(message.to_string())
}
fn invalid<T>(message: &str) -> Result<T, SupervisorError> {
    Err(page_error(message))
}

#[cfg(test)]
#[path = "production_mutation_paging_tests.rs"]
mod tests;
