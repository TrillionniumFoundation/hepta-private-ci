//! Process-local issuance for the exact context published by this Agentd body.
//! Public digests identify a plan; only this private owner records its issuance.

use std::collections::BTreeMap;
use std::io;
use std::io::Write;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_types::Digest32;
use serde::Serialize;

use crate::CognitiveContextItem;
use crate::CognitiveContextPlan;
use crate::CognitiveContextSnapshot;

const MAX_ISSUED_CONTEXTS: usize = 256;
const MAX_PLAN_LIFETIME_MICROS: u64 = 1_000_000;

/// A completed owner read, before the host's final lifecycle fence and issuance.
pub(crate) struct PlannedContextRead {
    pub(crate) snapshot: CognitiveContextSnapshot,
    owner: String,
    body_generation: u64,
    deadline: Instant,
}

impl PlannedContextRead {
    pub(crate) fn new(
        snapshot: CognitiveContextSnapshot,
        owner: &str,
        body_generation: u64,
        observed_at: Instant,
        observed_at_micros: u64,
        expires_at_micros: u64,
    ) -> Result<Self, String> {
        let lifetime = expires_at_micros
            .checked_sub(observed_at_micros)
            .filter(|lifetime| (1..=MAX_PLAN_LIFETIME_MICROS).contains(lifetime))
            .ok_or_else(|| "invalid context plan lifetime".to_string())?;
        if owner.is_empty() || owner.len() > 128 || body_generation == 0 {
            return Err("invalid context issuance owner/body".to_string());
        }
        let deadline = observed_at
            .checked_add(Duration::from_micros(lifetime))
            .ok_or_else(|| "context plan monotonic deadline overflow".to_string())?;
        Ok(Self {
            snapshot,
            owner: owner.to_string(),
            body_generation,
            deadline,
        })
    }
}

struct IssuedContext {
    owner: String,
    body_generation: u64,
    published_digest: Digest32,
    deadline: Instant,
}

#[derive(Default)]
pub(crate) struct ContextPlanIssuer {
    issued: Mutex<BTreeMap<Digest32, IssuedContext>>,
}

impl ContextPlanIssuer {
    /// Called only after the host rechecks its lifecycle fence. No context text
    /// is retained, and a full set of live receipts closes this read locally.
    pub(crate) fn issue(
        &self,
        read: PlannedContextRead,
    ) -> Result<CognitiveContextSnapshot, String> {
        let receipt = receipt_digest(&read.snapshot)?;
        let published_digest = ContextEnvelope::from(&read.snapshot).digest()?;
        let mut issued = self
            .issued
            .lock()
            .map_err(|_| "context issuance owner unavailable".to_string())?;
        let now = Instant::now();
        if now >= read.deadline {
            return Err("context plan expired before publication".to_string());
        }
        issued.retain(|_, context| now < context.deadline);
        if issued.contains_key(&receipt) {
            return Err("context receipt already issued by this live Agentd body".to_string());
        }
        if issued.len() == MAX_ISSUED_CONTEXTS {
            return Err("context issuance capacity unavailable".to_string());
        }
        issued.insert(
            receipt,
            IssuedContext {
                owner: read.owner,
                body_generation: read.body_generation,
                published_digest,
                deadline: read.deadline,
            },
        );
        Ok(read.snapshot)
    }

    /// Repeated before and after owner/CURRENT I/O. A new Agentd body has an
    /// empty issuer, so a public hash cannot transfer or renew an old receipt.
    pub(crate) fn validate(
        &self,
        owner: &str,
        body_generation: u64,
        snapshot: &CognitiveContextSnapshot,
    ) -> Result<(), String> {
        let published_digest = ContextEnvelope::from(snapshot).digest()?;
        let receipt = receipt_digest(snapshot)?;
        let mut issued = self
            .issued
            .lock()
            .map_err(|_| "context issuance owner unavailable".to_string())?;
        let now = Instant::now();
        issued.retain(|_, context| now < context.deadline);
        let context = issued
            .get(&receipt)
            .ok_or_else(|| "context plan was not issued by this live Agentd body".to_string())?;
        if context.owner != owner
            || context.body_generation != body_generation
            || context.published_digest != published_digest
        {
            return Err("context differs from this body's issued publication".to_string());
        }
        Ok(())
    }

    pub(crate) fn retract(&self, snapshot: &CognitiveContextSnapshot) {
        if let Ok(receipt) = receipt_digest(snapshot)
            && let Ok(mut issued) = self.issued.lock()
        {
            issued.remove(&receipt);
        }
    }
}

fn receipt_digest(snapshot: &CognitiveContextSnapshot) -> Result<Digest32, String> {
    snapshot
        .plan
        .as_ref()
        .ok_or_else(|| "context final use requires an issued plan".to_string())?
        .plan_receipt_digest
        .parse()
        .map_err(|error| format!("invalid context plan receipt: {error}"))
}

/// Borrow the native wire fields to bound serialization before copying content.
/// Field order deliberately matches `CognitiveContextSnapshot` serialization.
#[derive(Serialize)]
pub(crate) struct ContextEnvelope<'a> {
    pub(crate) snapshot_digest: &'a str,
    pub(crate) read_digest: &'a str,
    pub(crate) omitted_records: u64,
    pub(crate) items: &'a [CognitiveContextItem],
    pub(crate) plan: Option<&'a CognitiveContextPlan>,
}

impl<'a> From<&'a CognitiveContextSnapshot> for ContextEnvelope<'a> {
    fn from(snapshot: &'a CognitiveContextSnapshot) -> Self {
        Self {
            snapshot_digest: &snapshot.snapshot_digest,
            read_digest: &snapshot.read_digest,
            omitted_records: snapshot.omitted_records,
            items: &snapshot.items,
            plan: snapshot.plan.as_ref(),
        }
    }
}

impl ContextEnvelope<'_> {
    pub(crate) fn digest(&self) -> Result<Digest32, String> {
        if self.items.len() > 4 {
            return Err("context accepts at most four items".to_string());
        }
        let mut encoded =
            BoundedContextWriter(Vec::with_capacity(crate::MAX_COGNITIVE_CONTEXT_BYTES));
        serde_json::to_writer(&mut encoded, self).map_err(|error| {
            format!("context exceeds delivery budget or cannot encode: {error}")
        })?;
        Ok(Digest32::of_bytes(&encoded.0))
    }
}

struct BoundedContextWriter(Vec<u8>);

impl Write for BoundedContextWriter {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if bytes.len() > crate::MAX_COGNITIVE_CONTEXT_BYTES - self.0.len() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "context JSON byte limit",
            ));
        }
        self.0.extend_from_slice(bytes);
        Ok(bytes.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

#[cfg(test)]
#[path = "cognitive_context_issuer_tests.rs"]
mod tests;
