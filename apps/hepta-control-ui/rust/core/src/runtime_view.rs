//! Bounded read-only projection of the existing runtime status endpoint.
//! This state never admits a chat owner, signs text, or grants operation authority.

use serde::Deserialize;

/// JSON has no provider-wide encoded-size guarantee. Oversize is unavailable,
/// never truncated. This accommodates maximal escaped ordinary platform paths.
pub const MAX_RUNTIME_JSON_BYTES: usize = 256 * 1024;

#[derive(Clone, Debug, PartialEq, Eq, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RuntimeSnapshot {
    schema: String,
    product: String,
    status: String,
    state_root: String,
    state: RuntimeState,
    authority: RuntimeAuthority,
}

#[derive(Clone, Debug, PartialEq, Eq, Deserialize)]
#[serde(deny_unknown_fields)]
struct RuntimeState {
    adapter: String,
    schema_version: i64,
    outcome_generation: i64,
    preference_generation: i64,
    runtime_snapshot_version: u64,
    runtime_snapshot_generation: u64,
    integrity_binding_present: bool,
    integrity_verification: String,
    open_mode: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Deserialize)]
#[serde(deny_unknown_fields)]
struct RuntimeAuthority {
    telegram: bool,
    outbound: bool,
    model_invocation: bool,
    operator_mutation: bool,
    enforce: bool,
    promotion: bool,
    retirement: bool,
    automatic_transition: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RuntimeUnavailable {
    NotConnected,
    Transport,
    TimedOut,
    Oversize,
    InvalidStatus,
    CounterExhausted,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum RuntimeReadState {
    Unavailable(RuntimeUnavailable),
    Loading,
    Ready(Box<RuntimeSnapshot>),
}

#[derive(Debug)]
pub struct RuntimeReader {
    next: u64,
    active: Option<u64>,
    state: RuntimeReadState,
}

impl Default for RuntimeReader {
    fn default() -> Self {
        Self {
            next: 0,
            active: None,
            state: RuntimeReadState::Unavailable(RuntimeUnavailable::NotConnected),
        }
    }
}

impl RuntimeReader {
    pub fn state(&self) -> &RuntimeReadState {
        &self.state
    }

    pub fn begin(&mut self) -> Option<u64> {
        if self.active.is_some() {
            return None;
        }
        let Some(next) = self.next.checked_add(1) else {
            self.state = RuntimeReadState::Unavailable(RuntimeUnavailable::CounterExhausted);
            return None;
        };
        self.next = next;
        self.active = Some(next);
        self.state = RuntimeReadState::Loading;
        Some(next)
    }

    pub fn complete(&mut self, ticket: u64, status: u16, bytes: &[u8]) -> bool {
        if self.active != Some(ticket) {
            return false;
        }
        self.active = None;
        self.state = match parse_snapshot(status, bytes) {
            Ok(snapshot) => RuntimeReadState::Ready(Box::new(snapshot)),
            Err(reason) => RuntimeReadState::Unavailable(reason),
        };
        true
    }

    pub fn fail(&mut self, ticket: u64, reason: RuntimeUnavailable) -> bool {
        if self.active != Some(ticket) {
            return false;
        }
        self.active = None;
        self.state = RuntimeReadState::Unavailable(reason);
        true
    }

    pub fn disconnect(&mut self) -> Option<u64> {
        self.state = RuntimeReadState::Unavailable(RuntimeUnavailable::NotConnected);
        self.active.take()
    }
}

fn parse_snapshot(status: u16, bytes: &[u8]) -> Result<RuntimeSnapshot, RuntimeUnavailable> {
    if bytes.len() > MAX_RUNTIME_JSON_BYTES {
        return Err(RuntimeUnavailable::Oversize);
    }
    if status != 200 {
        return Err(RuntimeUnavailable::Transport);
    }
    let value: RuntimeSnapshot =
        serde_json::from_slice(bytes).map_err(|_| RuntimeUnavailable::InvalidStatus)?;
    let a = &value.authority;
    if value.schema != "hepta_vnext_live_runtime_status_v1"
        || value.product != "hepta"
        || value.status != "ready"
        || value.state.schema_version != 5
        || value.state.outcome_generation < 0
        || value.state.preference_generation < 0
        || a.telegram
        || a.outbound
        || a.model_invocation
        || a.operator_mutation
        || a.enforce
        || a.promotion
        || a.retirement
        || a.automatic_transition
    {
        return Err(RuntimeUnavailable::InvalidStatus);
    }
    Ok(value)
}

impl RuntimeReadState {
    pub fn display_text(&self) -> String {
        match self {
            Self::Loading => "Read-only runtime: checking current status…\nNo chat or operation authority is provided by this view.".to_owned(),
            Self::Unavailable(reason) => format!("Read-only runtime unavailable ({reason:?}).\nNo current status is shown. Chat and operation commands remain unavailable."),
            Self::Ready(value) => format!(
                "Read-only runtime: {}\nStorage schema: {} · snapshot version: {} · generation: {}\nOutcomes generation: {} · preferences generation: {}\nAdapter: {:?}\nIntegrity reported: {:?} · binding present: {}\nOpen mode: {:?}\nStorage root: {:?}\nAll effect gates reported closed. This observation does not grant chat or operation authority.",
                value.status, value.state.schema_version, value.state.runtime_snapshot_version, value.state.runtime_snapshot_generation,
                value.state.outcome_generation, value.state.preference_generation,
                value.state.adapter, value.state.integrity_verification, value.state.integrity_binding_present,
                value.state.open_mode, value.state_root
            ),
        }
    }
}

#[cfg(test)]
#[path = "runtime_view_tests.rs"]
mod tests;
