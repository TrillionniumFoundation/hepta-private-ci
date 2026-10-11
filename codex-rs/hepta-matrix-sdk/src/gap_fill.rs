//! Qualification-only forward pagination evidence; no product caller is enabled.
//!
//! Exact target equality proves traversal of the supplied token interval only.
//! It does not authenticate the caller's tokens, establish visible history before
//! the source, or authorize a cursor advance. Production binding still requires
//! owner-persisted coverage scope/anchors, authenticated SDK request provenance,
//! a shared all-room budget/deadline, decryption and mutation normalization, and
//! atomic coverage + deduplication + cursor persistence with crash reconciliation.
//! No caller may clear `limited` merely because this accumulator reached a token.
//! Matrix's `/messages` contract permits a `/sync` next_batch as `from`; its
//! syncing gap example uses the prior `since` and current room `prev_batch`.
//! This fixture still cannot establish that either supplied token is genuine.
//!
//! Raw event bounds apply after the SDK HTTP decoder. Token, scope and page-count
//! bounds separately bound metadata; the transcript retains digests, not payloads.
//! Chunk and ancillary state remain separate, in their received page order, and
//! repeated event IDs remain evidence for the downstream semantic normalizer.

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_matrix_protocol::MatrixBindingV1;
use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_protocol::MatrixRoomId;
use matrix_sdk::room::Messages;
use matrix_sdk::ruma::RoomVersionId;
use matrix_sdk::ruma::api::Direction;
use matrix_sdk::ruma::events::AnyStateEvent;
use matrix_sdk::ruma::events::AnySyncTimelineEvent;
use matrix_sdk::ruma::serde::Raw;
use serde::Deserialize;
use serde::Serialize;

const MAX_PAGES: usize = 8;
const MAX_PAGE_EVENTS: usize = 64;
const MAX_EVENTS: usize = 512;
const MAX_EVENT_BYTES: usize = 1024 * 1024;
const MAX_BYTES: usize = 16 * 1024 * 1024;
const MAX_TOKEN_BYTES: usize = 4096;
const MAX_HOMESERVER_BYTES: usize = 4096;

#[derive(Clone, Serialize)]
struct GapFillLimits {
    pages: usize,
    events: usize,
    event_bytes: usize,
}

#[derive(Clone)]
struct GapFillPlan {
    binding: MatrixBindingV1,
    generation: u64,
    room_id: MatrixRoomId,
    connection_sha256: Sha256Digest,
    room_version: RoomVersionId,
    filter_sha256: Sha256Digest,
    source_sync_token: String,
    target_prev_batch: String,
    response_next_batch: String,
    limits: GapFillLimits,
}

#[derive(Clone, Eq, PartialEq, Serialize)]
struct GapFillRequest {
    scope_sha256: Sha256Digest,
    room_id: MatrixRoomId,
    from: String,
    to: String,
    direction: Direction,
    limit: usize,
    filter_sha256: Sha256Digest,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
enum GapFillStatus {
    Fetching,
    ReachedTarget,
    VisibilityBoundary,
    PageLimitReached,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct GapFillObservation {
    status: GapFillStatus,
    pages: usize,
    events: usize,
    event_bytes: usize,
    transcript_sha256: Sha256Digest,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum GapFillError {
    InvalidPlan,
    RequestDrift,
    InvalidPage,
    Bounds,
    TokenCycle,
    Terminal,
    Encoding,
}

struct GapFillAccumulator {
    plan: GapFillPlan,
    request: GapFillRequest,
    visited_tokens: Vec<String>,
    pages: Vec<AcceptedGapPage>,
    observation: GapFillObservation,
}

// SDK TimelineEvent metadata can contain unbounded recursive bundled events.
// Retain only the raw envelopes covered by this accumulator's bounds/digest.
struct AcceptedGapPage {
    start: String,
    end: Option<String>,
    chunk: Vec<Raw<AnySyncTimelineEvent>>,
    state: Vec<Raw<AnyStateEvent>>,
}

#[derive(Deserialize)]
struct GapEventScope {
    room_id: MatrixRoomId,
    #[serde(rename = "event_id")]
    _event_id: MatrixEventId,
}

impl GapFillAccumulator {
    fn new(plan: GapFillPlan) -> Result<Self, GapFillError> {
        if plan.binding.validate().is_err()
            || plan.binding.homeserver.as_str().len() > MAX_HOMESERVER_BYTES
            || plan.generation == 0
            || !plan.binding.allowed_rooms.contains(&plan.room_id)
            || plan.room_version.rules().is_none()
            || !valid_token(&plan.source_sync_token)
            || !valid_token(&plan.target_prev_batch)
            || !valid_token(&plan.response_next_batch)
            || plan.source_sync_token == plan.target_prev_batch
            || !(1..=MAX_PAGES).contains(&plan.limits.pages)
            || plan.limits.events > MAX_EVENTS
            || plan.limits.event_bytes > MAX_BYTES
        {
            return Err(GapFillError::InvalidPlan);
        }
        let scope_sha256 = digest(&(
            "hepta.matrix.gap-fill.qualification.v1",
            &plan.binding,
            plan.generation,
            &plan.room_id,
            &plan.connection_sha256,
            &plan.room_version,
            &plan.filter_sha256,
            &plan.source_sync_token,
            &plan.target_prev_batch,
            &plan.response_next_batch,
            &plan.limits,
            MAX_PAGE_EVENTS,
            MAX_EVENT_BYTES,
            Direction::Forward,
            GapFillStatus::Fetching,
        ))?;
        let request = GapFillRequest {
            scope_sha256: scope_sha256.clone(),
            room_id: plan.room_id.clone(),
            from: plan.source_sync_token.clone(),
            to: plan.target_prev_batch.clone(),
            direction: Direction::Forward,
            limit: MAX_PAGE_EVENTS,
            filter_sha256: plan.filter_sha256.clone(),
        };
        Ok(Self {
            visited_tokens: vec![plan.source_sync_token.clone()],
            plan,
            request,
            pages: Vec::new(),
            observation: GapFillObservation {
                status: GapFillStatus::Fetching,
                pages: 0,
                events: 0,
                event_bytes: 0,
                transcript_sha256: scope_sha256,
            },
        })
    }

    fn append(
        &mut self,
        request: &GapFillRequest,
        page: Messages,
    ) -> Result<GapFillStatus, GapFillError> {
        if self.observation.status != GapFillStatus::Fetching {
            return Err(GapFillError::Terminal);
        }
        if request != &self.request {
            return Err(GapFillError::RequestDrift);
        }
        if page.start != request.from
            || !valid_token(&page.start)
            || page.end.as_deref().is_some_and(|end| !valid_token(end))
        {
            return Err(GapFillError::InvalidPage);
        }
        if page
            .end
            .as_ref()
            .is_some_and(|end| self.visited_tokens.contains(end))
        {
            return Err(GapFillError::TokenCycle);
        }
        let page_events = page
            .chunk
            .len()
            .checked_add(page.state.len())
            .ok_or(GapFillError::Bounds)?;
        let events = self
            .observation
            .events
            .checked_add(page_events)
            .ok_or(GapFillError::Bounds)?;
        if page_events > MAX_PAGE_EVENTS || events > self.plan.limits.events {
            return Err(GapFillError::Bounds);
        }
        let mut event_bytes = self.observation.event_bytes;
        // Check every size before parsing fields, hashing, or retaining a page.
        for raw in page
            .chunk
            .iter()
            .map(|event| event.raw().json())
            .chain(page.state.iter().map(Raw::json))
        {
            let size = raw.get().len();
            event_bytes = event_bytes.checked_add(size).ok_or(GapFillError::Bounds)?;
            if size > MAX_EVENT_BYTES || event_bytes > self.plan.limits.event_bytes {
                return Err(GapFillError::Bounds);
            }
        }
        let mut chunk_digests = Vec::with_capacity(page.chunk.len());
        let mut state_digests = Vec::with_capacity(page.state.len());
        for event in &page.chunk {
            chunk_digests.push(scoped_event_digest(event.raw(), &self.plan.room_id)?);
        }
        for event in &page.state {
            state_digests.push(scoped_event_digest(event, &self.plan.room_id)?);
        }
        let pages = self.observation.pages + 1;
        let status = match page.end.as_deref() {
            Some(end) if end == self.plan.target_prev_batch => GapFillStatus::ReachedTarget,
            None => GapFillStatus::VisibilityBoundary,
            Some(_) if pages == self.plan.limits.pages => GapFillStatus::PageLimitReached,
            Some(_) => GapFillStatus::Fetching,
        };
        let transcript_sha256 = digest(&(
            "hepta.matrix.gap-page.qualification.v1",
            &self.observation.transcript_sha256,
            request,
            &page.start,
            &page.end,
            &chunk_digests,
            &state_digests,
            pages,
            events,
            event_bytes,
            status,
        ))?;
        // Every rejection above leaves the previously accepted evidence intact.
        if let Some(end) = &page.end {
            self.visited_tokens.push(end.clone());
            self.request.from = end.clone();
        }
        self.pages.push(AcceptedGapPage {
            start: page.start,
            end: page.end,
            chunk: page.chunk.iter().map(|event| event.raw().clone()).collect(),
            state: page.state,
        });
        self.observation = GapFillObservation {
            status,
            pages,
            events,
            event_bytes,
            transcript_sha256,
        };
        Ok(status)
    }
}

fn valid_token(token: &str) -> bool {
    (1..=MAX_TOKEN_BYTES).contains(&token.len())
        && token.bytes().all(|byte| (b' '..=b'~').contains(&byte))
}

fn scoped_event_digest<T>(
    raw: &Raw<T>,
    room_id: &MatrixRoomId,
) -> Result<Sha256Digest, GapFillError> {
    if !raw.json().get().trim_start().starts_with('{') {
        return Err(GapFillError::InvalidPage);
    }
    // Derive rejects duplicate scope keys, including escaped equivalents.
    // Raw::get_field instead accepts the last occurrence of a repeated key.
    let scope: GapEventScope =
        serde_json::from_str(raw.json().get()).map_err(|_| GapFillError::InvalidPage)?;
    if &scope.room_id != room_id {
        return Err(GapFillError::InvalidPage);
    }
    Ok(Sha256Digest::for_bytes(raw.json().get().as_bytes()))
}

fn digest(value: &impl Serialize) -> Result<Sha256Digest, GapFillError> {
    serde_json::to_vec(value)
        .map(|bytes| Sha256Digest::for_bytes(&bytes))
        .map_err(|_| GapFillError::Encoding)
}

#[path = "gap_fill_tests.rs"]
mod tests;
