//! Lossless, bounded owner metadata observations; never authorizes a write.
use crate::runtime_view::RuntimeUnavailable;
use serde::Deserialize;

pub const MAX_OWNER_STATUS_BYTES: usize = 4096;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
enum Disposition {
    Missing,
    Active,
    ExpiredActive,
    Released,
    RolledBack,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
enum ReadFailure {
    ReadFailed,
    IntegrityRejected,
    InvalidObservation,
    Busy,
    TimedOut,
}

#[derive(Clone, Debug, PartialEq, Eq, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
enum Observation {
    NotAttached {},
    Observed {
        generation: Option<u64>,
        disposition: Disposition,
    },
    Unavailable {
        reason: ReadFailure,
    },
}

#[derive(Clone, Debug, PartialEq, Eq, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OwnerStatusDocument {
    schema: String,
    observation: Observation,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum OwnerReadState {
    Unavailable(RuntimeUnavailable),
    Loading,
    Received(OwnerStatusDocument),
}

impl OwnerReadState {
    /// Display-only headline derived from validated metadata, never write authority.
    /// Recorded dispositions are deliberately distinct from current health.
    pub fn observation_headline(&self) -> &'static str {
        match self {
            Self::Unavailable(RuntimeUnavailable::NotConnected) => "Not requested",
            Self::Unavailable(_) => "Unavailable",
            Self::Loading => "Reading…",
            Self::Received(document) => match document.observation {
                Observation::NotAttached {} => "Not attached",
                Observation::Unavailable { .. } => "Unavailable",
                Observation::Observed { disposition, .. } => match disposition {
                    Disposition::Missing => "Recorded missing",
                    Disposition::Active => "Recorded active",
                    Disposition::ExpiredActive => "Recorded expired active",
                    Disposition::Released => "Recorded released",
                    Disposition::RolledBack => "Recorded rolled back",
                },
            },
        }
    }

    pub fn display_text(&self) -> String {
        let detail = match self {
            Self::Unavailable(RuntimeUnavailable::NotConnected) => "No owner observation has been requested for this view. Use the read-only control above to query metadata.".to_owned(),
            Self::Unavailable(reason) => format!("Production owner observation unavailable ({reason:?})."),
            Self::Loading => "Reading a point-in-time production owner observation…".to_owned(),
            Self::Received(document) => match document.observation {
                Observation::NotAttached {} => "Production owner: not attached. No lease observation is available.".to_owned(),
                Observation::Observed {generation, disposition} => format!(
                    "Point-in-time production lease observation\nRecorded generation: {}\nRecorded disposition: {disposition:?}",
                    generation.map_or_else(|| "none".to_owned(), |value| value.to_string())
                ),
                Observation::Unavailable {reason} => format!("Production owner observation unavailable ({reason:?})."),
            },
        };
        format!(
            "{detail}\nThis is not current write authority. Chat and commands remain unavailable."
        )
    }
}

#[derive(Debug)]
pub struct OwnerReader {
    next: u64,
    active: Option<u64>,
    state: OwnerReadState,
}
impl Default for OwnerReader {
    fn default() -> Self {
        Self {
            next: 0,
            active: None,
            state: OwnerReadState::Unavailable(RuntimeUnavailable::NotConnected),
        }
    }
}
impl OwnerReader {
    pub fn state(&self) -> &OwnerReadState {
        &self.state
    }
    pub fn begin(&mut self) -> Option<u64> {
        if self.active.is_some() {
            return None;
        }
        let Some(next) = self.next.checked_add(1) else {
            self.state = OwnerReadState::Unavailable(RuntimeUnavailable::CounterExhausted);
            return None;
        };
        self.next = next;
        self.active = Some(next);
        self.state = OwnerReadState::Loading;
        Some(next)
    }
    pub fn complete(&mut self, ticket: u64, status: u16, bytes: &[u8]) -> bool {
        if self.active != Some(ticket) {
            return false;
        }
        self.active = None;
        self.state = match parse(status, bytes) {
            Ok(value) => OwnerReadState::Received(value),
            Err(reason) => OwnerReadState::Unavailable(reason),
        };
        true
    }
    pub fn fail(&mut self, ticket: u64, reason: RuntimeUnavailable) -> bool {
        if self.active != Some(ticket) {
            return false;
        }
        self.active = None;
        self.state = OwnerReadState::Unavailable(reason);
        true
    }
    pub fn disconnect(&mut self) {
        self.active = None;
        self.state = OwnerReadState::Unavailable(RuntimeUnavailable::NotConnected);
    }
}
fn parse(status: u16, bytes: &[u8]) -> Result<OwnerStatusDocument, RuntimeUnavailable> {
    if status != 200 {
        return Err(RuntimeUnavailable::Transport);
    }
    if bytes.len() > MAX_OWNER_STATUS_BYTES {
        return Err(RuntimeUnavailable::Oversize);
    }
    let value: OwnerStatusDocument =
        serde_json::from_slice(bytes).map_err(|_| RuntimeUnavailable::InvalidStatus)?;
    if value.schema != "hepta.owner-lease-observation.v1" {
        return Err(RuntimeUnavailable::InvalidStatus);
    }
    if let Observation::Observed {
        generation,
        disposition,
    } = value.observation
        && (disposition == Disposition::Missing) != generation.is_none()
    {
        return Err(RuntimeUnavailable::InvalidStatus);
    }
    Ok(value)
}

#[cfg(test)]
#[path = "owner_view_tests.rs"]
mod tests;
