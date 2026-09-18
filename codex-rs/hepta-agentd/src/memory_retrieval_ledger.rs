//! Durable learning.ledger adapter for memory-retrieval decisions.
//!
//! The adapter owns no path, directory or authorization decision. A trusted host
//! must create or recover the canonical `DurableLedger` first and retain its
//! external acknowledgement witness separately. This type only serializes
//! retrieval Decision appends through that already-authorized owner.

use std::sync::Mutex;

use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::EpisodeDecision;
use codex_hepta_learning_ledger::LedgerAnchor;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_types::Digest32;

use crate::MemoryRetrievalDecisionSink;

pub struct DurableMemoryRetrievalDecisionSink {
    ledger: Mutex<DurableLedger>,
}

impl DurableMemoryRetrievalDecisionSink {
    pub fn new(ledger: DurableLedger) -> Result<Self, String> {
        ledger.snapshot().map_err(|error| error.to_string())?;
        Ok(Self {
            ledger: Mutex::new(ledger),
        })
    }

    pub fn current_anchor(&self) -> Result<Option<LedgerAnchor>, String> {
        let ledger = self
            .ledger
            .lock()
            .map_err(|_| "memory retrieval ledger lock poisoned".to_string())?;
        let snapshot = ledger.snapshot().map_err(|error| error.to_string())?;
        let Some(last) = snapshot.records().last() else {
            return Ok(None);
        };
        Ok(Some(LedgerAnchor {
            sequence: last.sequence.get(),
            chain_digest: snapshot.head_digest,
        }))
    }
}

impl MemoryRetrievalDecisionSink for DurableMemoryRetrievalDecisionSink {
    fn append_decision(&self, decision: EpisodeDecision) -> Result<Digest32, String> {
        let mut ledger = self
            .ledger
            .lock()
            .map_err(|_| "memory retrieval ledger lock poisoned".to_string())?;

        // Preserve exact idempotency even when the same decision is retried
        // after later ledger events. DurableLedger's predecessor-CAS is kept for
        // new events; equality is checked against the canonical committed fact.
        if let Some(existing) = ledger
            .records()
            .map_err(|error| error.to_string())?
            .iter()
            .find(|record| match &record.event {
                LedgerEvent::Decision(value) => value.record_id == decision.record_id,
                _ => false,
            })
        {
            return match &existing.event {
                LedgerEvent::Decision(value) if value == &decision => Ok(existing.chain_digest),
                LedgerEvent::Decision(_) => Err(
                    "memory retrieval decision identity conflicts with committed content".to_string(),
                ),
                _ => unreachable!("record filter admits only decision events"),
            };
        }

        let predecessor = ledger
            .snapshot()
            .map_err(|error| error.to_string())?
            .head_digest;
        let receipt = ledger
            .append(predecessor, LedgerEvent::Decision(decision))
            .map_err(|error| error.to_string())?;
        Ok(receipt.chain_digest)
    }
}

#[cfg(test)]
#[path = "memory_retrieval_ledger_tests.rs"]
mod tests;
